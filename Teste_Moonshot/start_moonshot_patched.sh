#!/usr/bin/env bash
set -Eeuo pipefail

# always run from this script directory
cd "$(dirname "$0")"

export TZ=America/Sao_Paulo
export PYTHONUNBUFFERED=1

mkdir -p logs

LOCK_FILE="/tmp/moonshot_agent.lock"

# If already running, exit 0 (not error)
if [[ -f "$LOCK_FILE" ]] && ps -p "$(cat "$LOCK_FILE" 2>/dev/null)" >/dev/null 2>&1; then
  echo "[start] Já existe uma instância rodando (PID=$(cat "$LOCK_FILE")). Saindo (ok)."
  exit 0
fi

# If you have a venv, activate it (optional)
if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Try to install requirements, but don't crash on transient errors
if [[ -f "requirements.txt" ]]; then
  python3 -m pip install --upgrade pip >> logs/boot.out 2>&1 || true
  python3 -m pip install -r requirements.txt >> logs/boot.out 2>&1 || {
    echo "[warn] pip install falhou; seguindo assim mesmo (veja logs/boot.out)"
  }
fi

# Start agent in background
nohup python3 -u moonshot_agent.py >> logs/agent.out 2>&1 &
echo $! > logs/agent.pid
disown || true

echo "[start] Agent iniciado. PID=$(cat logs/agent.pid). Logs: tail -f logs/agent.out"
exit 0
