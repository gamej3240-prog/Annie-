"""Saare command handlers ek jagah register karta hai."""
from pyrogram.types import BotCommand

from . import controls, dev, play, queue, settings, start
from services import chat_settings as chat_settings_mod

COMMANDS = [
    BotCommand("start", "Bot start karo"),
    BotCommand("play", "Gaana chalao (naam / link / audio par reply)"),
    BotCommand("pause", "Pause karo"),
    BotCommand("resume", "Dobara chalao"),
    BotCommand("skip", "Agla gaana"),
    BotCommand("end", "Band karo aur queue saaf karo"),
    BotCommand("queue", "Queue dekho"),
    BotCommand("volume", "Volume 1-200"),
    BotCommand("help", "Madad"),
]


def register_all(bot, player, cfg) -> None:
    chat_settings_mod.settings_store = chat_settings_mod.ChatSettings(cfg.admin_only)
    store = chat_settings_mod.settings_store
    play.register(bot, player, cfg)
    controls.register(bot, player, cfg)
    queue.register(bot, player, cfg)
    start.register(bot, player, cfg)
    settings.register(bot, player, cfg, store)
    dev.register(bot, player, cfg, store)
