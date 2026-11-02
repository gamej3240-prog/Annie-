"""Personal playlists. Saved in data/playlists.json (no external database needed).

Layout:  { "<user_id>": { "<name lowercase>": {"name": str, "tracks": [{"title": str, "query": str}]} } }

A track stores only its title and a `query` (link or search text), not the audio file.
The audio is downloaded when the playlist is played.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PLAYLIST_FILE = os.path.join(DATA_DIR, "playlists.json")

MAX_PLAYLISTS = 10  # per user
MAX_TRACKS = 50  # per playlist
MAX_NAME_LEN = 32
_NAME_RE = re.compile(r"^[\w\-]+$", re.UNICODE)


class PlaylistError(Exception):
    """Error message that can be shown to the user as is."""


def clean_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        raise PlaylistError("Please give a playlist name.")
    if len(name) > MAX_NAME_LEN or not _NAME_RE.match(name):
        raise PlaylistError(
            f"Invalid name. Use letters, numbers, - or _ only (no spaces, max {MAX_NAME_LEN} characters)."
        )
    return name


class PlaylistStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}
        try:
            with open(PLAYLIST_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------ helpers
    def _user(self, user_id: int) -> dict[str, dict]:
        return self._data.setdefault(str(user_id), {})

    def _find(self, user_id: int, name: str) -> dict:
        pl = self._data.get(str(user_id), {}).get(clean_name(name).lower())
        if pl is None:
            raise PlaylistError(f"Playlist '{name}' not found. Use /myplaylists to see your playlists.")
        return pl

    def _save(self) -> None:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = PLAYLIST_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            os.replace(tmp, PLAYLIST_FILE)
        except OSError as exc:
            log.warning("Playlists could not be saved: %s", exc)

    # ---------------------------------------------------------- public API
    def count_users(self) -> int:
        return sum(1 for pls in self._data.values() if pls)

    def list(self, user_id: int) -> list[dict]:
        return list(self._data.get(str(user_id), {}).values())

    def get(self, user_id: int, name: str) -> dict:
        return self._find(user_id, name)

    def create(self, user_id: int, name: str) -> str:
        name = clean_name(name)
        pls = self._user(user_id)
        if name.lower() in pls:
            raise PlaylistError(f"You already have a playlist named '{pls[name.lower()]['name']}'.")
        if len(pls) >= MAX_PLAYLISTS:
            raise PlaylistError(f"You can have at most {MAX_PLAYLISTS} playlists. Delete one first.")
        pls[name.lower()] = {"name": name, "tracks": []}
        self._save()
        return name

    def delete(self, user_id: int, name: str) -> str:
        pl = self._find(user_id, name)
        del self._data[str(user_id)][pl["name"].lower()]
        self._save()
        return pl["name"]

    def add(self, user_id: int, name: str, title: str, query: str) -> tuple[dict, int]:
        """Returns (playlist, position of the new track)."""
        pl = self._find(user_id, name)
        if len(pl["tracks"]) >= MAX_TRACKS:
            raise PlaylistError(f"This playlist is full (max {MAX_TRACKS} songs).")
        if any(t["query"].lower() == query.lower() for t in pl["tracks"]):
            raise PlaylistError("This song is already in the playlist.")
        pl["tracks"].append({"title": title[:120], "query": query})
        self._save()
        return pl, len(pl["tracks"])

    def remove(self, user_id: int, name: str, index: int) -> tuple[dict, dict]:
        """index is 1-based. Returns (playlist, removed track)."""
        pl = self._find(user_id, name)
        if not 1 <= index <= len(pl["tracks"]):
            raise PlaylistError(f"Song number must be between 1 and {len(pl['tracks'])}.")
        removed = pl["tracks"].pop(index - 1)
        self._save()
        return pl, removed


store: PlaylistStore | None = None  # set by handlers.register_all
