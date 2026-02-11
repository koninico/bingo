#!/bin/bash
set -euo pipefail

# この .command 自身がある場所（= BingoApp）へ移動
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PY="$APP_DIR/.venv/bin/python"
SERVER="$APP_DIR/app/server.py"
RUNTIME_DIR="$APP_DIR/runtime"
PID_FILE="$RUNTIME_DIR/pid.txt"
URL_FILE="$RUNTIME_DIR/url.txt"

mkdir -p "$RUNTIME_DIR"

# すでに起動していたらURLを開くだけ（多重起動防止）
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Server already running (pid=$OLD_PID)"
    if [[ -f "$URL_FILE" ]]; then
      URL="$(cat "$URL_FILE")"
      open -na "Google Chrome" --args --new-window "$URL"
      exit 0
    fi
  fi
fi

# url.txt を前回のまま使わないように削除
rm -f "$URL_FILE"

# サーバ起動（バックグラウンド）
"$PY" "$SERVER" > "$RUNTIME_DIR/server.log" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

# url.txt ができるまで待つ（最大5秒）
for i in {1..50}; do
  if [[ -f "$URL_FILE" ]]; then
    URL="$(cat "$URL_FILE")"
    if [[ -n "$URL" ]]; then
      open -na "Google Chrome" --args --new-window "$URL"
      echo "Opened: $URL"
      exit 0
    fi
  fi
  sleep 0.1
done

echo "ERROR: url.txt was not created in time."
echo "See log: $RUNTIME_DIR/server.log"
exit 1
