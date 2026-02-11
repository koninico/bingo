#!/bin/bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PID_FILE="$APP_DIR/runtime/pid.txt"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No pid file. Server may not be running."
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$PID" ]]; then
  echo "Empty pid. Nothing to stop."
  rm -f "$PID_FILE"
  exit 0
fi

if kill -0 "$PID" 2>/dev/null; then
  echo "Stopping server (pid=$PID)..."
  kill "$PID" 2>/dev/null || true

  # 最大2秒待つ
  for i in {1..20}; do
    if kill -0 "$PID" 2>/dev/null; then
      sleep 0.1
    else
      break
    fi
  done

  # まだ生きてたら強制停止
  if kill -0 "$PID" 2>/dev/null; then
    echo "Force killing server (pid=$PID)..."
    kill -9 "$PID" 2>/dev/null || true
  fi
else
  echo "PID not running: $PID"
fi

rm -f "$PID_FILE"
echo "Stopped."
