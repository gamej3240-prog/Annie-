"""Playlist commands: /createplaylist /deleteplaylist /addtoplaylist /removefromplaylist
/playlistinfo /myplaylists /playplaylist

Playlists are personal (per user) and work in groups and in private chat.
/playplaylist works in groups only (it needs a voice chat).
"""
from __future__ import annotations

import html
import logging

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from handlers.common import require_play, user_label
from services import audio
from services.audio import AudioError
from services.player import PlayerError, now_playing_text
from services.playlists import MAX_PLAYLISTS, MAX_TRACKS, PlaylistError

log = logging.getLogger(__name__)

SHOW_LIMIT = 30  # songs shown in /playlistinfo (Telegram message size limit)
ANON_TEXT = "❌ Playlists need your own account. Turn off anonymous admin mode and try again."

PLAYLIST_COMMANDS = [
    "createplaylist", "deleteplaylist", "addtoplaylist", "removefromplaylist",
    "playlistinfo", "myplaylists", "playplaylist",
]


def _uid(message) -> int | None:
    return message.from_user.id if message.from_user else None


def register(bot, player, cfg, store) -> None:
    everywhere = filters.group | filters.private
    loading: set[int] = set()  # chats where a playlist is being loaded right now

    async def create_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        if len(message.command) < 2:
            await message.reply_text(
                "🎵 <b>Create a playlist</b>\n"
                "<code>/createplaylist &lt;name&gt;</code>\n\n"
                "Name: letters, numbers, - or _ (no spaces)."
            )
            return
        try:
            name = store.create(uid, message.command[1])
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        await message.reply_text(
            f"✅ Playlist <b>{html.escape(name)}</b> created.\n"
            f"Add songs: <code>/addtoplaylist {html.escape(name)} song name</code>"
        )

    async def delete_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        if len(message.command) < 2:
            await message.reply_text("🗑 <b>Delete a playlist</b>\n<code>/deleteplaylist &lt;name&gt;</code>")
            return
        try:
            name = store.delete(uid, message.command[1])
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        await message.reply_text(f"🗑 Playlist <b>{html.escape(name)}</b> deleted.")

    async def add_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        args = message.command[1:]
        if not args:
            await message.reply_text(
                "➕ <b>Add a song to a playlist</b>\n"
                "• <code>/addtoplaylist &lt;playlist&gt; song name or link</code>\n"
                "• <code>/addtoplaylist &lt;playlist&gt;</code> while a song is playing "
                "(adds the current song)"
            )
            return
        name = args[0]
        query = " ".join(args[1:]).strip()

        # Check the playlist exists before doing any network work
        try:
            store.get(uid, name)
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return

        if query:
            status = await message.reply_text("🔎 Searching...")
            try:
                title, query = await audio.lookup_meta(query, cfg)
            except AudioError as exc:
                await status.edit_text(f"❌ {html.escape(str(exc), quote=False)}")
                return
        else:
            current, _ = player.snapshot(message.chat.id)
            if current is None:
                await message.reply_text(
                    "❌ Nothing is playing right now. Give a song name or link:\n"
                    f"<code>/addtoplaylist {html.escape(name)} song name</code>"
                )
                return
            if not current.query:
                await message.reply_text("❌ This song came from a Telegram file and can't be saved to a playlist.")
                return
            status = await message.reply_text("⏳ Saving...")
            title, query = current.title, current.query

        try:
            pl, pos = store.add(uid, name, title, query)
        except PlaylistError as exc:
            await status.edit_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        await status.edit_text(
            f"✅ <b>Added to {html.escape(pl['name'])}</b> (#{pos})\n"
            f"🎵 {html.escape(title)}"
        )

    async def remove_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        args = message.command[1:]
        if len(args) < 2:
            await message.reply_text(
                "➖ <b>Remove a song from a playlist</b>\n"
                "<code>/removefromplaylist &lt;playlist&gt; &lt;song number&gt;</code>\n\n"
                "Use /playlistinfo to see song numbers."
            )
            return
        try:
            index = int(args[1])
        except ValueError:
            await message.reply_text("❌ Song number must be a number, e.g. <code>/removefromplaylist mylist 2</code>")
            return
        try:
            pl, removed = store.remove(uid, args[0], index)
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        await message.reply_text(
            f"✅ Removed from <b>{html.escape(pl['name'])}</b>\n"
            f"🎵 {html.escape(removed['title'])}"
        )

    async def info_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        if len(message.command) < 2:
            await message.reply_text("📂 <b>Playlist info</b>\n<code>/playlistinfo &lt;name&gt;</code>")
            return
        try:
            pl = store.get(uid, message.command[1])
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        tracks = pl["tracks"]
        lines = [f"📂 <b>{html.escape(pl['name'])}</b> - {len(tracks)}/{MAX_TRACKS} songs"]
        if not tracks:
            lines.append(f"\nThis playlist is empty. Add songs with <code>/addtoplaylist {html.escape(pl['name'])} song name</code>")
        else:
            lines.append("")
            for i, t in enumerate(tracks[:SHOW_LIMIT], start=1):
                lines.append(f"{i}. {html.escape(t['title'])}")
            if len(tracks) > SHOW_LIMIT:
                lines.append(f"... and {len(tracks) - SHOW_LIMIT} more")
            lines.append(f"\nPlay it in a group: <code>/playplaylist {html.escape(pl['name'])}</code>")
        await message.reply_text("\n".join(lines))

    async def my_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        playlists = store.list(uid)
        if not playlists:
            await message.reply_text(
                "📭 You don't have any playlists yet.\n"
                "Create one with <code>/createplaylist &lt;name&gt;</code>"
            )
            return
        lines = [f"📚 <b>Your playlists</b> ({len(playlists)}/{MAX_PLAYLISTS})\n"]
        for i, pl in enumerate(playlists, start=1):
            n = len(pl["tracks"])
            lines.append(f"{i}. {html.escape(pl['name'])} - {n} song{'s' if n != 1 else ''}")
        await message.reply_text("\n".join(lines))

    async def play_pl_cmd(client, message) -> None:
        uid = _uid(message)
        if uid is None:
            await message.reply_text(ANON_TEXT)
            return
        if not await require_play(cfg, client, message):
            return
        if len(message.command) < 2:
            await message.reply_text("▶️ <b>Play a playlist</b>\n<code>/playplaylist &lt;name&gt;</code>")
            return
        try:
            pl = store.get(uid, message.command[1])
        except PlaylistError as exc:
            await message.reply_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        tracks = list(pl["tracks"])
        if not tracks:
            await message.reply_text("❌ This playlist is empty. Add songs with /addtoplaylist first.")
            return

        chat_id = message.chat.id
        if chat_id in loading:
            await message.reply_text("⏳ A playlist is already being loaded in this chat. Please wait.")
            return
        loading.add(chat_id)
        who = user_label(message)
        status = await message.reply_text(f"⏳ Loading <b>{html.escape(pl['name'])}</b> ({len(tracks)} songs)...")
        added = failed = 0
        stop_reason = ""
        try:
            await player.ensure_assistant(chat_id)
            for i, t in enumerate(tracks, start=1):
                try:
                    track = await audio.resolve_query(t["query"], who, cfg)
                    track.query = t["query"]
                    position = await player.add(chat_id, track)
                except AudioError as exc:
                    log.info("Playlist song skipped (%s): %s", t["title"], exc)
                    failed += 1
                    continue
                except PlayerError as exc:
                    stop_reason = str(exc)
                    break
                added += 1
                if added == 1 and position == 0:
                    await status.edit_text(now_playing_text(track) + f"\n\n⏳ Loading the rest ({i}/{len(tracks)})...")
        except PlayerError as exc:
            await status.edit_text(f"❌ {html.escape(str(exc), quote=False)}")
            return
        except Exception:
            log.exception("/playplaylist unexpected error")
            await status.edit_text("❌ Something went wrong. Please try again later.")
            return
        finally:
            loading.discard(chat_id)

        summary = f"✅ <b>{html.escape(pl['name'])}</b>: {added} song(s) added"
        if failed:
            summary += f", {failed} could not be loaded"
        if stop_reason:
            summary += f"\n⚠️ Stopped: {html.escape(stop_reason)}"
        await status.edit_text(summary)

    bot.add_handler(MessageHandler(create_cmd, filters.command("createplaylist") & everywhere))
    bot.add_handler(MessageHandler(delete_cmd, filters.command("deleteplaylist") & everywhere))
    bot.add_handler(MessageHandler(add_cmd, filters.command("addtoplaylist") & everywhere))
    bot.add_handler(MessageHandler(remove_cmd, filters.command("removefromplaylist") & everywhere))
    bot.add_handler(MessageHandler(info_cmd, filters.command("playlistinfo") & everywhere))
    bot.add_handler(MessageHandler(my_cmd, filters.command("myplaylists") & everywhere))
    bot.add_handler(MessageHandler(play_pl_cmd, filters.command("playplaylist") & filters.group))
