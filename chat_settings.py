"""Har chat ki settings (/settings). data/settings.json me save hoti hain."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


settings_store: "ChatSettings | None" = None  # main.py / handlers.register_all isse set karta hai


class ChatSettings:
    def __init__(self, default_admin_mode: bool) -> None:
        self._default_admin_mode = default_admin_mode
        self._data: dict[str, dict] = {}
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        except (OSError, ValueError):
            pass

    def _defaults(self) -> dict:
        return {"play_mode": "everyone", "admin_mode": self._default_admin_mode, "auto_delete": False}

    def get(self, chat_id: int) -> dict:
        merged = self._defaults()
        merged.update(self._data.get(str(chat_id), {}))
        return merged

    def set(self, chat_id: int, key: str, value) -> None:
        self._data.setdefault(str(chat_id), {})[key] = value
        self._save()

    def count(self) -> int:
        return len(self._data)

    def _save(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = SETTINGS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f)
            os.replace(tmp, SETTINGS_FILE)
        except OSError as exc:
            log.warning("Settings save nahi hui: %s", exc)
