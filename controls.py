"""/pause /resume /skip /end /volume /help"""
from __future__ import annotations

import html
import logging

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from handlers.common import require_admin
from services.player import PlayerError, now_playing_text

log = logging.getLogger(__name__)

HELP_TEXT = (
    "🎧 <b>˹𝑨𝒏𝒏𝒊𝒆˼ 𝑴𝒖𝒔𝒊𝒄 - Commands</b>\n\n"
    "/play &lt;name | link&gt; - play a song (replying to audio also works)\n"
    "/pause - pause\n"
    "/resume - resume\n"
    "/skip - next song\n"
    "/end - stop and clear the queue\n"
    "/queue - show the queue\n"
    "/volume &lt;1-200&gt; - volume\n"
    "/help - this message\n\n"
    "ℹ️ Start the group's voice chat first."
)


def register(bot, player, cfg) -> None:
    async def pause_cmd(client, message) -> None:
        if not await require_admin(cfg, client, message):
            return
        try:
            await player.pause(message.chat.id)
            await message.reply_text("⏸ Paused.")
        except PlayerError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc))}")

    async def resume_cmd(client, message) -> None:
        if not await require_admin(cfg, client, message):
            return
        try:
            await player.resume(message.chat.id)
            await message.reply_text("▶️ Resumed.")
        except PlayerError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc))}")

    async def skip_cmd(client, message) -> None:
        if not await require_admin(cfg, client, message):
            return
        try:
            nxt = await player.skip(message.chat.id)
        except PlayerError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc))}")
            return
        if nxt:
            await message.reply_text("⏭ Skipped.\n\n" + now_playing_text(nxt))
        else:
            await message.reply_text("⏭ Skipped. The queue is finished, left the voice chat.")

    async def end_cmd(client, message) -> None:
        if not await require_admin(cfg, client, message):
            return
        if await player.stop(message.chat.id):
            await message.reply_text("⏹ Stopped and cleared the queue.")
        else:
            await message.reply_text("❌ Nothing is playing right now.")

    async def volume_cmd(client, message) -> None:
        chat_id = message.chat.id
        if len(message.command) < 2:
            await message.reply_text(
                f"🔊 Current volume: <b>{player.get_volume(chat_id)}</b>\n"
                "To change it: <code>/volume 80</code> (1 to 200)"
            )
            return
        if not await require_admin(cfg, client, message):
            return
        try:
            value = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Please enter a number, e.g. <code>/volume 80</code>")
            return
        try:
            await player.set_volume(chat_id, value)
            await message.reply_text(f"🔊 Volume set to {value}.")
        except PlayerError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc))}")

    grp = filters.group
    bot.add_handler(MessageHandler(pause_cmd, filters.command("pause") & grp))
    bot.add_handler(MessageHandler(resume_cmd, filters.command("resume") & grp))
    bot.add_handler(MessageHandler(skip_cmd, filters.command("skip") & grp))
    bot.add_handler(MessageHandler(end_cmd, filters.command(["end", "stop"]) & grp))
    bot.add_handler(MessageHandler(volume_cmd, filters.command("volume") & grp))
