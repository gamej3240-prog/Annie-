# 🎧 MusicBot (Termux + proot Debian)

Telegram group voice chat me gaana bajane wala bot. Poora phone par chalta hai, VPS nahi chahiye.

## ⚡ Quick install (ek hi command me)
1. Termux (F-Droid wala) kholo aur `musicbot.zip` ko phone ke Download folder me rakho.
2. Ye chalao:
```
termux-setup-storage
pkg install -y unzip
cd ~ && unzip -o ~/storage/downloads/musicbot.zip && bash ~/musicbot/termux_setup.sh
```
Ye script khud sab install karta hai, phir API_ID, API_HASH, BOT_TOKEN puchhta hai aur assistant account ka phone number + OTP. End me bot 24/7 start kar deta hai.
Update ke liye nayi zip se wahi command dobara chalao (aapki `.env` nahi badlegi).

Neeche wala manual tareeka tab dekho jab quick install me kuch atak jaye.

## 🧪 Pehle sirf test karna ho (sirf BOT_TOKEN se)
API_ID / assistant number abhi nahi hai to `test_bot.py` chalao. Ye sirf start message, buttons, help menu aur `/setstart` `/delstart` dikhata hai (gaana nahi bajta). Koi library install nahi karni, sirf Python 3:
```
python test_bot.py
```
Token puchhega (ya `.env` me `BOT_TOKEN=` ho to wahi le lega). Band: Ctrl+C. Full bot (`main.py`) chalane se pehle ise band karna, dono ek token pe ek saath nahi chalte.

## ⚠️ Teen zaroori baatein

1. **Bot token se voice chat join nahi hota.** Telegram sirf normal accounts ko voice chat me aane deta hai. Isliye 2 cheezein chahiye: *Bot* (commands leta hai) + *Assistant account* (voice chat me gaana bajata hai). Assistant ke liye alag number ka account banao, apna main account nahi.
2. **Seedha Termux me install nahi hoga.** `ntgcalls` (voice engine) ke ready wheels sirf glibc Linux ke hain; Termux bionic use karta hai. Isliye Termux ke andar **Debian (proot-distro)** chalate hain. Ye har step me neeche hai.
3. **Naam se search Internet Archive par hoti hai** (free/legal, par popular filmi gaane wahan nahi milte). Apni audio file par reply karke `/play` ya direct `.mp3` link sabse bharosemand hai.

## Install (zero se)

### 1. Termux
F-Droid ya GitHub releases se install karo (Play Store wala purana hai).

### 2. Termux update + tools
```
pkg update -y && pkg upgrade -y
pkg install -y proot-distro tmux termux-api unzip
```
Phir **Termux:API** app bhi F-Droid se install karo (wake lock ke liye).

### 3. Debian install
```
proot-distro install debian
proot-distro login debian
```
Ab prompt badal jayega, aap Debian ke andar ho.

### 4. Debian me Python + FFmpeg
```
apt update && apt install -y python3 python3-venv python3-pip ffmpeg build-essential python3-dev
```

### 5. Project copy karo
Zip ko phone ke Download me rakho. Debian ke andar se Termux/Android storage ke liye pehle Termux me `termux-setup-storage` chalao, phir:
```
cp /sdcard/Download/musicbot.zip ~/ && cd ~ && unzip musicbot.zip && cd musicbot
```
(Agar `/sdcard` Debian me na dikhe to zip ko Termux home me copy karke `proot-distro login debian --bind ~/:/host` se kholo.)

### 6. Python libraries
```
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 7. BotFather se bot
Telegram me @BotFather -> `/newbot` -> naam do -> **token** copy karo. Phir `/setprivacy` -> bot chuno -> **Disable** (taaki group commands mile). Bot ko group me add karke **admin** banao (Invite users permission ke saath).

### 8. API ID / API HASH
https://my.telegram.org -> login (assistant ya apne number se) -> API development tools -> app banao -> `api_id`, `api_hash`.

### 9. Config
```
cp .env.example .env
nano .env
```
API_ID, API_HASH, BOT_TOKEN bharo (`nano`: save = Ctrl+O, Enter; exit = Ctrl+X).

Assistant ki session string:
```
python generate_session.py
```
Phone number + OTP puchhega. Jo lambi string aaye use `.env` me `SESSION_STRING=` ke aage paste karo. **Ye string password jaisi hai, kisi ko mat do.**

### 10. Test run
```
./run.sh
```
Log me `Ready: bot @... | assistant @...` aana chahiye. Group me voice chat **start karo**, phir `/play` try karo. Ctrl+C se band.

### 11. Background me 24/7
Debian se bahar niklo (`exit`), Termux me:
```
cd ~
termux-wake-lock
```
Phir bot start karne ke liye (ek baar script copy karo):
```
cp ~/../usr/var/lib/proot-distro/installed-rootfs/debian/root/musicbot/termux_start.sh ~/termux_start.sh
chmod +x ~/termux_start.sh && ~/termux_start.sh
```
Logs dekhna: `tmux attach -t musicbot` (bahar: Ctrl+B phir D). Band karna: `tmux kill-session -t musicbot`.

## Android background restrictions (MIUI / K20 Pro)
Android aur MIUI background apps ko maar dete hain. Ye sab karo:
- Termux ko notification me **Acquire wakelock** dabao ya `termux-wake-lock` chalao.
- Settings -> Apps -> Termux -> **Battery saver: No restrictions**, **Autostart: ON**.
- Recent apps me Termux card ko **lock** karo (card ko niche kheencho -> lock icon).
- Settings -> Battery -> Termux ko optimization se bahar rakho.
- Charging par rakho, aur phone ki "Battery saver" mode band rakho.
- WiFi sleep policy "Never" rakho.

## Automatic recovery
- Pyrogram chhote network breaks khud reconnect karta hai.
- `main.py` ka watchdog har 60 sec Telegram ping karta hai; lagatar 3 baar fail hua to exit karta hai.
- `run.sh` exit hone par 10 sec baad bot dobara start karta hai.
- Note: restart par queue memory se jaati hai (RAM bachane ke liye database nahi rakha); voice chat me `/play` dobara karna padega.

## Files
- `main.py` - start, logging, watchdog
- `config.py` - .env se settings
- `handlers/` - commands (`play.py`, `controls.py`, `queue.py`, `common.py`)
- `services/audio.py` - search/download/check, `services/player.py` - queue + voice chat
- `generate_session.py` - assistant session string banane ke liye

## Common problems
- **"Pehle voice chat start karo"**: group me voice chat chalu karo.
- **Assistant join nahi hua**: bot ko admin banao (Invite users) ya assistant ko manually add karo.
- **pip me tgcrypto error**: `apt install build-essential python3-dev` chalao, ya requirements se `pytgcrypto` hata do (sirf thoda slow hoga).
- **Gaana nahi mila**: Internet Archive me nahi hai. Direct .mp3 link ya audio file reply use karo.

## Legal
`ENABLE_YT_SEARCH=true` (default ON) se `/play gaane ka naam` YouTube se search + download karta hai, aur youtube.com / youtu.be links bhi chalte hain. Ye YouTube ke Terms of Service ke khilaf ho sakta hai aur ye aapki apni zimmedari hai. Band karne ke liye `.env` me `ENABLE_YT_SEARCH=false` karo. Kabhi-kabhi YouTube download rok deta hai; tab `pip install -U yt-dlp` (venv ke andar) chalao.
Baaki audio sirf wahi chalao jiska aapko right hai (apni files, Creative Commons, public domain).
