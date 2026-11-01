#!/data/data/com.termux/files/usr/bin/bash
# Ye Termux (bahar wale) me chalta hai. Wake lock leke Debian ke andar bot start karta hai
# tmux session me, taaki Termux band karne par bhi bot chalta rahe.
termux-wake-lock
tmux has-session -t musicbot 2>/dev/null && { echo "Pehle se chal raha hai. Dekhne ke liye: tmux attach -t musicbot"; exit 0; }
tmux new-session -d -s musicbot "proot-distro login debian -- bash -lc 'cd ~/musicbot && ./run.sh'"
echo "Bot start ho gaya. Logs dekhne ke liye: tmux attach -t musicbot   (bahar nikalne: Ctrl+B phir D)"
