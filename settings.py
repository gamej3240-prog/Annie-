"""/settings - chat owner ke liye: play mode, admin mode, command auto-delete."""
from __future__ import annotations

import logging

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)

AUTO_DELETE_CMDS = ["play", "pause", "resume", "skip", "end", "stop", "queue", "volume", "help", "settings"]


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


def _panel(cs: dict) -> tuple[str, InlineKeyboardMarkup]:
    play = "Everyone" if cs["play_mode"] == "everyone" else "Admins only"
    admin = "ON" if cs["admin_mode"] else "OFF"
    auto = "ON" if cs["auto_delete"] else "OFF"
    text = (
        "⚙️ <b>Chat Settings</b>\n\n"
        f"<b>Play mode:</b> {play}\n<i>Kaun /play kar sakta hai.</i>\n\n"
        f"<b>Admin mode:</b> {admin}\n<i>ON = pause/skip/end/volume sirf admins.</i>\n\n"
        f"<b>Command auto-delete:</b> {auto}\n<i>ON = commands chalne ke baad delete ho jaate hain "
        "(bot ko 'Delete messages' right chahiye).</i>"
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
            await message.reply_text("🚫 /settings sirf chat owner ke liye hai.")
            return
        text, kb = _panel(chat_settings.get(message.chat.id))
        await message.reply_text(text, reply_markup=kb)

    async def settings_cb(client, query) -> None:
        chat_id = query.message.chat.id
        if not await _is_chat_owner(cfg, client, chat_id, query.from_user):
            await query.answer("Sirf chat owner badal sakta hai.", show_alert=True)
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
        text, kb = _panel(chat_settings.get(chat_id))
        try:
            await query.message.edit_text(text, reply_markup=kb)
        except Exception as exc:
            log.debug("settings edit: %s", exc)
        await query.answer("Updated ✅")

    async def auto_delete(client, message) -> None:
        """Group 1 me chalta hai, yaani asli command handler ke baad."""
        if not chat_settings.get(message.chat.id)["auto_delete"]:
            return
        try:
            await message.delete()
        except Exception as exc:
            log.debug("auto-delete: %s", exc)

    bot.add_handler(MessageHandler(settings_cmd, filters.command("settings") & filters.group))
    bot.add_handler(CallbackQueryHandler(settings_cb, filters.regex("^st_(play|admin|del|close)$")))
    bot.add_handler(MessageHandler(auto_delete, filters.command(AUTO_DELETE_CMDS) & filters.group), group=1)
