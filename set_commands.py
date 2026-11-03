"""Sets the bot's command menu (the list shown when you type "/") in English.

Run once:   python set_commands.py
Needs BOT_TOKEN in the environment or in a .env file in the same folder.
Uses only the Python standard library.
"""
import json
import os
import sys
import urllib.request

COMMANDS = [
    ("start", "Start the bot"),
    ("play", "Play a song (name / link / reply to audio)"),
    ("pause", "Pause playback"),
    ("resume", "Resume playback"),
    ("skip", "Skip to the next song"),
    ("end", "Stop and clear the queue"),
    ("queue", "View the queue"),
    ("volume", "Set volume (1-200)"),
    ("help", "Help"),
]


def get_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if token:
        return token
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def call(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> None:
    token = get_token()
    if not token:
        sys.exit("BOT_TOKEN not found. Put it in .env or export BOT_TOKEN=...")
    cmds = [{"command": c, "description": d} for c, d in COMMANDS]
    # Clear every scope first so no old Hinglish list stays behind, then set the default one.
    for scope in ("default", "all_private_chats", "all_group_chats", "all_chat_administrators"):
        call(token, "deleteMyCommands", {"scope": {"type": scope}})
    result = call(token, "setMyCommands", {"commands": cmds})
    print("Done: command menu is now in English." if result.get("ok") else f"Failed: {result}")


if __name__ == "__main__":
    main()
