#!/bin/bash
set -euo pipefail
LOCK="/tmp/teste_moonshot_agent.lock"
if [[ -e "$LOCK" ]]; then
  PID=$(cat "$LOCK")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "[INFO][DEV] Matando PID $PID..."
    kill "$PID" || true
    sleep 1
    ps -p "$PID" > /dev/null 2>&1 && kill -9 "$PID" || true
  fi
  rm -f "$LOCK"
  echo "[OK][DEV] Teste_Moonshot parado."
else
  echo "[INFO][DEV] Nada para parar."
fi
