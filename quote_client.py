"""Bot ka Client: jo bhi text/caption bot bhejta ya edit karta hai, sab quote (blockquote) style me.

Ek hi jagah wrap hota hai, isliye har command ka reply, now-playing, errors, start message,
help menu - sab apne aap quote me aate hain.
"""
from __future__ import annotations

from pyrogram import Client

from texts import quote


def _wrap(args: tuple, kwargs: dict, name: str, pos: int) -> tuple:
    if name in kwargs:
        kwargs[name] = quote(kwargs[name])
    elif len(args) > pos:
        args = list(args)
        args[pos] = quote(args[pos])
        args = tuple(args)
    return args


class QuoteClient(Client):
    async def send_message(self, *args, **kwargs):
        args = _wrap(args, kwargs, "text", 1)
        return await super().send_message(*args, **kwargs)

    async def edit_message_text(self, *args, **kwargs):
        args = _wrap(args, kwargs, "text", 2)
        return await super().edit_message_text(*args, **kwargs)

    async def edit_message_caption(self, *args, **kwargs):
        args = _wrap(args, kwargs, "caption", 2)
        return await super().edit_message_caption(*args, **kwargs)

    async def send_photo(self, *args, **kwargs):
        args = _wrap(args, kwargs, "caption", 2)
        return await super().send_photo(*args, **kwargs)

    async def send_animation(self, *args, **kwargs):
        args = _wrap(args, kwargs, "caption", 2)
        return await super().send_animation(*args, **kwargs)

    async def send_video(self, *args, **kwargs):
        args = _wrap(args, kwargs, "caption", 2)
        return await super().send_video(*args, **kwargs)
