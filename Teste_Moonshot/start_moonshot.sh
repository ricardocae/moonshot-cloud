#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
: > logs/agent.out

# força pyenv (cai para system python se não houver pyenv)
PYBIN="$(pyenv which python3 2>/dev/null || command -v python3)"

echo "Usando Python: $($PYBIN -V)"

# sobe o wrapper com o PYBIN escolhido
PYTHONUNBUFFERED=1 nohup "$PYBIN" ./moonshot_wrapper.py >> logs/agent.out 2>&1 &
echo "wrapper PID: $!"
sleep 2
tail -n 80 logs/agent.out || true
