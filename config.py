"""All settings come from here (the .env file or environment variables).

No secret is hardcoded in the code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Direct links with these extensions are downloaded as they are
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac")


class ConfigError(Exception):
    """Raised when something in .env is missing or wrong."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} was not found in .env. See .env.example.")
    return value


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got: {raw!r}")
    return max(value, minimum)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _ids(name: str, default: str) -> tuple[int, ...]:
    """Comma-separated Telegram user IDs, e.g.: 111,222"""
    raw = os.getenv(name, "").strip() or default
    out = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            raise ConfigError(f"{name} must contain only numbers (separated by commas), got: {part!r}")
    return tuple(out)


def _list(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    session_string: str
    owner_ids: tuple[int, ...]
    admin_only: bool
    max_queue: int
    max_duration: int  # seconds
    max_file_mb: int
    default_volume: int
    log_level: str
    enable_ytdlp: bool
    enable_yt_search: bool
    enable_archive_search: bool
    allowed_domains: tuple[str, ...]
    watchdog_interval: int
    watchdog_max_fails: int
    download_dir: str
    session_dir: str
    log_dir: str


def load_config() -> Config:
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        api_id = int(_required("API_ID"))
    except ValueError:
        raise ConfigError("API_ID must be a number.")

    return Config(
        api_id=api_id,
        api_hash=_required("API_HASH"),
        bot_token=_required("BOT_TOKEN"),
        session_string=_required("SESSION_STRING"),
        owner_ids=_ids("OWNER_ID", "1864818152,8097560108"),
        admin_only=_bool("ADMIN_ONLY", True),
        max_queue=_int("MAX_QUEUE", 15, minimum=1),
        max_duration=_int("MAX_DURATION_MIN", 30, minimum=1) * 60,
        max_file_mb=_int("MAX_FILE_MB", 50, minimum=1),
        default_volume=min(max(_int("DEFAULT_VOLUME", 100), 1), 200),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        enable_ytdlp=_bool("ENABLE_YTDLP", True),
        enable_yt_search=_bool("ENABLE_YT_SEARCH", True),
        # Internet Archive mostly has very old recordings, so it is only a last resort (off by default)
        enable_archive_search=_bool("ENABLE_ARCHIVE_SEARCH", False),
        allowed_domains=_list("ALLOWED_DOMAINS", "archive.org,youtube.com,youtu.be,music.youtube.com,soundcloud.com,bandcamp.com"),
        watchdog_interval=_int("WATCHDOG_INTERVAL", 60, minimum=15),
        watchdog_max_fails=_int("WATCHDOG_MAX_FAILS", 3, minimum=1),
        download_dir=os.path.join(base, "downloads"),
        session_dir=os.path.join(base, "sessions"),
        log_dir=os.path.join(base, "logs"),
    )
