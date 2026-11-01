#!/usr/bin/env bash
# Bot crash ho ya network se kat jaaye to 10 sec baad apne aap restart.
cd "$(dirname "$0")" || exit 1
source venv/bin/activate

while true; do
  python main.py
  code=$?
  # 0 = band karne ko kaha gaya, 2 = config galat (restart se theek nahi hoga)
  if [ "$code" -eq 0 ] || [ "$code" -eq 2 ]; then
    echo "Bot band (code $code)."
    break
  fi
  echo "Bot ruka (code $code). 10 second me restart..."
  sleep 10
done
