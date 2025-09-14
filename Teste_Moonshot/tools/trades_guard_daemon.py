import os, time, json, pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
ENV = os.environ.copy()
ENV_FILE = BASE / ".env_moonshot"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,v = line.split("=",1); ENV.setdefault(k.strip(), v.strip().strip("'").strip('"'))

TRF   = ENV.get("REPORT_TRADES_FILE") or "moonshot_trades.json"
TRADES_PATH = pathlib.Path(TRF) if pathlib.Path(TRF).is_absolute() else (BASE / TRF)
SHADOW_PATH = BASE / "moonshot_trades_shadow.json"
INTERVAL = int(ENV.get("TRADES_GUARD_EVERY_SEC", "15"))

def atomic_write(path: pathlib.Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",",":")))
    tmp.replace(path)

def load_json(p): 
    return json.loads(p.read_text()) if p.exists() and p.stat().st_size>0 else {}

ESSENTIAL = ["entry_price","tp_levels","stop_loss","tick_size","opened_at","side","symbol","tf",
             "tp1_sent","tp2_sent","tp3_sent"]

def loop():
    shadow = load_json(SHADOW_PATH)
    print(f"[trades_guard] rodando a cada {INTERVAL}s | trades={TRADES_PATH}", flush=True)
    while True:
        try:
            data = load_json(TRADES_PATH)
            changed = False
            # 1) atualiza shadow com dados bons de OPEN
            for k,tr in data.items():
                if not isinstance(tr, dict): continue
                if tr.get("status")=="OPEN":
                    snap = shadow.get(k, {})
                    for field in ESSENTIAL:
                        val = tr.get(field, snap.get(field))
                        if val is not None:
                            snap[field] = val
                    shadow[k] = snap

            # 2) para trades fechadas, restaura faltantes a partir do shadow
            for k,tr in data.items():
                if not isinstance(tr, dict): continue
                if str(tr.get("status","")).startswith("CLOSED") or tr.get("status")=="STOP":
                    snap = shadow.get(k, {})
                    for field in ESSENTIAL:
                        if tr.get(field) is None:
                            if field in snap:
                                tr[field] = snap[field]
                                changed = True

            if changed:
                atomic_write(TRADES_PATH, data)
            # persiste shadow periodicamente
            atomic_write(SHADOW_PATH, shadow)
        except Exception as e:
            print(f"[trades_guard] erro: {e}", flush=True)
        time.sleep(INTERVAL)

if __name__=="__main__":
    loop()
