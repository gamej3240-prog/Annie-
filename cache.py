"""Remembers songs already uploaded to the cache channel (query -> Telegram file_id)."""
import json
import os
import re

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "song_cache.json")

try:
    with open(_FILE, encoding="utf-8") as f:
        _data = json.load(f)
except Exception:
    _data = {}


def _key(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower().strip())


def get(q: str):
    return _data.get(_key(q))


def put(q: str, file_id: str, title: str, duration: int) -> None:
    _data[_key(q)] = {"file_id": file_id, "title": title, "duration": duration}
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, _FILE)
