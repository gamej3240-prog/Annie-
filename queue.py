"""/queue command."""
from __future__ import annotations

import html

from pyrogram import filters
from pyrogram.handlers import MessageHandler

SHOW_LIMIT = 10


def register(bot, player, cfg) -> None:
    async def queue_cmd(client, message) -> None:
        current, upcoming = player.snapshot(message.chat.id)
        if current is None:
            await message.reply_text("📭 The queue is empty. Add a song with /play.")
            return

        lines = [
            "🎶 <b>Now playing</b>",
            f"{html.escape(current.title)} ({current.duration_text})",
        ]
        if upcoming:
            lines.append("\n📋 <b>Up next</b>")
            for i, track in enumerate(upcoming[:SHOW_LIMIT], start=1):
                lines.append(f"{i}. {html.escape(track.title)} ({track.duration_text})")
            if len(upcoming) > SHOW_LIMIT:
                lines.append(f"... and {len(upcoming) - SHOW_LIMIT} more")
        else:
            lines.append("\nNo more songs in the queue.")
        await message.reply_text("\n".join(lines))

    bot.add_handler(MessageHandler(queue_cmd, filters.command("queue") & filters.group))
