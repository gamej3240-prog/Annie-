"""PREVIEW BOT - sirf BOT_TOKEN chahiye (API_ID / API_HASH / assistant number nahi).

Isse aap dekh sakte ho ki /start message, buttons, help menu aur /setstart /delstart
sahi dikh rahe hain ya nahi. Gaana bajana (voice chat) isme NAHI hai - uske liye main.py chahiye.

Chalane ke liye:   python test_bot.py
Koi library install nahi karni, sirf Python 3 chahiye. Band karne ke liye Ctrl+C.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from texts import (
    BOT_NAME, category_rows, category_text, help_menu_rows, help_menu_text, quote, start_rows, start_text,
)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
START_FILE = os.path.join(DATA_DIR, "start.json")
DEFAULT_OWNERS = (1864818152, 8097560108)
CATEGORY_KEYS = ("users", "admins", "owner", "playlist", "devs", "autoplay")

# Ye commands main.py (full bot) me kaam karte hain, preview me nahi
FULL_ONLY = {
    "play", "pause", "resume", "skip", "end", "stop", "queue", "volume",
    "settings", "stats", "av", "clearass", "leaveall", "logger",
}

TOKEN = ""
OWNERS: tuple[int, ...] = DEFAULT_OWNERS
BOT_USERNAME = ""


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(os.path.join(BASE, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def api(method: str, **params) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def markup(rows) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": label, "url": val} if kind == "url" else {"text": label, "callback_data": val}
                for label, kind, val in row
            ]
            for row in rows
        ]
    }


def load_start_media() -> dict | None:
    try:
        with open(START_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if data.get("file_id") else None
    except (OSError, ValueError):
        return None


def media_of(msg: dict) -> dict | None:
    if msg.get("photo"):
        return {"type": "photo", "file_id": msg["photo"][-1]["file_id"]}
    if msg.get("animation"):
        return {"type": "animation", "file_id": msg["animation"]["file_id"]}
    if msg.get("video"):
        return {"type": "video", "file_id": msg["video"]["file_id"]}
    return None


def reply(msg: dict, text: str, kb: dict | None = None) -> dict:
    params = {
        "chat_id": msg["chat"]["id"],
        "text": quote(text),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
        "reply_parameters": {"message_id": msg["message_id"], "allow_sending_without_reply": True},
    }
    if kb:
        params["reply_markup"] = kb
    return api("sendMessage", **params)


def send_start(msg: dict) -> None:
    user = msg.get("from") or {}
    text = start_text(user.get("first_name") or "there")
    kb = markup(start_rows(BOT_USERNAME))
    media = load_start_media()
    if media:
        method = {"photo": "sendPhoto", "animation": "sendAnimation", "video": "sendVideo"}[media["type"]]
        res = api(
            method,
            chat_id=msg["chat"]["id"],
            caption=quote(text),
            parse_mode="HTML",
            reply_markup=kb,
            reply_parameters={"message_id": msg["message_id"], "allow_sending_without_reply": True},
            **{media["type"]: media["file_id"]},
        )
        if res.get("ok"):
            return
        print("Start media nahi gayi, text bhej raha hoon:", res.get("description"))
    reply(msg, text, kb)


def edit(cb_msg: dict, text: str, kb: dict) -> None:
    has_media = any(cb_msg.get(k) for k in ("photo", "video", "animation"))
    common = {"chat_id": cb_msg["chat"]["id"], "message_id": cb_msg["message_id"], "parse_mode": "HTML", "reply_markup": kb}
    if has_media:
        api("editMessageCaption", caption=quote(text), **common)
    else:
        api("editMessageText", text=quote(text), link_preview_options={"is_disabled": True}, **common)


def handle_message(msg: dict) -> None:
    text = msg.get("text") or msg.get("caption") or ""
    if not text.startswith("/"):
        return
    head = text.split()[0][1:]
    cmd, _, target = head.partition("@")
    cmd = cmd.lower()
    if target and target.lower() != BOT_USERNAME.lower():
        return  # kisi aur bot ke liye hai
    user = msg.get("from") or {}
    is_owner = user.get("id") in OWNERS

    if cmd == "start":
        send_start(msg)
    elif cmd == "help":
        reply(msg, help_menu_text(user.get("first_name") or "there"), markup(help_menu_rows()))
    elif cmd == "setstart":
        if not is_owner:
            reply(msg, "🚫 Ye command sirf bot owner ke liye hai.")
            return
        media = media_of(msg.get("reply_to_message") or {})
        if not media:
            reply(msg, "❌ Kisi photo (ya video/GIF) par reply karke <code>/setstart</code> likho.")
            return
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(START_FILE, "w", encoding="utf-8") as f:
            json.dump(media, f)
        reply(msg, "✅ Start pic set ho gayi.")
    elif cmd == "delstart":
        if not is_owner:
            reply(msg, "🚫 Ye command sirf bot owner ke liye hai.")
            return
        try:
            os.remove(START_FILE)
            reply(msg, "🗑 Start pic hata di.")
        except OSError:
            reply(msg, "ℹ️ Abhi koi start pic set nahi hai.")
    elif cmd in FULL_ONLY:
        reply(msg, f"🧪 <b>Preview mode</b>\n<code>/{cmd}</code> abhi kaam nahi karega. "
                   "Ye full bot (main.py) me chalega jab API_ID, API_HASH aur assistant ka session ho.")


def handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    msg = cb.get("message")
    if not msg:
        api("answerCallbackQuery", callback_query_id=cb["id"])
        return
    name = (cb.get("from") or {}).get("first_name") or "there"
    if data == "help_open":
        edit(msg, help_menu_text(name), markup(help_menu_rows()))
    elif data == "help_back":
        edit(msg, start_text(name), markup(start_rows(BOT_USERNAME)))
    elif data.startswith("hc_") and data[3:] in CATEGORY_KEYS:
        edit(msg, category_text(data[3:]), markup(category_rows()))
    elif data == "help_close":
        res = api("deleteMessage", chat_id=msg["chat"]["id"], message_id=msg["message_id"])
        if not res.get("ok"):
            api("answerCallbackQuery", callback_query_id=cb["id"], text="Close nahi ho paya.")
            return
    api("answerCallbackQuery", callback_query_id=cb["id"])


def handle_update(upd: dict) -> None:
    if "message" in upd:
        handle_message(upd["message"])
    elif "callback_query" in upd:
        handle_callback(upd["callback_query"])


def main() -> int:
    global TOKEN, OWNERS, BOT_USERNAME
    env = read_env()
    TOKEN = os.getenv("BOT_TOKEN") or env.get("BOT_TOKEN") or input("BOT_TOKEN: ").strip()
    raw_owners = os.getenv("OWNER_ID") or env.get("OWNER_ID") or ""
    try:
        parsed = tuple(int(x) for x in raw_owners.replace(" ", "").split(",") if x)
        OWNERS = parsed or DEFAULT_OWNERS
    except ValueError:
        OWNERS = DEFAULT_OWNERS

    me = api("getMe")
    if not me.get("ok"):
        print("❌ Token galat hai ya internet nahi:", me.get("description"))
        return 1
    BOT_USERNAME = me["result"]["username"]
    api("deleteWebhook")
    api("setMyCommands", commands=[
        {"command": "start", "description": "Bot start karo"},
        {"command": "help", "description": "Help menu"},
    ])
    print(f"✅ Preview bot chalu: @{BOT_USERNAME}  ({BOT_NAME})  [quote mode ON]")
    print("Telegram me /start bhejo. Band karne ke liye Ctrl+C.")

    offset = 0
    while True:
        res = api("getUpdates", offset=offset, timeout=30, allowed_updates=["message", "callback_query"])
        if not res.get("ok"):
            print("getUpdates error:", res.get("description"))
            if "Conflict" in str(res.get("description")):
                print("⚠️ Ye bot token kahin aur (main.py?) chal raha hai. Pehle use band karo.")
            time.sleep(5)
            continue
        for upd in res["result"]:
            offset = upd["update_id"] + 1
            try:
                handle_update(upd)
            except Exception as exc:
                print("Update handle error:", exc)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nBand.")
