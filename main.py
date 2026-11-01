"""MusicBot ka entry point. Chalane ke liye:  python main.py  (ya ./run.sh)"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
from contextlib import suppress
from logging.handlers import RotatingFileHandler

from pyrogram import Client
from pyrogram.enums import ParseMode
from pytgcalls import PyTgCalls

from config import ConfigError, load_config
from handlers import COMMANDS, register_all
from services.player import Player
from services.quote_client import QuoteClient

log = logging.getLogger("musicbot")


def setup_logging(level: str, log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    # Log file 1 MB se badi nahi hogi (2 purani copies rakhta hai) - storage bachta hai
    logfile = RotatingFileHandler(
        os.path.join(log_dir, "musicbot.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    logfile.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(logfile)
    for noisy in ("pyrogram", "aiohttp", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def watchdog(bot: Client, assistant: Client, interval: int, max_fails: int) -> None:
    """Har `interval` sec me Telegram ping karta hai.

    Pyrogram chhote network breaks khud sambhal leta hai. Agar lagatar
    `max_fails` baar fail ho (jaise connection atak gaya), to process exit
    karta hai taaki run.sh use fresh restart de.
    """
    fails = 0
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.wait_for(bot.get_me(), timeout=20)
            await asyncio.wait_for(assistant.get_me(), timeout=20)
            if fails:
                log.info("Network wapas aa gaya.")
            fails = 0
        except Exception as exc:
            fails += 1
            log.warning("Watchdog ping fail %d/%d: %s", fails, max_fails, exc)
            if fails >= max_fails:
                log.error("Connection recover nahi hua. Restart ke liye exit.")
                os._exit(3)


async def wait_for_stop_signal() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def safe_stop(client: Client) -> None:
    with suppress(Exception):
        await client.stop()


async def run() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"❌ Config error: {exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.log_level, cfg.log_dir)

    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        log.error("ffmpeg/ffprobe nahi mila. 'apt install ffmpeg' chalao.")
        return 2

    os.makedirs(cfg.download_dir, exist_ok=True)
    os.makedirs(cfg.session_dir, exist_ok=True)
    # Pichhli run ki bachi hui files hata do
    for name in os.listdir(cfg.download_dir):
        path = os.path.join(cfg.download_dir, name)
        if os.path.isfile(path):
            with suppress(OSError):
                os.remove(path)

    bot = QuoteClient(
        name="musicbot",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        workdir=cfg.session_dir,
        parse_mode=ParseMode.HTML,
    )
    assistant = Client(
        name="assistant",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        session_string=cfg.session_string,
        in_memory=True,
    )
    calls = PyTgCalls(assistant, cache_duration=100)
    player = Player(cfg, bot, assistant, calls)

    try:
        await bot.start()
        await assistant.start()
        await calls.start()
    except Exception:
        log.exception("Start nahi ho paya (internet / credentials check karo)")
        await safe_stop(assistant)
        await safe_stop(bot)
        return 1  # run.sh 10 sec baad dobara try karega

    player.register_events()
    register_all(bot, player, cfg)
    with suppress(Exception):
        await bot.set_bot_commands(COMMANDS)

    log.info("Ready: bot @%s | assistant @%s", bot.me.username, assistant.me.username)
    watch = asyncio.create_task(watchdog(bot, assistant, cfg.watchdog_interval, cfg.watchdog_max_fails))

    await wait_for_stop_signal()

    log.info("Band ho raha hai...")
    watch.cancel()
    await player.shutdown()
    await safe_stop(assistant)
    await safe_stop(bot)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
