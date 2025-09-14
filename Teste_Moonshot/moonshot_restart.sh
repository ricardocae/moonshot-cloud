#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== Parando tudo =="
pkill -f "python3 .*moonshot_(wrapper|agent)\.py" || true
pkill -f "tp_watcher_daemon.py|sl_watcher_daemon.py|hb_sidecar.py" || true
rm -f /tmp/moonshot_agent.lock
sleep 1

echo "== Subindo wrapper =="
mkdir -p logs
: > logs/agent.out
PYTHONUNBUFFERED=1 nohup ./moonshot_wrapper.py >> logs/agent.out 2>&1 &
echo "wrapper PID: $!"
sleep 3
tail -n 40 logs/agent.out || true

echo
echo "== Garantindo sidecar =="
pkill -f hb_sidecar.py || true
nohup python3 -u tools/hb_sidecar.py >> logs/hb_sidecar.out 2>&1 &
pgrep -fal hb_sidecar.py || echo "⚠️ sidecar não iniciou"

echo
echo "== Reiniciando watchers =="
pkill -f "tp_watcher_daemon.py|sl_watcher_daemon.py" || true
nohup python3 -u tools/tp_watcher_daemon.py >> logs/tp_watcher.out 2>&1 &
nohup python3 -u tools/sl_watcher_daemon.py >> logs/sl_watcher.out 2>&1 &
sleep 2
pgrep -fal "tp_watcher_daemon.py|sl_watcher_daemon.py" || echo "⚠️ watchers não iniciaram"

echo
echo "== Heartbeat =="
python3 - <<'PY'
import json, time, pathlib
p=pathlib.Path("logs/heartbeat.json")
print("heartbeat age (s):", round(time.time()-json.loads(p.read_text()).get("ts",0),1) if p.exists() else "sem hb")
PY
