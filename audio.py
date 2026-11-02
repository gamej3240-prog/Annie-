"""Finding, downloading and checking audio (duration/size).

Supported:
  1. An audio file sent in Telegram (reply with /play)
  2. Direct audio link (.mp3, .ogg ...)
  3. Links from allowed domains (via yt-dlp)
  4. Search by name: Internet Archive (free, no API key needed)
     (YouTube search only when you set ENABLE_YT_SEARCH=true in .env)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import aiohttp

from config import AUDIO_EXTENSIONS, Config

log = logging.getLogger(__name__)

USER_AGENT = "MusicBot/1.0 (personal Telegram bot)"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/"
IA_DOWNLOAD = "https://archive.org/download/"


class AudioError(Exception):
    """An error whose message can be shown to the user as is."""


@dataclass
class Track:
    title: str
    path: str  # downloaded file on the device
    duration: int  # seconds
    requested_by: str
    source: str
    query: str = ""  # original link / search text (used to save the song to a playlist)

    @property
    def duration_text(self) -> str:
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


def remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _new_path(cfg: Config, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    return os.path.join(cfg.download_dir, f"{uuid.uuid4().hex}{ext}")


async def probe_duration(path: str) -> int:
    """Gets the duration with ffprobe. Raises AudioError if it is not audio."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise AudioError("ffprobe is not installed (install ffmpeg).")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise AudioError("Checking the file took too long.")
    try:
        return int(float(out.decode().strip()))
    except ValueError:
        raise AudioError("This file does not look like valid audio.")


async def _finalize(path: str, title: str, who: str, source: str, cfg: Config) -> Track:
    """After the download, checks the duration and builds a Track."""
    try:
        duration = await probe_duration(path)
        if duration <= 0:
            raise AudioError("Could not detect the audio length.")
        if duration > cfg.max_duration:
            raise AudioError(f"Song is too long (max {cfg.max_duration // 60} min).")
    except AudioError:
        remove_file(path)
        raise
    return Track(title=title[:120], path=path, duration=duration, requested_by=who, source=source)


# ---------------------------------------------------------------- download

async def _download_once(url: str, dest: str, max_bytes: int) -> None:
    timeout = aiohttp.ClientTimeout(total=600, sock_connect=15, sock_read=30)
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                raise AudioError(f"Could not get the file from the link (HTTP {resp.status}).")
            if resp.content_length and resp.content_length > max_bytes:
                raise AudioError(f"File is too large (max {max_bytes // 1024 // 1024} MB).")
            written = 0
            with open(dest, "wb") as fh:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise AudioError(f"File is too large (max {max_bytes // 1024 // 1024} MB).")
                    fh.write(chunk)


async def download_file(url: str, dest: str, max_bytes: int, attempts: int = 3) -> None:
    """If the network drops, retries up to 3 times."""
    for attempt in range(1, attempts + 1):
        try:
            await _download_once(url, dest, max_bytes)
            return
        except AudioError:
            remove_file(dest)
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            remove_file(dest)
            log.warning("Download fail (try %d/%d): %s", attempt, attempts, exc)
            if attempt == attempts:
                raise AudioError("Network problem: the download failed. Please try again later.")
            await asyncio.sleep(2 * attempt)


async def _from_direct_url(url: str, title: str | None, who: str, cfg: Config, source: str) -> Track:
    path_part = urlparse(url).path
    ext = os.path.splitext(path_part)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        ext = ".mp3"
    dest = _new_path(cfg, ext)
    await download_file(url, dest, cfg.max_file_mb * 1024 * 1024)
    name = title or os.path.basename(path_part) or "Audio"
    return await _finalize(dest, name, who, source, cfg)


# --------------------------------------------------------- Internet Archive

async def search_archive(query: str, max_bytes: int) -> tuple[str, str]:
    """Searches audio on Internet Archive. Returns (title, download_url)."""
    clean = re.sub(r"[^\w\s]", " ", query, flags=re.UNICODE).strip()
    if not clean:
        raise AudioError("Please type a song name to search.")
    params = [
        ("q", f"({clean}) AND mediatype:audio"),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("rows", "5"),
        ("page", "1"),
        ("output", "json"),
    ]
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}, timeout=timeout) as session:
            async with session.get(IA_SEARCH, params=params) as resp:
                if resp.status != 200:
                    raise AudioError("The search service is not working right now.")
                data = await resp.json(content_type=None)
            for doc in data.get("response", {}).get("docs", []):
                ident = doc.get("identifier")
                if not ident:
                    continue
                async with session.get(IA_META + quote(ident)) as resp:
                    if resp.status != 200:
                        continue
                    meta = await resp.json(content_type=None)
                doc_title = doc.get("title") or ident
                if isinstance(doc_title, list):
                    doc_title = doc_title[0] if doc_title else ident
                for item in meta.get("files", []):
                    name = item.get("name", "")
                    if not name.lower().endswith(".mp3"):
                        continue
                    try:
                        size = int(item.get("size") or 0)
                    except ValueError:
                        size = 0
                    if size and size > max_bytes:
                        continue
                    title = item.get("title") or doc_title
                    return str(title), f"{IA_DOWNLOAD}{quote(ident)}/{quote(name)}"
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise AudioError("Network problem: the search failed.")
    raise AudioError(
        "Could not find this song on Internet Archive. Send a direct .mp3 link or "
        "reply to an audio file with /play."
    )


# ------------------------------------------------------------------ yt-dlp

def _ytdlp_opts(cfg: Config, youtube: bool) -> dict:
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": os.path.join(cfg.download_dir, f"{uuid.uuid4().hex}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 3,
        "max_filesize": cfg.max_file_mb * 1024 * 1024,
    }
    if youtube:
        # Newer YouTube needs a JavaScript runtime (nodejs)
        if shutil.which("node"):
            opts["js_runtimes"] = {"node": {}}
        cookies = os.environ.get("YT_COOKIES", "cookies.txt")
        if os.path.exists(cookies):
            opts["cookiefile"] = cookies
    return opts


SEARCH_RESULTS = 5  # how many search results to look at


def _pick_search_result(target: str, cfg: Config, youtube: bool) -> str:
    """For 'ytsearch:' / 'scsearch:' targets returns the URL of the first result that is not
    too long. Other targets are returned unchanged. Only a quick (flat) search, nothing is downloaded."""
    import yt_dlp

    if not target.startswith(("ytsearch", "scsearch")):
        return target
    prefix, _, text = target.partition(":")
    opts = _ytdlp_opts(cfg, youtube)
    opts["extract_flat"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"{prefix.rstrip('0123456789')}{SEARCH_RESULTS}:{text}", download=False)
    entries = [e for e in (info or {}).get("entries") or [] if e]
    urls = [(e.get("duration"), e.get("url") or e.get("webpage_url")) for e in entries]
    urls = [(d, u) for d, u in urls if u]
    if not urls:
        raise AudioError("Nothing found.")
    for duration, url in urls:
        if not duration or duration <= cfg.max_duration:
            return url
    return urls[0][1]  # all too long: the normal duration check will explain it


def _ytdlp_blocking(target: str, cfg: Config, youtube: bool = False) -> tuple[str, str]:
    import yt_dlp  # lazy import: RAM is used only when needed

    target = _pick_search_result(target, cfg, youtube)
    with yt_dlp.YoutubeDL(_ytdlp_opts(cfg, youtube)) as ydl:
        info = ydl.extract_info(target, download=False)
        if info and info.get("entries"):
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise AudioError("Nothing found.")
            info = entries[0]
        if not info:
            raise AudioError("Nothing found.")
        duration = info.get("duration") or 0
        if duration and duration > cfg.max_duration:
            raise AudioError(f"Song is too long (max {cfg.max_duration // 60} min).")
        info = ydl.process_ie_result(info, download=True)
        downloads = info.get("requested_downloads") or []
        path = downloads[0]["filepath"] if downloads else ydl.prepare_filename(info)
    return info.get("title") or "Audio", path


async def _from_ytdlp(target: str, who: str, cfg: Config, source: str, youtube: bool = False) -> Track:
    loop = asyncio.get_running_loop()
    try:
        title, path = await loop.run_in_executor(None, _ytdlp_blocking, target, cfg, youtube)
    except AudioError:
        raise
    except Exception as exc:  # yt-dlp can raise many kinds of errors
        log.warning("yt-dlp fail (%s): %s", source, str(exc)[:300])
        raise AudioError(f"Could not download from {source}.")
    if not os.path.exists(path):
        raise AudioError("The download did not complete.")
    return await _finalize(path, title, who, source, cfg)


# ------------------------------------------------------------ public API

def _domain_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed)


async def resolve_query(query: str, who: str, cfg: Config) -> Track:
    """Text after /play (link or name) -> downloaded Track."""
    track = await _resolve_query(query, who, cfg)
    track.query = query.strip()
    return track


async def _resolve_query(query: str, who: str, cfg: Config) -> Track:
    query = query.strip()
    if query.lower().startswith(("http://", "https://")):
        parsed = urlparse(query)
        host = (parsed.hostname or "").lower()
        if parsed.path.lower().endswith(AUDIO_EXTENSIONS):
            return await _from_direct_url(query, None, who, cfg, "direct link")
        if cfg.enable_ytdlp and _domain_allowed(host, cfg.allowed_domains):
            is_yt = "youtube" in host or host == "youtu.be"
            return await _from_ytdlp(query, who, cfg, host, youtube=is_yt)
        raise AudioError(
            "This link is not allowed. Send a direct audio link (.mp3 etc.), "
            "or ask the admin to extend ALLOWED_DOMAINS in .env."
        )

    # Search by name: try the sources one by one (fallback chain)
    errors: list[str] = []
    if cfg.enable_yt_search:
        steps = (
            ("YouTube", f"ytsearch1:{query}", True),
            ("SoundCloud", f"scsearch1:{query}", False),
        )
        for name, target, is_yt in steps:
            try:
                return await _from_ytdlp(target, who, cfg, name, youtube=is_yt)
            except AudioError as exc:
                log.warning("Source failed: %s -> %s", name, exc)
                errors.append(str(exc))
    if cfg.enable_archive_search or not cfg.enable_yt_search:
        try:
            title, url = await search_archive(query, cfg.max_file_mb * 1024 * 1024)
            return await _from_direct_url(url, title, who, cfg, "archive.org")
        except AudioError as exc:
            log.warning("Source failed: archive.org -> %s", exc)
            errors.append(str(exc))
    raise AudioError(
        "Could not find or download this song right now. Try again in a moment, "
        "send a YouTube link, or reply to an audio file with /play."
    )


async def from_telegram(bot, replied, who: str, cfg: Config) -> Track:
    """Downloads the replied-to Telegram audio/voice/document."""
    media = replied.audio or replied.voice or replied.document
    if media is None:
        raise AudioError("Reply to an audio file with /play.")
    if replied.document and not (replied.document.mime_type or "").startswith("audio/"):
        raise AudioError("This document is not an audio file.")
    size = getattr(media, "file_size", 0) or 0
    if size > cfg.max_file_mb * 1024 * 1024:
        raise AudioError(f"File is too large (max {cfg.max_file_mb} MB).")
    original_name = getattr(media, "file_name", None) or ""
    ext = os.path.splitext(original_name)[1] or (".ogg" if replied.voice else ".mp3")
    title = getattr(media, "title", None) or original_name or "Telegram audio"
    dest = os.path.abspath(_new_path(cfg, ext))
    try:
        saved = await bot.download_media(replied, file_name=dest)
    except Exception as exc:
        log.warning("Telegram download fail: %s", exc)
        remove_file(dest)
        raise AudioError("Could not download the file from Telegram.")
    if not saved:
        raise AudioError("Could not download the file from Telegram.")
    return await _finalize(str(saved), title, who, "telegram file", cfg)


# ------------------------------------------------------- playlist metadata

def _ytdlp_meta_blocking(target: str, cfg: Config, youtube: bool) -> tuple[str, str]:
    """Title + page URL without downloading anything."""
    import yt_dlp

    target = _pick_search_result(target, cfg, youtube)
    opts = _ytdlp_opts(cfg, youtube)
    opts["skip_download"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
        if info and info.get("entries"):
            entries = [e for e in info["entries"] if e]
            info = entries[0] if entries else None
        if not info:
            raise AudioError("Nothing found.")
        return info.get("title") or target, info.get("webpage_url") or info.get("url") or target


async def lookup_meta(query: str, cfg: Config) -> tuple[str, str]:
    """For /addtoplaylist: returns (title, query_to_save) without downloading the audio.

    A search text is turned into the exact video URL when possible, so the playlist
    always plays the same song. If the lookup fails the raw text is saved instead.
    """
    query = query.strip()
    if query.lower().startswith(("http://", "https://")):
        parsed = urlparse(query)
        host = (parsed.hostname or "").lower()
        if parsed.path.lower().endswith(AUDIO_EXTENSIONS):
            return os.path.basename(parsed.path) or query, query
        if not (cfg.enable_ytdlp and _domain_allowed(host, cfg.allowed_domains)):
            raise AudioError(
                "This link is not allowed. Send a direct audio link (.mp3 etc.) or a YouTube link."
            )
        target, is_yt, keep_url = query, ("youtube" in host or host == "youtu.be"), True
    elif cfg.enable_yt_search:
        target, is_yt, keep_url = f"ytsearch1:{query}", True, False
    else:
        return query[:120], query

    loop = asyncio.get_running_loop()
    try:
        title, url = await loop.run_in_executor(None, _ytdlp_meta_blocking, target, cfg, is_yt)
    except Exception as exc:
        log.info("Metadata lookup failed (%s): %s", target, str(exc)[:200])
        return query[:120], query
    return title, (query if keep_url else url)
