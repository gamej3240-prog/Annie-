"""/settings - for the chat owner: play mode, admin mode, command auto-delete."""
from __future__ import annotations

import asyncio
import logging

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)

AUTO_DELETE_CMDS = [
    "play", "pause", "resume", "skip", "end", "stop", "queue", "volume", "help", "settings",
    "createplaylist", "deleteplaylist", "addtoplaylist", "removefromplaylist", "playlistinfo",
    "myplaylists", "playplaylist",
    "np", "nowplaying", "loop", "shuffle", "remove", "auth", "unauth", "authusers",
    "stats", "av", "clean", "off", "shutdown", "clearass", "leaveall", "logger",
    "broadcast", "fbroadcast",
]


# --- Instant delete support -------------------------------------------------------------
# The command message is deleted the moment it arrives. A normal reply would try to quote it
# and fail, so for those messages the reply helpers send a plain (not quoted) message instead.
_GONE: set[tuple[int, int]] = set()
_PATCHED = False


def _patch_replies() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    senders = {
        "reply_text": "send_message",
        "reply_photo": "send_photo",
        "reply_animation": "send_animation",
        "reply_video": "send_video",
        "reply_audio": "send_audio",
        "reply_document": "send_document",
    }

    def make(name: str, send_name: str):
        original = getattr(Message, name)

        async def wrapper(self, first, *args, **kwargs):
            if (self.chat.id, self.id) in _GONE:
                for key in ("quote", "reply_to_message_id", "reply_parameters"):
                    kwargs.pop(key, None)
                thread = getattr(self, "message_thread_id", None)
                if thread and "message_thread_id" not in kwargs:
                    kwargs["message_thread_id"] = thread
                return await getattr(self._client, send_name)(self.chat.id, first, *args, **kwargs)
            return await original(self, first, *args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    for name, send_name in senders.items():
        if hasattr(Message, name):
            setattr(Message, name, make(name, send_name))


async def _is_chat_owner(cfg, client, chat_id: int, user) -> bool:
    if user is None:
        return False
    if user.id in cfg.owner_ids:
        return True
    try:
        member = await client.get_chat_member(chat_id, user.id)
    except Exception:
        return False
    return member.status == ChatMemberStatus.OWNER


def _panel(cs: dict, forced_delete: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    play = "Everyone" if cs["play_mode"] == "everyone" else "Admins only"
    admin = "ON" if cs["admin_mode"] else "OFF"
    auto = "ON (always)" if forced_delete else ("ON" if cs["auto_delete"] else "OFF")
    text = (
        "⚙️ <b>Chat Settings</b>\n\n"
        f"<b>Play mode:</b> {play}\n<i>Who can use /play.</i>\n\n"
        f"<b>Admin mode:</b> {admin}\n<i>ON = only admins can pause/skip/end/change volume.</i>\n\n"
        f"<b>Command auto-delete:</b> {auto}\n<i>ON = commands are deleted after they run "
        "(the bot needs the 'Delete messages' right).</i>"
    )
    b = InlineKeyboardButton
    kb = InlineKeyboardMarkup(
        [
            [b(f"Play mode: {play}", callback_data="st_play")],
            [b(f"Admin mode: {admin}", callback_data="st_admin")],
            [b(f"Auto-delete: {auto}", callback_data="st_del")],
            [b("Close", callback_data="st_close")],
        ]
    )
    return text, kb


def register(bot, player, cfg, chat_settings) -> None:
    async def settings_cmd(client, message) -> None:
        if not await _is_chat_owner(cfg, client, message.chat.id, message.from_user):
            await message.reply_text("🚫 /settings is for the chat owner only.")
            return
        text, kb = _panel(chat_settings.get(message.chat.id), cfg.delete_commands)
        await message.reply_text(text, reply_markup=kb)

    async def settings_cb(client, query) -> None:
        chat_id = query.message.chat.id
        if not await _is_chat_owner(cfg, client, chat_id, query.from_user):
            await query.answer("Only the chat owner can change this.", show_alert=True)
            return
        action = query.data
        if action == "st_close":
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.answer()
            return
        cs = chat_settings.get(chat_id)
        if action == "st_play":
            chat_settings.set(chat_id, "play_mode", "admins" if cs["play_mode"] == "everyone" else "everyone")
        elif action == "st_admin":
            chat_settings.set(chat_id, "admin_mode", not cs["admin_mode"])
        elif action == "st_del":
            chat_settings.set(chat_id, "auto_delete", not cs["auto_delete"])
        text, kb = _panel(chat_settings.get(chat_id), cfg.delete_commands)
        try:
            await query.message.edit_text(text, reply_markup=kb)
        except Exception as exc:
            log.debug("settings edit: %s", exc)
        await query.answer("Updated ✅")

    pending: set[asyncio.Task] = set()

    async def _delete_now(message) -> None:
        key = (message.chat.id, message.id)
        try:
            await message.delete()
        except Exception as exc:
            log.debug("auto-delete: %s", exc)
        finally:
            # keep the mark a little while: the handlers may still be replying
            asyncio.get_running_loop().call_later(120, _GONE.discard, key)

    async def auto_delete(client, message) -> None:
        """Runs BEFORE the command handler (group -1): the command is deleted instantly."""
        if not (cfg.delete_commands or chat_settings.get(message.chat.id)["auto_delete"]):
            return
        _patch_replies()
        _GONE.add((message.chat.id, message.id))
        task = asyncio.create_task(_delete_now(message))
        pending.add(task)
        task.add_done_callback(pending.discard)

    bot.add_handler(MessageHandler(settings_cmd, filters.command("settings") & filters.group))
    bot.add_handler(CallbackQueryHandler(settings_cb, filters.regex("^st_(play|admin|del|close)$")))
    bot.add_handler(MessageHandler(auto_delete, filters.command(AUTO_DELETE_CMDS) & filters.group), group=-1)
