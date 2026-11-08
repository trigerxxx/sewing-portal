#!/usr/bin/env bash
# Запуск портала одной командой (Codespaces, Linux, macOS):  bash run.sh
# Сервер работает в фоне, терминал остаётся свободным. Лог: server.log. Остановить: pkill -f server.py
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8787}"

python3 -c "import lxml, openpyxl" 2>/dev/null || pip install -q -r requirements.txt || exit 1
[ -f data/companies.xlsx ] || python3 seed.py >/dev/null

pkill -f "server.py --port $PORT" 2>/dev/null
sleep 1
nohup python3 server.py --port "$PORT" > server.log 2>&1 &

for _ in $(seq 1 30); do
  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$PORT/', timeout=2)" 2>/dev/null && ok=1 && break
  sleep 1
done

if [ -n "$ok" ]; then
  echo "Готово: сервер работает на порту $PORT."
  echo "Откройте вкладку «Порты», глобус у порта $PORT, и допишите в адресе /cex/"
  echo "Вход: цех Ц-01, логин boss, пароль 123456"
else
  echo "Сервер не запустился. Последние строки лога:"
  tail -20 server.log
  exit 1
fi
