"""Handles each group's queue + voice chat playback (PyTgCalls).

Every chat_id has its own ChatState, so multiple groups
run independently at the same time.
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import deque
from dataclasses import dataclass, field

from ntgcalls import ConnectionError as NtgConnectionError
from ntgcalls import ConnectionNotFound, TelegramServerError
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import UserAlreadyParticipant, UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pytgcalls import exceptions, types

from config import Config
from services.audio import Track, remove_file

log = logging.getLogger(__name__)


class PlayerError(Exception):
    """Carries an error message that is fine to show to the user."""


@dataclass
class ChatState:
    queue: deque = field(default_factory=deque)
    current: Track | None = None
    paused: bool = False
    volume: int = 100
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def now_playing_text(track: Track) -> str:
    return (
        "▶️ <b>Now playing</b>\n"
        f"🎵 {html.escape(track.title)}\n"
        f"⏱ {track.duration_text}\n"
        f"👤 {html.escape(track.requested_by)}"
    )


def player_keyboard(paused: bool = False) -> InlineKeyboardMarkup:
    """Buttons under the 'Now playing' message."""
    b = InlineKeyboardButton
    return InlineKeyboardMarkup(
        [
            [
                b("⏭", callback_data="pl_skip"),
                b("⏹", callback_data="pl_stop"),
                b("▶️" if paused else "⏸", callback_data="pl_pause"),
            ],
            [b("Close", callback_data="pl_close")],
        ]
    )


def queue_keyboard(track: Track) -> InlineKeyboardMarkup:
    """Buttons under the 'Added to queue' message."""
    b = InlineKeyboardButton
    return InlineKeyboardMarkup(
        [[b("Play Now", callback_data=f"pn_{id(track)}"), b("Close", callback_data="pl_close")]]
    )


class Player:
    def __init__(self, cfg: Config, bot, assistant, calls) -> None:
        self.cfg = cfg
        self.bot = bot
        self.assistant = assistant
        self.calls = calls
        self._states: dict[int, ChatState] = {}

    # ------------------------------------------------------------ helpers
    def get_state(self, chat_id: int) -> ChatState:
        if chat_id not in self._states:
            self._states[chat_id] = ChatState(volume=self.cfg.default_volume)
        return self._states[chat_id]

    def snapshot(self, chat_id: int) -> tuple[Track | None, list[Track]]:
        st = self._states.get(chat_id)
        if not st:
            return None, []
        return st.current, list(st.queue)

    def active(self) -> dict[int, ChatState]:
        """Chats where a song is playing / paused right now."""
        return {cid: st for cid, st in self._states.items() if st.current is not None}

    async def stop_all(self) -> int:
        """Disconnects from all chats and clears the queues. Returns how many chats were active."""
        count = len(self.active())
        for chat_id in list(self._states):
            try:
                await self.stop(chat_id)
            except Exception:
                log.exception("stop_all fail (%s)", chat_id)
        return count

    async def _notify(self, chat_id: int, text: str, reply_markup=None) -> None:
        try:
            await self.bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as exc:
            log.warning("Could not send message (%s): %s", chat_id, exc)

    # --------------------------------------------------------- assistant
    async def ensure_assistant(self, chat_id: int) -> None:
        """The assistant account must be in the group; makes it join if it is not."""
        username = getattr(self.assistant.me, "username", None)
        label = f"@{username}" if username else "assistant account"
        try:
            member = await self.assistant.get_chat_member(chat_id, "me")
            if member.status == ChatMemberStatus.BANNED:
                raise PlayerError(f"{label} is banned in this group. Please unban it first.")
            if member.status != ChatMemberStatus.LEFT:
                return
        except PlayerError:
            raise
        except UserNotParticipant:
            pass
        except Exception as exc:
            log.debug("Assistant membership check fail: %s", exc)

        try:
            chat = await self.bot.get_chat(chat_id)
            if chat.username:
                await self.assistant.join_chat(chat.username)
            else:
                link = await self.bot.export_chat_invite_link(chat_id)
                await self.assistant.join_chat(link)
        except UserAlreadyParticipant:
            return
        except Exception as exc:
            log.warning("Assistant join fail (%s): %s", chat_id, exc)
            raise PlayerError(
                f"Please add {label} to the group (or make the bot an admin "
                "with the 'Invite users' permission), then use /play again."
            )

    # ------------------------------------------------------------ events
    def register_events(self) -> None:
        @self.calls.on_update()
        async def _on_update(_, update: types.Update) -> None:
            try:
                if isinstance(update, types.StreamEnded):
                    if update.stream_type == types.StreamEnded.Type.AUDIO:
                        await self.advance(update.chat_id)
                elif isinstance(update, types.ChatUpdate):
                    if update.status in (
                        types.ChatUpdate.Status.KICKED,
                        types.ChatUpdate.Status.LEFT_GROUP,
                        types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                    ):
                        await self.stop(update.chat_id)
            except Exception:
                log.exception("Error while handling an update")

    # -------------------------------------------------------- core playback
    async def _play(self, chat_id: int, st: ChatState, track: Track) -> None:
        """Plays the track in the voice chat. The lock must already be held."""
        stream = types.MediaStream(
            track.path,
            audio_parameters=types.AudioQuality.MEDIUM,  # low CPU/data
            video_flags=types.MediaStream.Flags.IGNORE,   # audio only
        )
        try:
            await self.calls.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
        except exceptions.NoActiveGroupCall:
            raise PlayerError("Please start the group's voice chat first, then use /play.")
        except exceptions.NoAudioSourceFound:
            raise PlayerError("No audio found in this file.")
        except FileNotFoundError:
            raise PlayerError("The audio file went missing.")
        except (NtgConnectionError, ConnectionNotFound, TelegramServerError):
            raise PlayerError("Could not connect to the Telegram voice server. Please try again later.")
        except Exception:
            log.exception("calls.play fail (%s)", chat_id)
            raise PlayerError("An error occurred while playing. Please check the logs.")

        st.current = track
        st.paused = False
        if st.volume != 100:
            try:
                await self.calls.change_volume_call(chat_id, st.volume)
            except Exception as exc:
                log.debug("Volume could not be set again: %s", exc)

    async def add(self, chat_id: int, track: Track) -> int:
        """0 = starts playing right away, otherwise the position in the queue."""
        st = self.get_state(chat_id)
        async with st.lock:
            try:
                if st.current is None:
                    await self._play(chat_id, st, track)
                    return 0
                if len(st.queue) >= self.cfg.max_queue:
                    raise PlayerError(f"The queue is full (max {self.cfg.max_queue}).")
                st.queue.append(track)
                return len(st.queue)
            except PlayerError:
                remove_file(track.path)
                raise

    async def _advance(self, chat_id: int, st: ChatState, announce: bool) -> Track | None:
        """Current song is over, play the next one. The lock must already be held."""
        if st.current:
            remove_file(st.current.path)
        st.current = None
        while st.queue:
            nxt = st.queue.popleft()
            try:
                await self._play(chat_id, st, nxt)
            except PlayerError as exc:
                remove_file(nxt.path)
                await self._notify(chat_id, f"⚠️ {html.escape(nxt.title)} was skipped: {html.escape(str(exc))}")
                continue
            if announce:
                await self._notify(chat_id, now_playing_text(nxt), player_keyboard())
            return nxt
        await self._leave(chat_id)
        if announce:
            await self._notify(chat_id, "✅ Queue finished. Left the voice chat.")
        return None

    async def advance(self, chat_id: int) -> Track | None:
        """When a song ends by itself."""
        st = self._states.get(chat_id)
        if not st:
            return None
        async with st.lock:
            return await self._advance(chat_id, st, announce=True)

    async def skip(self, chat_id: int) -> Track | None:
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Nothing is playing right now.")
        async with st.lock:
            return await self._advance(chat_id, st, announce=False)

    async def play_now(self, chat_id: int, track_key: int) -> Track:
        """Moves a queued song to the front and starts it right away."""
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Nothing is playing right now.")
        async with st.lock:
            target = next((t for t in st.queue if id(t) == track_key), None)
            if target is None:
                raise PlayerError("This song is no longer in the queue.")
            st.queue.remove(target)
            st.queue.appendleft(target)
            nxt = await self._advance(chat_id, st, announce=False)
        if nxt is None:
            raise PlayerError("Could not play this song.")
        return nxt

    async def _leave(self, chat_id: int) -> None:
        try:
            await self.calls.leave_call(chat_id, close=False)
        except Exception as exc:
            log.debug("leave_call: %s", exc)
        self._states.pop(chat_id, None)

    async def stop(self, chat_id: int) -> bool:
        """Playback band + queue clear + voice chat se bahar."""
        st = self._states.get(chat_id)
        if not st:
            return False
        async with st.lock:
            if st.current:
                remove_file(st.current.path)
            for track in st.queue:
                remove_file(track.path)
            st.queue.clear()
            st.current = None
            await self._leave(chat_id)
        return True

    async def shutdown(self) -> None:
        for chat_id in list(self._states):
            try:
                await self.stop(chat_id)
            except Exception:
                log.exception("Shutdown stop fail (%s)", chat_id)

    # ----------------------------------------------------------- controls
    async def pause(self, chat_id: int) -> None:
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Nothing is playing right now.")
        if st.paused:
            raise PlayerError("Already paused. Use /resume.")
        try:
            await self.calls.pause(chat_id)
        except Exception:
            log.exception("pause fail")
            raise PlayerError("Could not pause.")
        st.paused = True

    async def resume(self, chat_id: int) -> None:
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Nothing is playing right now.")
        if not st.paused:
            raise PlayerError("The song is already playing.")
        try:
            await self.calls.resume(chat_id)
        except Exception:
            log.exception("resume fail")
            raise PlayerError("Could not resume.")
        st.paused = False

    async def set_volume(self, chat_id: int, volume: int) -> None:
        if not 1 <= volume <= 200:
            raise PlayerError("Volume must be between 1 and 200.")
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Nothing is playing right now.")
        try:
            await self.calls.change_volume_call(chat_id, volume)
        except Exception:
            log.exception("volume fail")
            raise PlayerError("Could not change the volume.")
        st.volume = volume

    def get_volume(self, chat_id: int) -> int:
        st = self._states.get(chat_id)
        return st.volume if st else self.cfg.default_volume
