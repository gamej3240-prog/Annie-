"""/start (welcome + buttons), /setstart, /delstart.

The start picture is saved as a Telegram file_id in data/start.json,
so it stays after a restart.
"""
from __future__ import annotations

import html
import json
import logging
import os

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

log = logging.getLogger(__name__)
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

from texts import (  # noqa: E402
    BOT_NAME, JINWOO_URL, UPDATES_URL, category_rows, category_text, help_menu_rows,
    help_menu_text, start_rows, start_text,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
START_FILE = os.path.join(DATA_DIR, "start.json")


def _markup(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(label, url=val) if kind == "url" else InlineKeyboardButton(label, callback_data=val)
                for label, kind, val in row
            ]
            for row in rows
        ]
    )


def start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return _markup(start_rows(bot_username))


def help_menu_keyboard() -> InlineKeyboardMarkup:
    return _markup(help_menu_rows())


def category_keyboard() -> InlineKeyboardMarkup:
    return _markup(category_rows())


def _load() -> dict | None:
    try:
        with open(START_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("file_id") else None
    except (OSError, ValueError):
        return None


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = START_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, START_FILE)


def _delete() -> bool:
    try:
        os.remove(START_FILE)
        return True
    except OSError:
        return False


def _media_of(message) -> dict | None:
    if message.photo:
        return {"type": "photo", "file_id": message.photo.file_id}
    if message.animation:
        return {"type": "animation", "file_id": message.animation.file_id}
    if message.video:
        return {"type": "video", "file_id": message.video.file_id}
    return None


DM_TEXT = "💓 Please start me in DM to check features."


async def _ask_dm(client, message) -> bool:
    """In groups: tells the user to open the bot in DM. True = it was a group (already handled)."""
    if message.chat.type == ChatType.PRIVATE:
        return False
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Start in DM", url=f"https://t.me/{client.me.username}?start=help")]]
    )
    await message.reply_text(DM_TEXT, reply_markup=kb)
    return True


def register(bot, player, cfg) -> None:
    def is_owner(message) -> bool:
        return bool(message.from_user and message.from_user.id in cfg.owner_ids)

    async def start_cmd(client, message) -> None:
        if await _ask_dm(client, message):
            return
        name = message.from_user.first_name if message.from_user and message.from_user.first_name else "there"
        text = start_text(name)
        kb = start_keyboard(client.me.username)
        media = _load()
        if media:
            sender = {
                "photo": message.reply_photo,
                "animation": message.reply_animation,
                "video": message.reply_video,
            }[media["type"]]
            try:
                await sender(media["file_id"], caption=text, reply_markup=kb)
                return
            except Exception as exc:  # if the file_id is broken, fall back to text
                log.warning("Error while sending the start media: %s", exc)
        await message.reply_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)

    async def setstart_cmd(client, message) -> None:
        if not is_owner(message):
            await message.reply_text("🚫 This command is for the bot owner only.")
            return
        replied = message.reply_to_message
        media = _media_of(replied) if replied else None
        if not media:
            await message.reply_text("❌ Reply to a photo (or video/GIF) with <code>/setstart</code>.")
            return
        _save(media)
        await message.reply_text("✅ Start picture has been set.")

    async def delstart_cmd(client, message) -> None:
        if not is_owner(message):
            await message.reply_text("🚫 This command is for the bot owner only.")
            return
        if _delete():
            await message.reply_text("🗑 Start picture removed.")
        else:
            await message.reply_text("ℹ️ No start picture is set right now.")

    async def _edit(query, text: str, kb) -> None:
        msg = query.message
        if msg.photo or msg.video or msg.animation:
            await msg.edit_caption(text, reply_markup=kb)
        else:
            await msg.edit_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)

    async def help_cmd(client, message) -> None:
        if await _ask_dm(client, message):
            return
        name = message.from_user.first_name if message.from_user and message.from_user.first_name else "there"
        await message.reply_text(help_menu_text(name), reply_markup=help_menu_keyboard(), link_preview_options=NO_PREVIEW)

    async def help_open(client, query) -> None:
        try:
            await _edit(query, help_menu_text(query.from_user.first_name or "there"), help_menu_keyboard())
        except Exception as exc:
            log.debug("help edit: %s", exc)
        await query.answer()

    async def help_category(client, query) -> None:
        key = query.data.split("_", 1)[1]
        try:
            await _edit(query, category_text(key), category_keyboard())
        except Exception as exc:
            log.debug("category edit: %s", exc)
        await query.answer()

    async def help_back(client, query) -> None:
        try:
            await _edit(query, start_text(query.from_user.first_name or "there"), start_keyboard(client.me.username))
        except Exception as exc:
            log.debug("back edit: %s", exc)
        await query.answer()

    async def help_close(client, query) -> None:
        try:
            await query.message.delete()
        except Exception as exc:
            log.debug("close: %s", exc)
            await query.answer("Could not close.")
            return
        await query.answer()

    bot.add_handler(MessageHandler(start_cmd, filters.command("start")))
    bot.add_handler(MessageHandler(help_cmd, filters.command("help")))
    bot.add_handler(MessageHandler(setstart_cmd, filters.command("setstart")))
    bot.add_handler(MessageHandler(delstart_cmd, filters.command("delstart")))
    bot.add_handler(CallbackQueryHandler(help_open, filters.regex("^help_open$")))
    bot.add_handler(CallbackQueryHandler(help_category, filters.regex("^hc_(users|admins|owner|playlist|devs|autoplay)$")))
    bot.add_handler(CallbackQueryHandler(help_back, filters.regex("^help_back$")))
    bot.add_handler(CallbackQueryHandler(help_close, filters.regex("^help_close$")))
