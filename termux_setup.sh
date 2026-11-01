#!/data/data/com.termux/files/usr/bin/bash
# Poora setup ek command me. Termux me (Debian ke bahar) chalao:
#   cd ~ && unzip -o ~/storage/downloads/musicbot.zip && bash ~/musicbot/termux_setup.sh
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "==> Termux packages..."
pkg update -y && pkg upgrade -y
pkg install -y proot-distro tmux termux-api unzip

ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/debian"
if [ ! -d "$ROOTFS" ]; then
  echo "==> Debian install ho raha hai..."
  proot-distro install debian
fi

echo "==> Bot ki files Debian me copy ho rahi hain..."
mkdir -p "$ROOTFS/root/musicbot"
cp -r "$SRC"/. "$ROOTFS/root/musicbot/"

echo "==> Debian ke andar setup..."
proot-distro login debian -- bash -lc "cd ~/musicbot && bash setup_inside.sh"

cp "$SRC/termux_start.sh" ~/termux_start.sh
chmod +x ~/termux_start.sh

echo
read -r -p "Bot abhi start karun (24/7 background me)? [y/n]: " ans
if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
  ~/termux_start.sh
else
  echo "Baad me start karne ke liye:  ~/termux_start.sh"
fi
