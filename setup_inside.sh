#!/usr/bin/env bash
# Debian ke ANDAR chalta hai (termux_setup.sh ise khud chalata hai).
set -e
cd "$(dirname "$0")"

echo "==> Debian packages install ho rahe hain..."
apt update
apt install -y python3 python3-venv python3-pip ffmpeg build-essential python3-dev

echo "==> Python libraries install ho rahi hain (kuch minute lag sakte hain)..."
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
chmod +x run.sh

[ -f .env ] || cp .env.example .env

# .env me KEY ki value hai ya nahi
env_get() { grep -E "^$1=" .env | head -n1 | cut -d= -f2-; }
# .env me KEY=VALUE likho (special characters safe)
env_set() {
  KEY="$1" VAL="$2" python3 - <<'PY'
import os
key, val = os.environ["KEY"], os.environ["VAL"]
lines = open(".env", encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if l.startswith(key + "="):
        lines[i] = f"{key}={val}"
        break
else:
    lines.append(f"{key}={val}")
open(".env", "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}
ask() {
  local key="$1" label="$2"
  if [ -z "$(env_get "$key")" ]; then
    read -r -p "$label: " val
    env_set "$key" "$val"
  fi
}

echo
echo "==> Ab settings bharo (my.telegram.org aur @BotFather se)"
ask API_ID "API_ID"
ask API_HASH "API_HASH"
ask BOT_TOKEN "BOT_TOKEN"

if [ -z "$(env_get SESSION_STRING)" ]; then
  echo
  echo "==> Assistant account login (alag number ka account). Phone number + OTP puchhega."
  python generate_session.py
fi

echo
echo "✅ Setup complete."
