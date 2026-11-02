"""Developer commands (bot owners only): /stats /av /clean /clearass /leaveall /logger"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import platform
import shutil
import time
from contextlib import suppress

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from services import audio

log = logging.getLogger(__name__)
START_TIME = time.time()


def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s"


def _mem_text() -> str:
    try:
        info = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total, avail = info["MemTotal"] // 1024, info["MemAvailable"] // 1024
        return f"{total - avail} MB / {total} MB"
    except Exception:
        return "N/A"


def _size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def _downloads_text(path: str) -> str:
    count = total = 0
    try:
        for name in os.listdir(path):
            fp = os.path.join(path, name)
            if os.path.isfile(fp):
                count += 1
                total += os.path.getsize(fp)
    except OSError:
        return "N/A"
    return f"{_size(total)} ({count} files)"


def register(bot, player, cfg, chat_settings, playlists=None) -> None:
    owner = filters.create(
        lambda _, __, m: bool(m.from_user and m.from_user.id in cfg.owner_ids), name="OwnerFilter"
    )

    async def stats_cmd(client, message) -> None:
        active = player.active()
        queued = sum(len(st.queue) for st in active.values())
        disk = shutil.disk_usage(cfg.download_dir if os.path.isdir(cfg.download_dir) else "/")
        try:
            load = " ".join(f"{x:.2f}" for x in os.getloadavg())
        except OSError:
            load = "N/A"
        text = (
            "📊 <b>Bot Stats</b>\n\n"
            f"<b>Uptime:</b> {_fmt_uptime(time.time() - START_TIME)}\n"
            f"<b>Active voice chats:</b> {len(active)}\n"
            f"<b>Songs in queues:</b> {queued}\n\n"
            "<b>Hosting</b>\n"
            f"Python: {platform.python_version()}\n"
            f"OS: {html.escape(platform.system())} {html.escape(platform.machine())}\n"
            f"CPU load (1/5/15m): {load}\n"
            f"RAM used: {_mem_text()}\n"
            f"Disk free: {_size(disk.free)} / {_size(disk.total)}\n"
            f"Downloads folder: {_downloads_text(cfg.download_dir)}\n\n"
            "<b>Database</b>\n"
            f"Chats with saved settings: {chat_settings.count()}\n"
            f"Users with playlists: {playlists.count_users() if playlists else 0}\n"
            "Storage: local JSON files (no external database)"
        )
        await message.reply_text(text)

    async def av_cmd(client, message) -> None:
        active = player.active()
        if not active:
            await message.reply_text("📭 There are no active voice chats right now.")
            return
        lines = [f"🎙 <b>Active voice chats ({len(active)})</b>\n"]
        for i, (chat_id, st) in enumerate(active.items(), start=1):
            try:
                chat = await client.get_chat(chat_id)
                name = html.escape(chat.title or str(chat_id))
            except Exception:
                name = "Unknown chat"
            state = "⏸" if st.paused else "▶️"
            lines.append(
                f"{i}. {name} (<code>{chat_id}</code>)\n"
                f"   {state} {html.escape(st.current.title)} | queue: {len(st.queue)}"
            )
        await message.reply_text("\n".join(lines))

    async def leaveall_cmd(client, message) -> None:
        count = await player.stop_all()
        await message.reply_text(f"✅ Assistant disconnected from {count} active chat(s). Queues cleared.")

    async def clearass_cmd(client, message) -> None:
        count = await player.stop_all()
        removed = 0
        for name in os.listdir(cfg.download_dir):
            path = os.path.join(cfg.download_dir, name)
            if os.path.isfile(path):
                with suppress(OSError):
                    os.remove(path)
                    removed += 1
        await message.reply_text(
            f"🧹 Disconnected {count} active chat(s), cleared all states, deleted {removed} temp file(s)."
        )

    async def clean_cmd(client, message) -> None:
        """Deletes old downloaded files that are not playing and not in a queue."""
        loop = asyncio.get_running_loop()
        count, freed = await loop.run_in_executor(
            None, audio.cleanup_downloads, cfg, player.in_use_paths(), 120
        )
        await message.reply_text(
            f"🧹 Deleted {count} old file(s), freed {_size(freed)}.\n"
            "Songs that are playing or waiting in a queue were not touched."
        )

    async def logger_cmd(client, message) -> None:
        log_path = os.path.join(cfg.log_dir, "musicbot.log")
        try:
            size = _size(os.path.getsize(log_path))
        except OSError:
            size = "N/A"
        await message.reply_text(
            "🗒 <b>Logging configuration</b>\n\n"
            f"<b>Level:</b> {html.escape(cfg.log_level)}\n"
            f"<b>File:</b> <code>{html.escape(log_path)}</code>\n"
            f"<b>Current size:</b> {size}\n"
            "<b>Rotation:</b> 1 MB per file, 2 backups\n"
            f"<b>Watchdog:</b> every {cfg.watchdog_interval}s, restart after {cfg.watchdog_max_fails} fails\n\n"
            "To change the level, set <code>LOG_LEVEL</code> (DEBUG/INFO/WARNING) in .env and restart."
        )

    bot.add_handler(MessageHandler(stats_cmd, filters.command("stats") & owner))
    bot.add_handler(MessageHandler(av_cmd, filters.command("av") & owner))
    bot.add_handler(MessageHandler(leaveall_cmd, filters.command("leaveall") & owner))
    bot.add_handler(MessageHandler(clearass_cmd, filters.command("clearass") & owner))
    bot.add_handler(MessageHandler(clean_cmd, filters.command("clean") & owner))
    bot.add_handler(MessageHandler(logger_cmd, filters.command("logger") & owner))
