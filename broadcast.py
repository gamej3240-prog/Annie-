"""/broadcast and /fbroadcast (bot owners only).

Also remembers every group and every user the bot talks to (saved in a small JSON file),
because Telegram does not let a bot list its own chats.

  /broadcast <text>              send a text to everyone
  /broadcast -users <text>       only to users who started the bot
  /broadcast -groups <text>      only to groups
  /broadcast                     (as a reply) copy that message (photo, formatting etc.) to everyone
  /fbroadcast                    (as a reply) FORWARD that message to everyone (with 'Forwarded from')
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from pyrogram import filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.errors import FloodWait, RPCError
from pyrogram.handlers import MessageHandler

try:
    from pyrogram.handlers import ChatMemberUpdatedHandler
except ImportError:  # very old pyrogram: we only learn about chats from their messages
    ChatMemberUpdatedHandler = None

log = logging.getLogger(__name__)

GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)
# Errors that mean "this chat/user can never receive our messages" -> forget it
DEAD_ERRORS = {
    "UserIsBlocked", "InputUserDeactivated", "UserDeactivated", "UserDeactivatedBan",
    "PeerIdInvalid", "ChatWriteForbidden", "ChannelPrivate", "ChannelInvalid", "ChatIdInvalid",
}
USAGE = (
    "📢 <b>Broadcast</b>\n\n"
    "• <code>/broadcast your text</code>\n"
    "• <code>/broadcast -users your text</code> (only users)\n"
    "• <code>/broadcast -groups your text</code> (only groups)\n"
    "• Reply to any message with <code>/broadcast</code> to copy it to everyone "
    "(photo, video, file, voice, sticker, formatting - all kept)\n"
    "• Send a photo/video/file with <code>/broadcast your caption</code> as its caption\n"
    "• Bold / italic / links typed in the text are kept\n"
    "• Reply to any message with <code>/fbroadcast</code> to forward it to everyone"
)


class Targets:
    """Groups and users the bot knows about (JSON file, survives restarts)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.chats: set[int] = set()
        self.users: set[int] = set()
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.chats = {int(x) for x in data.get("chats", [])}
            self.users = {int(x) for x in data.get("users", [])}
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"chats": sorted(self.chats), "users": sorted(self.users)}, fh)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("Could not save broadcast targets: %s", exc)

    def add_chat(self, chat_id: int) -> None:
        if chat_id not in self.chats:
            self.chats.add(chat_id)
            self._save()

    def add_user(self, user_id: int) -> None:
        if user_id not in self.users:
            self.users.add(user_id)
            self._save()

    def discard(self, target_id: int) -> None:
        if target_id in self.chats or target_id in self.users:
            self.chats.discard(target_id)
            self.users.discard(target_id)
            self._save()


def register(bot, cfg) -> None:
    targets = Targets(os.path.join(cfg.session_dir, "broadcast_targets.json"))
    owner = filters.create(
        lambda _, __, m: bool(m.from_user and m.from_user.id in cfg.owner_ids), name="BroadcastOwner"
    )
    state = {"running": False}
    tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------- remember chats/users
    async def track(client, message) -> None:
        chat = message.chat
        if chat is None:
            return
        if chat.type in GROUP_TYPES:
            targets.add_chat(chat.id)
        elif chat.type == ChatType.PRIVATE:
            targets.add_user(chat.id)

    async def member_update(client, update) -> None:
        try:
            new = update.new_chat_member
            if new is None or not new.user.is_self:
                return
            chat = update.chat
            joined = new.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
            gone = new.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            if chat.type in GROUP_TYPES:
                if joined:
                    targets.add_chat(chat.id)
                elif gone:
                    targets.discard(chat.id)
            elif chat.type == ChatType.PRIVATE and gone:
                targets.discard(chat.id)  # the user blocked the bot
        except Exception as exc:
            log.debug("member_update: %s", exc)

    # ------------------------------------------------------------- sending
    async def _send_all(client, status, ids: list[int], send) -> None:
        ok = failed = removed = 0
        for i, chat_id in enumerate(ids, start=1):
            for attempt in (1, 2):
                try:
                    await send(chat_id)
                    ok += 1
                    break
                except FloodWait as exc:
                    if attempt == 2:
                        failed += 1
                        break
                    await asyncio.sleep(exc.value + 1)
                except RPCError as exc:
                    failed += 1
                    if type(exc).__name__ in DEAD_ERRORS:
                        targets.discard(chat_id)
                        removed += 1
                    break
                except Exception as exc:
                    log.warning("Broadcast to %s failed: %s", chat_id, exc)
                    failed += 1
                    break
            if i % 25 == 0:
                try:
                    await status.edit_text(f"📢 Sending... {i}/{len(ids)}")
                except Exception:
                    pass
            await asyncio.sleep(0.1)  # stay well below Telegram's limits
        try:
            await status.edit_text(
                "✅ <b>Broadcast finished</b>\n\n"
                f"Delivered: {ok}\nFailed: {failed}\n"
                f"Removed from list (blocked / kicked): {removed}"
            )
        except Exception:
            pass

    async def _broadcast(client, message, forward: bool) -> None:
        if state["running"]:
            await message.reply_text("⏳ A broadcast is already running. Please wait for it to finish.")
            return
        replied = message.reply_to_message
        source = message.text or message.caption  # Telegram text object (has .html), or None
        raw = source or ""
        parts = raw.split(None, 1)
        rest = parts[1] if len(parts) > 1 else ""
        # same text but with the formatting (bold, italic, links) as HTML
        html_parts = (source.html if source else "").split(None, 1)
        rest_html = html_parts[1] if len(html_parts) > 1 else ""

        mode = "all"
        while rest.startswith("-"):
            flag, _, rest = rest.partition(" ")
            rest = rest.lstrip()
            _, _, rest_html = rest_html.partition(" ")  # drop the same flag from the HTML copy
            rest_html = rest_html.lstrip()
            if flag.lower() in ("-user", "-users"):
                mode = "users"
            elif flag.lower() in ("-group", "-groups", "-chats"):
                mode = "groups"
            else:
                await message.reply_text(USAGE)
                return

        has_own_media = bool(message.media) and not replied
        if forward and not replied:
            await message.reply_text("Reply to the message you want to forward with <code>/fbroadcast</code>.")
            return
        if not forward and not replied and not has_own_media and not rest:
            await message.reply_text(USAGE)
            return

        ids: list[int] = []
        if mode in ("all", "groups"):
            ids += sorted(targets.chats)
        if mode in ("all", "users"):
            ids += sorted(targets.users)
        if not ids:
            await message.reply_text(
                "📭 No chats or users saved yet. The list fills up as people use the bot "
                "and as the bot is added to groups."
            )
            return

        if forward:
            async def send(chat_id: int) -> None:
                await client.forward_messages(chat_id, replied.chat.id, replied.id)
        elif replied:
            async def send(chat_id: int) -> None:
                await client.copy_message(chat_id, replied.chat.id, replied.id)
        elif has_own_media:
            # photo / video / file sent together with the command as its caption
            async def send(chat_id: int) -> None:
                await client.copy_message(
                    chat_id, message.chat.id, message.id, caption=rest_html, parse_mode=ParseMode.HTML
                )
        else:
            async def send(chat_id: int) -> None:
                await client.send_message(chat_id, rest_html, parse_mode=ParseMode.HTML)

        status = await message.reply_text(
            f"📢 Broadcasting to {len(ids)} chat(s) "
            f"({len([i for i in ids if i in targets.chats])} groups, "
            f"{len([i for i in ids if i in targets.users])} users)..."
        )
        state["running"] = True

        async def runner() -> None:
            try:
                await _send_all(client, status, ids, send)
            finally:
                state["running"] = False

        task = asyncio.create_task(runner())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def broadcast_cmd(client, message) -> None:
        await _broadcast(client, message, forward=False)

    async def fbroadcast_cmd(client, message) -> None:
        await _broadcast(client, message, forward=True)

    bot.add_handler(MessageHandler(broadcast_cmd, filters.command("broadcast") & owner))
    bot.add_handler(MessageHandler(fbroadcast_cmd, filters.command("fbroadcast") & owner))
    # group=8: runs next to the normal handlers, never blocks them
    bot.add_handler(MessageHandler(track, filters.group | filters.private), group=8)
    if ChatMemberUpdatedHandler is not None:
        bot.add_handler(ChatMemberUpdatedHandler(member_update), group=8)
