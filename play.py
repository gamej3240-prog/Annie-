"""/play command: naam, link ya audio file se gaana queue me daalta hai."""
from __future__ import annotations

import html
import logging

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from handlers.common import require_play, user_label
from services import audio
from services.audio import AudioError
from services.player import PlayerError, now_playing_text

log = logging.getLogger(__name__)

USAGE = (
    "🎵 <b>Kaise use karein</b>\n"
    "• <code>/play gaane ka naam</code>\n"
    "• <code>/play https://.../song.mp3</code>\n"
    "• Kisi audio file par reply karke <code>/play</code>"
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

        status = await message.reply_text("🔎 Dhoondh raha hoon...")
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
            log.exception("/play me unexpected error")
            await status.edit_text("❌ Kuch gadbad ho gayi. Thodi der baad try karo.")
            return

        if position == 0:
            await status.edit_text(now_playing_text(track))
        else:
            await status.edit_text(
                f"📥 <b>Queue me #{position}</b>\n"
                f"🎵 {html.escape(track.title)}\n"
                f"⏱ {track.duration_text}"
            )

    bot.add_handler(MessageHandler(play_cmd, filters.command("play") & filters.group))
