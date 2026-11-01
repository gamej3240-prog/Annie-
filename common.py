"""Handlers ke common helper functions."""
from __future__ import annotations

from pyrogram.enums import ChatMemberStatus


def user_label(message) -> str:
    user = message.from_user
    return user.first_name if user and user.first_name else "Anonymous"


async def is_admin(cfg, client, message) -> bool:
    user = message.from_user
    if user is None:
        # Anonymous admin: group ke naam se message bhejta hai
        return bool(message.sender_chat and message.sender_chat.id == message.chat.id)
    if user.id in cfg.owner_ids:
        return True
    try:
        member = await client.get_chat_member(message.chat.id, user.id)
    except Exception:
        return False
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def require_play(cfg, client, message) -> bool:
    """/play: chat ki 'play mode' setting ke hisaab se."""
    from services.chat_settings import settings_store

    if settings_store is None or settings_store.get(message.chat.id)["play_mode"] == "everyone":
        return True
    if await is_admin(cfg, client, message):
        return True
    await message.reply_text("🚫 Is chat me /play sirf admins kar sakte hain.")
    return False


async def require_admin(cfg, client, message) -> bool:
    """True = aage badho. False = user ko bata diya gaya ki admin chahiye."""
    admin_mode = cfg.admin_only
    if message.chat is not None:
        from services.chat_settings import settings_store  # late import: settings object main.py me banta hai

        if settings_store is not None:
            admin_mode = settings_store.get(message.chat.id)["admin_mode"]
    if not admin_mode:
        return True
    if await is_admin(cfg, client, message):
        return True
    await message.reply_text("🚫 Ye command sirf group admins ke liye hai.")
    return False
