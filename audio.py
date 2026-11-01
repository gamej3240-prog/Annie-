"""Audio dhoondhna, download karna aur check karna (duration/size).

Support:
  1. Telegram me bheji gayi audio file (reply karke /play)
  2. Direct audio link (.mp3, .ogg ...)
  3. Allowed domains ke links (yt-dlp se)
  4. Naam se search: Internet Archive (free, API key nahi chahiye)
     (YouTube search sirf tab jab aap .env me ENABLE_YT_SEARCH=true karo)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
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
    """Aisa error jiska message seedha user ko dikha sakte hain."""


@dataclass
class Track:
    title: str
    path: str  # phone par downloaded file
    duration: int  # seconds
    requested_by: str
    source: str

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
    """ffprobe se duration nikalta hai. Audio nahi hui to AudioError."""
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
        raise AudioError("ffprobe install nahi hai (ffmpeg install karo).")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise AudioError("File check karne me bahut time laga.")
    try:
        return int(float(out.decode().strip()))
    except ValueError:
        raise AudioError("Ye file valid audio nahi lag rahi.")


async def _finalize(path: str, title: str, who: str, source: str, cfg: Config) -> Track:
    """Download ke baad duration check karke Track banata hai."""
    try:
        duration = await probe_duration(path)
        if duration <= 0:
            raise AudioError("Audio ki length pata nahi chali.")
        if duration > cfg.max_duration:
            raise AudioError(f"Gaana bahut lamba hai (max {cfg.max_duration // 60} min).")
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
                raise AudioError(f"Link se file nahi mili (HTTP {resp.status}).")
            if resp.content_length and resp.content_length > max_bytes:
                raise AudioError(f"File badi hai (max {max_bytes // 1024 // 1024} MB).")
            written = 0
            with open(dest, "wb") as fh:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise AudioError(f"File badi hai (max {max_bytes // 1024 // 1024} MB).")
                    fh.write(chunk)


async def download_file(url: str, dest: str, max_bytes: int, attempts: int = 3) -> None:
    """Network toot jaye to 3 baar tak dobara try karta hai."""
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
                raise AudioError("Network problem: download nahi ho paya. Thodi der baad try karo.")
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
    """Internet Archive me audio search. (title, download_url) lautata hai."""
    clean = re.sub(r"[^\w\s]", " ", query, flags=re.UNICODE).strip()
    if not clean:
        raise AudioError("Search ke liye gaane ka naam likho.")
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
                    raise AudioError("Search service abhi kaam nahi kar rahi.")
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
        raise AudioError("Network problem: search nahi ho paya.")
    raise AudioError(
        "Internet Archive par ye gaana nahi mila. Direct .mp3 link do ya "
        "audio file par reply karke /play likho."
    )


# ------------------------------------------------------------------ yt-dlp

def _ytdlp_blocking(target: str, cfg: Config) -> tuple[str, str]:
    import yt_dlp  # lazy import: RAM tabhi use hoti hai jab zarurat ho

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
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
        if info and info.get("entries"):
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise AudioError("Kuch nahi mila.")
            info = entries[0]
        if not info:
            raise AudioError("Kuch nahi mila.")
        duration = info.get("duration") or 0
        if duration and duration > cfg.max_duration:
            raise AudioError(f"Gaana bahut lamba hai (max {cfg.max_duration // 60} min).")
        info = ydl.process_ie_result(info, download=True)
        downloads = info.get("requested_downloads") or []
        path = downloads[0]["filepath"] if downloads else ydl.prepare_filename(info)
    return info.get("title") or "Audio", path


async def _from_ytdlp(target: str, who: str, cfg: Config, source: str) -> Track:
    loop = asyncio.get_running_loop()
    try:
        title, path = await loop.run_in_executor(None, _ytdlp_blocking, target, cfg)
    except AudioError:
        raise
    except Exception as exc:  # yt-dlp ke kai tarah ke errors
        log.warning("yt-dlp fail: %s", exc)
        raise AudioError("Is link/naam se audio download nahi ho paya.")
    if not os.path.exists(path):
        raise AudioError("Download poora nahi hua.")
    return await _finalize(path, title, who, source, cfg)


# ------------------------------------------------------------ public API

def _domain_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed)


async def resolve_query(query: str, who: str, cfg: Config) -> Track:
    """/play ke baad likha text (link ya naam) -> downloaded Track."""
    query = query.strip()
    if query.lower().startswith(("http://", "https://")):
        parsed = urlparse(query)
        host = (parsed.hostname or "").lower()
        if parsed.path.lower().endswith(AUDIO_EXTENSIONS):
            return await _from_direct_url(query, None, who, cfg, "direct link")
        if cfg.enable_ytdlp and _domain_allowed(host, cfg.allowed_domains):
            return await _from_ytdlp(query, who, cfg, host)
        raise AudioError(
            "Ye link allowed nahi hai. Direct audio link (.mp3 etc.) do, "
            "ya admin .env me ALLOWED_DOMAINS badha de."
        )
    if cfg.enable_yt_search:
        return await _from_ytdlp(f"ytsearch1:{query}", who, cfg, "youtube search")
    title, url = await search_archive(query, cfg.max_file_mb * 1024 * 1024)
    return await _from_direct_url(url, title, who, cfg, "archive.org")


async def from_telegram(bot, replied, who: str, cfg: Config) -> Track:
    """Reply kiye gaye Telegram audio/voice/document ko download karta hai."""
    media = replied.audio or replied.voice or replied.document
    if media is None:
        raise AudioError("Audio file par reply karke /play likho.")
    if replied.document and not (replied.document.mime_type or "").startswith("audio/"):
        raise AudioError("Ye document audio file nahi hai.")
    size = getattr(media, "file_size", 0) or 0
    if size > cfg.max_file_mb * 1024 * 1024:
        raise AudioError(f"File badi hai (max {cfg.max_file_mb} MB).")
    original_name = getattr(media, "file_name", None) or ""
    ext = os.path.splitext(original_name)[1] or (".ogg" if replied.voice else ".mp3")
    title = getattr(media, "title", None) or original_name or "Telegram audio"
    dest = os.path.abspath(_new_path(cfg, ext))
    try:
        saved = await bot.download_media(replied, file_name=dest)
    except Exception as exc:
        log.warning("Telegram download fail: %s", exc)
        remove_file(dest)
        raise AudioError("Telegram se file download nahi ho payi.")
    if not saved:
        raise AudioError("Telegram se file download nahi ho payi.")
    return await _finalize(str(saved), title, who, "telegram file", cfg)
