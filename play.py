"""/play command: adds a song to the queue from a name, link or audio file."""
from __future__ import annotations

import asyncio
import html
import logging
import hashlib
import json
import os
import re

from pyrogram import filters
from pyrogram.handlers import InlineQueryHandler, MessageHandler
from pyrogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
)

from handlers.common import require_play, user_label
from services import audio
from services.audio import AudioError
from services.player import PlayerError, now_playing_text, queue_keyboard

log = logging.getLogger(__name__)

# Private channel where finished songs are saved (the bot must be admin there)
CACHE_CHAT = int(os.getenv("CACHE_CHANNEL_ID", "-1004361677300") or 0)
# Users (besides the owners) who may use /precache. Added with /allowprecache (saved in
# data/precache_users.json), or fixed in .env: PRECACHE_USERS=111,222
_PU_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "precache_users.json"
)
_ENV_USERS = {
    int(x) for x in os.getenv("PRECACHE_USERS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()
}


def _pu_load() -> set[int]:
    try:
        with open(_PU_FILE, encoding="utf-8") as f:
            return {int(x) for x in json.load(f)}
    except Exception:
        return set()


def _pu_save(users: set[int]) -> None:
    try:
        os.makedirs(os.path.dirname(_PU_FILE), exist_ok=True)
        tmp = _PU_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(users), f)
        os.replace(tmp, _PU_FILE)
    except OSError as exc:
        log.warning("could not save precache users: %s", exc)


PRECACHE_USERS: set[int] = _ENV_USERS | _pu_load()


async def _cache_upload(client, query: str, track) -> None:
    """Saves the song in the cache channel so the next /play of it is instant."""
    if not CACHE_CHAT:
        return
    try:
        msg = await client.send_audio(
            CACHE_CHAT, track.path, title=track.title, duration=track.duration
        )
        media = msg.audio or msg.document
        audio.cache_put(query, media.file_id, track.title, track.duration, track.vid)
    except Exception as exc:
        log.warning("cache upload fail: %s", exc)


async def _get_track(client, query: str, who: str, cfg):
    """Cache first (by text, then by video id); download only when it is really new."""
    hit = audio.cache_get(query)
    if hit:
        try:
            return await audio.from_cache(client, hit, who, cfg, query)
        except Exception as exc:
            log.warning("cache file not usable, removing it: %s", exc)
            audio.cache_drop(hit)
    for _ in range(2):
        try:
            track = await audio.resolve_query(query, who, cfg, allow_cache_hit=False)
        except audio.CacheHit as ch:
            try:
                track = await audio.from_cache(client, ch.hit, who, cfg, query)
                audio.cache_alias(query, ch.hit)
                return track
            except Exception as exc:
                log.warning("cache file not usable, removing it: %s", exc)
                audio.cache_drop(ch.hit)
                continue
        asyncio.create_task(_cache_upload(client, query, track))
        return track
    raise AudioError("Could not play this song. Please try again.")


USAGE = (
    "🎵 <b>How to use</b>\n"
    "• <code>/play song name</code>\n"
    "• <code>/play https://.../song.mp3</code>\n"
    "• Reply to an audio file with <code>/play</code>"
)


def register(bot, player, cfg) -> None:
    audio.prewarm()

    async def play_cmd(client, message) -> None:
        if not await require_play(cfg, client, message):
            return
        chat_id = message.chat.id
        who = user_label(message)
        replied = message.reply_to_message
        has_file = bool(
            replied
            and (
                replied.audio
                or replied.voice
                or (replied.document and (replied.document.mime_type or "").startswith("audio/"))
            )
        )
        query = " ".join(message.command[1:]).strip()
        if not query and not has_file:
            audio.schedule_delete(await message.reply_text(USAGE))
            return

        # Housekeeping in the background: delete old leftover files (older than 30 min, not in use)
        asyncio.get_running_loop().run_in_executor(
            None, audio.cleanup_downloads, cfg, player.in_use_paths(), 1800
        )

        # Send the "Searching" message at the same time as the search (saves one round trip)
        status_task = asyncio.create_task(message.reply_text("🔎 Searching..."))
        try:
            # The assistant-in-group check runs at the same time as the search/download
            assistant_task = asyncio.create_task(player.ensure_assistant(chat_id))
            try:
                if query:
                    track = await _get_track(client, query, who, cfg)
                else:
                    track = await audio.from_telegram(client, replied, who, cfg)
            except BaseException:
                assistant_task.cancel()
                raise
            try:
                await assistant_task
            except BaseException:
                audio.remove_file(track.path)
                raise
            position = await player.add(chat_id, track)
        except (AudioError, PlayerError) as exc:
            status = await status_task
            await status.edit_text(f"❌ {html.escape(str(exc))}")
            audio.schedule_delete(status, 30)
            return
        except Exception:
            log.exception("Unexpected error in /play")
            status = await status_task
            await status.edit_text("❌ Something went wrong. Please try again later.")
            audio.schedule_delete(status, 30)
            return
        status = await status_task

        if position == 0:
            await status.edit_text(now_playing_text(track), reply_markup=player.keyboard(chat_id))
        else:
            await status.edit_text(
                f"📥 <b>Added to queue at #{position}</b>\n"
                f"🎵 {html.escape(track.title)}\n"
                f"⏱ {track.duration_text}",
                reply_markup=queue_keyboard(track),
            )
        audio.schedule_delete(status)

    # ------------------------------------------------------------ /precache (owner only)
    state = {"running": False}

    async def _precache_job(client, status, names: list[str]) -> None:
        done = skipped = 0
        failed: list[str] = []
        total = len(names)

        async def _edit(text: str) -> None:
            try:
                await status.edit_text(text)
            except Exception:
                pass

        try:
            for i, name in enumerate(names, 1):
                if audio.cache_get(name):
                    skipped += 1
                    continue
                await _edit(f"⏳ <b>Precache {i}/{total}</b>\n🎵 {html.escape(name[:60])}")
                track = None
                try:
                    track = await audio.resolve_query(name, "precache", cfg, allow_cache_hit=False)
                    msg = await client.send_audio(
                        CACHE_CHAT, track.path, title=track.title, duration=track.duration
                    )
                    media = msg.audio or msg.document
                    audio.cache_put(name, media.file_id, track.title, track.duration, track.vid)
                    done += 1
                except audio.CacheHit as ch:
                    audio.cache_alias(name, ch.hit)  # same video was cached under another text
                    skipped += 1
                except Exception as exc:
                    log.warning("precache fail (%s): %s", name, exc)
                    failed.append(name)
                finally:
                    if track is not None:
                        audio.remove_file(track.path)
                await asyncio.sleep(2)  # let the weak phone breathe
            text = (
                f"✅ <b>Precache finished</b>\n"
                f"📥 New: {done}\n⏭ Already cached: {skipped}\n❌ Failed: {len(failed)}\n"
                f"💾 Total songs in cache: {audio.cache_count()}"
            )
            if failed:
                text += "\n\n" + "\n".join(f"• {html.escape(n[:60])}" for n in failed[:15])
            await _edit(text)
        finally:
            state["running"] = False

    async def precache_cmd(client, message) -> None:
        user = message.from_user
        if user is None or (user.id not in cfg.owner_ids and user.id not in PRECACHE_USERS):
            await message.reply_text("🚫 You are not allowed to use /precache.")
            return
        if not CACHE_CHAT:
            await message.reply_text("❌ CACHE_CHANNEL_ID is not set.")
            return
        if state["running"]:
            await message.reply_text("⏳ A precache job is already running. Please wait.")
            return
        parts = (message.text or "").split(None, 1)
        text = parts[1] if len(parts) > 1 else ""
        replied = message.reply_to_message
        if not text and replied and replied.text:
            text = replied.text
        names = [n.strip() for n in re.split(r"[\n|]+", text) if n.strip()][:100]
        if not names:
            await message.reply_text(
                "ℹ️ <b>How to use</b>\n"
                "<code>/precache song one | song two | song three</code>\n"
                "or reply to a message that has one song name per line.\n"
                "Max 100 songs at a time."
            )
            return
        state["running"] = True
        status = await message.reply_text(f"⏳ Precache started: {len(names)} songs...")
        asyncio.create_task(_precache_job(client, status, names))

    # ------------------------------------------------- inline mode: @bot song name
    async def inline_cmd(client, inline_query) -> None:
        hits = audio.cache_search(inline_query.query or "", 20)
        if hits:
            results = [
                InlineQueryResultCachedAudio(
                    audio_file_id=h["file_id"],
                    id=hashlib.md5(h["file_id"].encode()).hexdigest(),
                )
                for h in hits
            ]
        else:
            results = [
                InlineQueryResultArticle(
                    title="No saved song found",
                    description="Play it once with /play in a group, then it shows up here.",
                    input_message_content=InputTextMessageContent("🎵 Use /play song name in a group chat."),
                    id="nosong",
                )
            ]
        try:
            await inline_query.answer(results, cache_time=5, is_personal=False)
        except Exception as exc:
            log.warning("inline answer fail: %s", exc)

    # --------------------------- who may use /precache (owner only): /allowprecache etc.
    async def _pu_target(client, message):
        replied = message.reply_to_message
        if replied and replied.from_user:
            return replied.from_user
        if len(message.command) > 1:
            arg = message.command[1].strip()
            try:
                return await client.get_users(int(arg) if arg.lstrip("-").isdigit() else arg)
            except Exception:
                return None
        return None

    def _is_owner(message) -> bool:
        return bool(message.from_user and message.from_user.id in cfg.owner_ids)

    async def allowprecache_cmd(client, message) -> None:
        if not _is_owner(message):
            await message.reply_text("🚫 Only the bot owner can use this command.")
            return
        user = await _pu_target(client, message)
        if user is None:
            await message.reply_text(
                "ℹ️ Reply to a user with <code>/allowprecache</code>, or use "
                "<code>/allowprecache @username</code> / <code>/allowprecache user_id</code>."
            )
            return
        if user.is_bot:
            await message.reply_text("❌ Bots cannot be allowed.")
            return
        name = html.escape(user.first_name or str(user.id))
        if user.id in PRECACHE_USERS or user.id in cfg.owner_ids:
            await message.reply_text(f"ℹ️ {name} can already use /precache.")
            return
        PRECACHE_USERS.add(user.id)
        _pu_save(PRECACHE_USERS - _ENV_USERS)
        await message.reply_text(f"✅ {name} can now use /precache.")

    async def denyprecache_cmd(client, message) -> None:
        if not _is_owner(message):
            await message.reply_text("🚫 Only the bot owner can use this command.")
            return
        user = await _pu_target(client, message)
        if user is None:
            await message.reply_text(
                "ℹ️ Reply to a user with <code>/denyprecache</code>, or use "
                "<code>/denyprecache @username</code> / <code>/denyprecache user_id</code>."
            )
            return
        name = html.escape(user.first_name or str(user.id))
        if user.id in _ENV_USERS:
            await message.reply_text(f"❌ {name} is set in .env (PRECACHE_USERS). Remove the ID from .env.")
            return
        if user.id not in PRECACHE_USERS:
            await message.reply_text(f"ℹ️ {name} was not allowed.")
            return
        PRECACHE_USERS.discard(user.id)
        _pu_save(PRECACHE_USERS - _ENV_USERS)
        await message.reply_text(f"🗑 {name} can no longer use /precache.")

    async def precacheusers_cmd(client, message) -> None:
        if not _is_owner(message):
            await message.reply_text("🚫 Only the bot owner can use this command.")
            return
        if not PRECACHE_USERS:
            await message.reply_text("ℹ️ No extra users are allowed (only owners).")
            return
        lines = []
        for i, uid in enumerate(sorted(PRECACHE_USERS), 1):
            try:
                u = await client.get_users(uid)
                label = html.escape(u.first_name or str(uid))
            except Exception:
                label = "Unknown user"
            lines.append(f"{i}. {label} (<code>{uid}</code>)")
        await message.reply_text("👥 <b>Allowed for /precache</b>\n" + "\n".join(lines))

    bot.add_handler(MessageHandler(allowprecache_cmd, filters.command("allowprecache")))
    bot.add_handler(MessageHandler(denyprecache_cmd, filters.command("denyprecache")))
    bot.add_handler(MessageHandler(precacheusers_cmd, filters.command("precacheusers")))
    bot.add_handler(InlineQueryHandler(inline_cmd))
    bot.add_handler(MessageHandler(play_cmd, filters.command("play") & filters.group))
    bot.add_handler(MessageHandler(precache_cmd, filters.command("precache")))
