"""/play command: adds a song to the queue from a name, link or audio file."""
from __future__ import annotations

import html
import logging

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from handlers.common import require_play, user_label
from services import audio
from services.audio import AudioError
from services.player import PlayerError, now_playing_text, player_keyboard, queue_keyboard

log = logging.getLogger(__name__)

USAGE = (
    "🎵 <b>How to use</b>\n"
    "• <code>/play song name</code>\n"
    "• <code>/play https://.../song.mp3</code>\n"
    "• Reply to an audio file with <code>/play</code>"
)


def register(bot, player, cfg) -> None:
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
            await message.reply_text(USAGE)
            return

        status = await message.reply_text("🔎 Searching...")
        try:
            await player.ensure_assistant(chat_id)
            if query:
                track = await audio.resolve_query(query, who, cfg)
            else:
                track = await audio.from_telegram(client, replied, who, cfg)
            position = await player.add(chat_id, track)
        except (AudioError, PlayerError) as exc:
            await status.edit_text(f"❌ {html.escape(str(exc))}")
            return
        except Exception:
            log.exception("Unexpected error in /play")
            await status.edit_text("❌ Something went wrong. Please try again later.")
            return

        if position == 0:
            await status.edit_text(now_playing_text(track), reply_markup=player_keyboard())
        else:
            await status.edit_text(
                f"📥 <b>Added to queue at #{position}</b>\n"
                f"🎵 {html.escape(track.title)}\n"
                f"⏱ {track.duration_text}",
                reply_markup=queue_keyboard(track),
            )

    bot.add_handler(MessageHandler(play_cmd, filters.command("play") & filters.group))
