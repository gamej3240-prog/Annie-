"""/auth, /unauth, /authusers - authorized users can use the admin commands
(/pause, /skip, /end ...) even if they are not group admins.

The list is saved per chat in data/auth.json, so it stays after a restart.
"""
from __future__ import annotations

import html
import json
import logging
import os

from pyrogram import filters
from pyrogram.handlers import MessageHandler

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
AUTH_FILE = os.path.join(DATA_DIR, "auth.json")
MAX_AUTH_PER_CHAT = 25

_store: dict[str, list[int]] | None = None


def _data() -> dict[str, list[int]]:
    global _store
    if _store is None:
        try:
            with open(AUTH_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            _store = {str(k): [int(x) for x in v] for k, v in raw.items()}
        except (OSError, ValueError, AttributeError, TypeError):
            _store = {}
    return _store


def _save() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = AUTH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data(), f)
        os.replace(tmp, AUTH_FILE)
    except OSError as exc:
        log.warning("Could not save the auth list: %s", exc)


def is_authorized(chat_id: int, user_id: int) -> bool:
    return user_id in _data().get(str(chat_id), [])


def register(bot, player, cfg) -> None:
    async def _is_real_admin(client, message) -> bool:
        """Only real group admins / bot owners can change the list (authorized users cannot)."""
        user = message.from_user
        if user is None:
            return bool(message.sender_chat and message.sender_chat.id == message.chat.id)
        if user.id in cfg.owner_ids:
            return True
        try:
            member = await client.get_chat_member(message.chat.id, user.id)
        except Exception:
            return False
        return member.status.name in ("OWNER", "ADMINISTRATOR")

    async def _target(client, message):
        """Returns the User to (un)authorize: from a reply, an @username or a numeric id."""
        replied = message.reply_to_message
        if replied and replied.from_user:
            return replied.from_user
        if len(message.command) > 1:
            arg = message.command[1].strip()
            try:
                return await client.get_users(int(arg) if arg.lstrip("-").isdigit() else arg)
            except Exception:
                return None
        return None

    async def auth_cmd(client, message) -> None:
        if not await _is_real_admin(client, message):
            await message.reply_text("🚫 Only group admins can use /auth.")
            return
        user = await _target(client, message)
        if user is None:
            await message.reply_text(
                "ℹ️ Reply to a user with <code>/auth</code>, or use "
                "<code>/auth @username</code> / <code>/auth user_id</code>."
            )
            return
        if user.is_bot:
            await message.reply_text("❌ Bots cannot be authorized.")
            return
        users = _data().setdefault(str(message.chat.id), [])
        name = html.escape(user.first_name or str(user.id))
        if user.id in users:
            await message.reply_text(f"ℹ️ {name} is already authorized.")
            return
        if len(users) >= MAX_AUTH_PER_CHAT:
            await message.reply_text(f"❌ The limit is {MAX_AUTH_PER_CHAT} authorized users per chat.")
            return
        users.append(user.id)
        _save()
        await message.reply_text(f"✅ {name} is now authorized to use admin commands in this chat.")

    async def unauth_cmd(client, message) -> None:
        if not await _is_real_admin(client, message):
            await message.reply_text("🚫 Only group admins can use /unauth.")
            return
        user = await _target(client, message)
        if user is None:
            await message.reply_text(
                "ℹ️ Reply to a user with <code>/unauth</code>, or use "
                "<code>/unauth @username</code> / <code>/unauth user_id</code>."
            )
            return
        users = _data().get(str(message.chat.id), [])
        name = html.escape(user.first_name or str(user.id))
        if user.id not in users:
            await message.reply_text(f"ℹ️ {name} is not authorized.")
            return
        users.remove(user.id)
        if not users:
            _data().pop(str(message.chat.id), None)
        _save()
        await message.reply_text(f"🗑 {name} is no longer authorized in this chat.")

    async def authusers_cmd(client, message) -> None:
        users = _data().get(str(message.chat.id), [])
        if not users:
            await message.reply_text("ℹ️ No authorized users in this chat.")
            return
        lines = []
        for i, uid in enumerate(users, 1):
            try:
                u = await client.get_users(uid)
                label = html.escape(u.first_name or str(uid))
            except Exception:
                label = "Unknown user"
            lines.append(f"{i}. {label} (<code>{uid}</code>)")
        await message.reply_text("👥 <b>Authorized users</b>\n" + "\n".join(lines))

    bot.add_handler(MessageHandler(auth_cmd, filters.command("auth") & filters.group))
    bot.add_handler(MessageHandler(unauth_cmd, filters.command("unauth") & filters.group))
    bot.add_handler(MessageHandler(authusers_cmd, filters.command("authusers") & filters.group))
