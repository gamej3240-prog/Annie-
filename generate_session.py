"""Assistant account ka SESSION_STRING banane ke liye (sirf ek baar chalao).

Voice chat me bot token se join nahi ho sakte, isliye ek normal Telegram
account (assistant) chahiye. Apna main account mat use karo - alag number
ka account banao.

API_ID / API_HASH .env me mil gaye to dobara nahi puchhta, aur session string
apne aap .env me SESSION_STRING= ke aage likh deta hai.
"""
import asyncio
import os

from dotenv import load_dotenv
from pyrogram import Client

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def write_env(key: str, value: str) -> bool:
    try:
        lines = open(ENV_PATH, encoding="utf-8").read().splitlines() if os.path.exists(ENV_PATH) else []
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except OSError:
        return False


async def main() -> None:
    load_dotenv(ENV_PATH)
    api_id = os.getenv("API_ID", "").strip() or input("API_ID: ").strip()
    api_hash = os.getenv("API_HASH", "").strip() or input("API_HASH: ").strip()
    # Ye phone number aur OTP puchhega
    async with Client("gen", api_id=int(api_id), api_hash=api_hash, in_memory=True) as app:
        session = await app.export_session_string()
    if write_env("SESSION_STRING", session):
        print("\n✅ SESSION_STRING .env me save ho gayi. Ise kisi ko mat dikhana (password jaisi hai).")
    else:
        print("\n=== SESSION_STRING (ise secret rakho, password jaisa hai) ===\n")
        print(session)
        print("\n=== is poori line ko .env me SESSION_STRING= ke aage paste karo ===")


if __name__ == "__main__":
    asyncio.run(main())
