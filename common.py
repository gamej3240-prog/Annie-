"""Common helper functions for the handlers."""
from __future__ import annotations

from pyrogram.enums import ChatMemberStatus


def user_label(message) -> str:
    user = message.from_user
    return user.first_name if user and user.first_name else "Anonymous"


async def is_admin(cfg, client, message) -> bool:
    user = message.from_user
    if user is None:
        # Anonymous admin: sends messages as the group itself
        return bool(message.sender_chat and message.sender_chat.id == message.chat.id)
    if user.id in cfg.owner_ids:
        return True
    from handlers.auth import is_authorized  # late import (auth.py is a sibling module)

    if is_authorized(message.chat.id, user.id):
        return True
    try:
        member = await client.get_chat_member(message.chat.id, user.id)
    except Exception:
        return False
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def require_play(cfg, client, message) -> bool:
    """/play: follows the chat's 'play mode' setting."""
    from services.chat_settings import settings_store

    if settings_store is None or settings_store.get(message.chat.id)["play_mode"] == "everyone":
        return True
    if await is_admin(cfg, client, message):
        return True
    await message.reply_text("🚫 Only admins can use /play in this chat.")
    return False


async def require_admin(cfg, client, message) -> bool:
    """True = go ahead. False = the user was told that admin rights are needed."""
    admin_mode = cfg.admin_only
    if message.chat is not None:
        from services.chat_settings import settings_store  # late import: the settings object is created in main.py

        if settings_store is not None:
            admin_mode = settings_store.get(message.chat.id)["admin_mode"]
    if not admin_mode:
        return True
    if await is_admin(cfg, client, message):
        return True
    await message.reply_text("🚫 This command is for group admins only.")
    return False


async def cb_require_admin(cfg, client, query) -> bool:
    """Same rule as require_admin, but for button presses (answers with a popup)."""
    from services.chat_settings import settings_store

    chat_id = query.message.chat.id
    admin_mode = cfg.admin_only
    if settings_store is not None:
        admin_mode = settings_store.get(chat_id)["admin_mode"]
    if not admin_mode:
        return True
    user = query.from_user
    if user.id in cfg.owner_ids:
        return True
    from handlers.auth import is_authorized

    if is_authorized(chat_id, user.id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user.id)
        if member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            return True
    except Exception:
        pass
    await query.answer("🚫 Only group admins can use these buttons.", show_alert=True)
    return False
