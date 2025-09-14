import os, time, json, subprocess, pathlib, datetime

LOGS = [pathlib.Path("logs/agent.out"), pathlib.Path("logs/fg.out")]
HB   = pathlib.Path("logs/heartbeat.json")
STATE= pathlib.Path("logs/hb_state.json")
pathlib.Path("logs").mkdir(exist_ok=True)

# ---- Telegram (desligado por padrão) ----
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT  = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHANNEL")
SEND_ENABLED = bool(int(os.getenv("HB_TG_ON","0")))               # 0=off, 1=on
KEEPALIVE_HOURS = float(os.getenv("HB_TG_KEEPALIVE_HOURS","0"))   # 0=off
HB_FORCE = bool(int(os.getenv("HB_FORCE","0")))                   # 1=força update sem checar log freshness

def pgrep(pat):
    try:
        out = subprocess.check_output(["pgrep","-fal",pat], text=True)
        return [l for l in out.strip().splitlines() if l]
    except subprocess.CalledProcessError:
        return []

def agent_alive():
    return bool(pgrep(r"python3 .*moonshot_(wrapper|agent)\.py"))

def any_log_fresh(th=180):
    now = time.time()
    for L in LOGS:
        if L.exists() and (now - L.stat().st_mtime) < th:
            return True
    return False

def load_state():
    try:
        return json.loads(STATE.read_text())
    except:
        return {"state": "unknown", "last_notify": 0, "last_keepalive": 0}

def save_state(s):
    STATE.write_text(json.dumps(s))

def telegram_send(text):
    if not (SEND_ENABLED and TOKEN and CHAT):
        return
    try:
        try:
            import certifi, os as _os
            _os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except Exception:
            pass
        import requests
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT, "text": text}, timeout=10)
    except Exception:
        pass

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st = load_state()

while True:
    alive = agent_alive()
    fresh = any_log_fresh() or HB_FORCE

    # atualiza heartbeat se o agent estiver vivo e o log estiver ok (ou forçado)
    if alive and fresh:
        HB.write_text(json.dumps({"ts": time.time()}))

    # eventos de UP/DOWN (opcionais)
    new_state = "up" if (alive and fresh) else "down"
    if new_state != st.get("state"):
        telegram_send(f"Moonshot {new_state.upper()} • {now_str()}")
        st["state"] = new_state
        st["last_notify"] = time.time()
        save_state(st)

    # keepalive opcional
    if KEEPALIVE_HOURS > 0 and new_state == "up":
        if time.time() - st.get("last_keepalive", 0) > KEEPALIVE_HOURS*3600:
            telegram_send(f"Moonshot alive ✅ • {now_str()}")
            st["last_keepalive"] = time.time()
            save_state(st)

    time.sleep(30)
