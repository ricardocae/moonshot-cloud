#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
echo "=== Moonshot STATUS ==="
date
echo
echo "-- Processos --"
pgrep -fal "moonshot_wrapper.py|moonshot_agent.py" || echo "⛔ wrapper/agent não encontrados"
pgrep -fal "tp_watcher_daemon.py|sl_watcher_daemon.py" || echo "⛔ watchers não encontrados"
pgrep -fal "hb_sidecar.py" || echo "⛔ sidecar não encontrado"

echo
echo "-- Lockfile --"
[ -f /tmp/moonshot_agent.lock ] && { echo "lock: /tmp/moonshot_agent.lock"; cat /tmp/moonshot_agent.lock | awk '{print "PID:",$0}'; } || echo "sem lock (ok)"

echo
echo "-- Heartbeat --"
python3 - <<'PY'
import json, time, pathlib
p=pathlib.Path("logs/heartbeat.json")
if p.exists():
    try:
        ts=json.loads(p.read_text()).get("ts",0)
        print("heartbeat age (s):", round(time.time()-ts,1))
        print("OK ✅" if time.time()-ts < 120 else "⚠️ ANTIGO")
    except Exception as e:
        print("erro lendo heartbeat:", e)
else:
    print("sem heartbeat.json")
PY

echo
echo "-- agent.out (últimas 25) --"
tail -n 25 logs/agent.out 2>/dev/null || echo "sem logs"

echo
echo "-- tp_watcher.out (últimas 20) --"
tail -n 20 logs/tp_watcher.out 2>/dev/null || echo "sem logs"

echo
echo "-- sl_watcher.out (últimas 20) --"
tail -n 20 logs/sl_watcher.out 2>/dev/null || echo "sem logs"
