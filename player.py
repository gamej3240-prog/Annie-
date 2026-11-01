"""Har group ka queue + voice chat playback (PyTgCalls) yahin sambhalta hai.

Har chat_id ka apna alag ChatState hota hai, isliye multiple groups
ek saath independent chalte hain.
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
from pytgcalls import exceptions, types

from config import Config
from services.audio import Track, remove_file

log = logging.getLogger(__name__)


class PlayerError(Exception):
    """User ko dikhane layak error message ke saath."""


@dataclass
class ChatState:
    queue: deque = field(default_factory=deque)
    current: Track | None = None
    paused: bool = False
    volume: int = 100
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def now_playing_text(track: Track) -> str:
    return (
        "▶️ <b>Ab chal raha hai</b>\n"
        f"🎵 {html.escape(track.title)}\n"
        f"⏱ {track.duration_text}\n"
        f"👤 {html.escape(track.requested_by)}"
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
        """Jin chats me abhi gaana chal raha / paused hai."""
        return {cid: st for cid, st in self._states.items() if st.current is not None}

    async def stop_all(self) -> int:
        """Sab chats se disconnect + queues saaf. Kitne active chats the, wo number deta hai."""
        count = len(self.active())
        for chat_id in list(self._states):
            try:
                await self.stop(chat_id)
            except Exception:
                log.exception("stop_all fail (%s)", chat_id)
        return count

    async def _notify(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id, text)
        except Exception as exc:
            log.warning("Message nahi bhej paya (%s): %s", chat_id, exc)

    # --------------------------------------------------------- assistant
    async def ensure_assistant(self, chat_id: int) -> None:
        """Assistant account group me hona chahiye, nahi hai to join karwata hai."""
        username = getattr(self.assistant.me, "username", None)
        label = f"@{username}" if username else "assistant account"
        try:
            member = await self.assistant.get_chat_member(chat_id, "me")
            if member.status == ChatMemberStatus.BANNED:
                raise PlayerError(f"{label} group me banned hai. Pehle unban karo.")
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
                f"{label} ko group me add karo (ya bot ko admin banao "
                "with 'Invite users' permission), phir dobara /play karo."
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
                log.exception("Update handle karte time error")

    # -------------------------------------------------------- core playback
    async def _play(self, chat_id: int, st: ChatState, track: Track) -> None:
        """Track ko voice chat me bajata hai. Lock pehle se liya hona chahiye."""
        stream = types.MediaStream(
            track.path,
            audio_parameters=types.AudioQuality.MEDIUM,  # kam CPU/data
            video_flags=types.MediaStream.Flags.IGNORE,   # sirf audio
        )
        try:
            await self.calls.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
        except exceptions.NoActiveGroupCall:
            raise PlayerError("Pehle group ka voice chat start karo, phir /play karo.")
        except exceptions.NoAudioSourceFound:
            raise PlayerError("Is file me audio nahi mila.")
        except FileNotFoundError:
            raise PlayerError("Audio file gayab ho gayi.")
        except (NtgConnectionError, ConnectionNotFound, TelegramServerError):
            raise PlayerError("Telegram voice server se connect nahi ho paya. Thodi der baad try karo.")
        except Exception:
            log.exception("calls.play fail (%s)", chat_id)
            raise PlayerError("Play karte time error aaya. Logs check karo.")

        st.current = track
        st.paused = False
        if st.volume != 100:
            try:
                await self.calls.change_volume_call(chat_id, st.volume)
            except Exception as exc:
                log.debug("Volume dobara set nahi hua: %s", exc)

    async def add(self, chat_id: int, track: Track) -> int:
        """0 = turant chalna shuru, warna queue me position."""
        st = self.get_state(chat_id)
        async with st.lock:
            try:
                if st.current is None:
                    await self._play(chat_id, st, track)
                    return 0
                if len(st.queue) >= self.cfg.max_queue:
                    raise PlayerError(f"Queue full hai (max {self.cfg.max_queue}).")
                st.queue.append(track)
                return len(st.queue)
            except PlayerError:
                remove_file(track.path)
                raise

    async def _advance(self, chat_id: int, st: ChatState, announce: bool) -> Track | None:
        """Current gaana khatam, agla chalao. Lock pehle se liya hona chahiye."""
        if st.current:
            remove_file(st.current.path)
        st.current = None
        while st.queue:
            nxt = st.queue.popleft()
            try:
                await self._play(chat_id, st, nxt)
            except PlayerError as exc:
                remove_file(nxt.path)
                await self._notify(chat_id, f"⚠️ {html.escape(nxt.title)} skip hua: {html.escape(str(exc))}")
                continue
            if announce:
                await self._notify(chat_id, now_playing_text(nxt))
            return nxt
        await self._leave(chat_id)
        if announce:
            await self._notify(chat_id, "✅ Queue khatam. Voice chat se nikal gaya.")
        return None

    async def advance(self, chat_id: int) -> Track | None:
        """Gaana apne aap khatam hone par."""
        st = self._states.get(chat_id)
        if not st:
            return None
        async with st.lock:
            return await self._advance(chat_id, st, announce=True)

    async def skip(self, chat_id: int) -> Track | None:
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Abhi kuch play nahi ho raha.")
        async with st.lock:
            return await self._advance(chat_id, st, announce=False)

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
            raise PlayerError("Abhi kuch play nahi ho raha.")
        if st.paused:
            raise PlayerError("Pehle se paused hai. /resume use karo.")
        try:
            await self.calls.pause(chat_id)
        except Exception:
            log.exception("pause fail")
            raise PlayerError("Pause nahi ho paya.")
        st.paused = True

    async def resume(self, chat_id: int) -> None:
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Abhi kuch play nahi ho raha.")
        if not st.paused:
            raise PlayerError("Gaana pehle se chal raha hai.")
        try:
            await self.calls.resume(chat_id)
        except Exception:
            log.exception("resume fail")
            raise PlayerError("Resume nahi ho paya.")
        st.paused = False

    async def set_volume(self, chat_id: int, volume: int) -> None:
        if not 1 <= volume <= 200:
            raise PlayerError("Volume 1 se 200 ke beech me do.")
        st = self._states.get(chat_id)
        if not st or not st.current:
            raise PlayerError("Abhi kuch play nahi ho raha.")
        try:
            await self.calls.change_volume_call(chat_id, volume)
        except Exception:
            log.exception("volume fail")
            raise PlayerError("Volume change nahi ho paya.")
        st.volume = volume

    def get_volume(self, chat_id: int) -> int:
        st = self._states.get(chat_id)
        return st.volume if st else self.cfg.default_volume
