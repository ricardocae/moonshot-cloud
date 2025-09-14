import os, json, time, threading
from datetime import datetime
from pathlib import Path

_HB_STARTED = {}

def start_heartbeat(path="logs/heartbeat.json", interval=30):
    # guarda para evitar múltiplas threads
    if _HB_STARTED.get(path):
        return
    _HB_STARTED[path] = True

    try:
        interval = int(interval)
        if interval < 1:
            interval = 1
    except Exception:
        interval = 30

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    def loop():
        while True:
            hb = {
                "ts": time.time(),
                "ts_human": datetime.now().strftime("%Y-%m-%d %H:%M:%S %z"),
                "pid": os.getpid(),
                "running": True
            }
            tmp = f"{path}.tmp"
            with open(tmp, "w") as f:
                json.dump(hb, f)
            os.replace(tmp, path)  # gravação atômica
            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
