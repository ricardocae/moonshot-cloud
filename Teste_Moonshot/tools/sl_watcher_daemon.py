import os, time, json, pathlib, requests, fcntl, sys, hashlib
from pathlib import Path
import sys
BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path: sys.path.insert(0, str(BASE))
from moonshot_card import generate_stop_card  # << usa seu gerador de card

BASE = pathlib.Path(__file__).resolve().parent.parent
env = os.environ.copy()
for line in (BASE/".env_moonshot").read_text().splitlines():
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1); env.setdefault(k.strip(), v.strip().strip("'").strip('"'))

TOKEN=env.get("TELEGRAM_BOT_TOKEN")
CHAT =env.get("TELEGRAM_STOPS_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
TAG  =(env.get("STOPS_TAG") or "[TESTE]").strip()
EVERY=int(env.get("STOP_WATCH_EVERY_SEC","15"))
TRF  =env.get("REPORT_TRADES_FILE") or "moonshot_trades.json"
TRADES = pathlib.Path(TRF) if pathlib.Path(TRF).is_absolute() else (BASE/TRF)
SET_STATUS=int(env.get("STOP_SET_STATUS","1"))
SENT_FILE = pathlib.Path(os.path.expanduser(env.get("STOPS_SENT_FILE") or "~/.moonshot_shared/stops_sent.json"))
STOP_BG = env.get("STOP_CARD_TEMPLATE", "assets/moonshot/bg_stoploss.jpg")
OUTDIR = pathlib.Path(env.get("CARD_OUT_DIR") or (BASE/"out"))
OUTDIR.mkdir(parents=True, exist_ok=True)

# lock
lock=open(f"/tmp/sl_watcher_{BASE.name}.lock","w")
try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError: print("[sl] já existe outra instância; saindo.", flush=True); sys.exit(0)

def last_price(sym):
    try:
        r=requests.get("https://api.bybit.com/v5/market/tickers", params={"category":"linear","symbol":sym}, timeout=10)
        j=r.json(); L=(j.get("result") or {}).get("list") or []
        return float(L[0]["lastPrice"]) if L else None
    except Exception: return None

def atomic_write(p,data):
    tmp=p.with_suffix(p.suffix+".tmp"); tmp.write_text(json.dumps(data, separators=(",",":"))); tmp.replace(p)

def pnl_pct(side,entry,price):
    if not entry or not price: return 0.0
    return (price/entry-1.0)*100.0 if side=="LONG" else (1.0-price/entry)*100.0

def load_sent():
    try: return set(json.loads(SENT_FILE.read_text()))
    except Exception: return set()
def save_sent(s):
    try: SENT_FILE.write_text(json.dumps(sorted(s)))
    except Exception: pass
def key(kjson, side, sl): return hashlib.sha1(f"{kjson}|{side}|{sl}".encode()).hexdigest()

def send_photo(path, caption):
    if not (TOKEN and CHAT): return False
    try:
        with open(path, "rb") as f:
            r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                            data={"chat_id":CHAT,"caption":caption},
                            files={"photo":("stop.png", f, "image/png")}, timeout=30)
        return r.ok
    except Exception: return False

def loop():
    print(f"[sl] watching {TRADES} every {EVERY}s | bg={STOP_BG}", flush=True)
    sent=load_sent()
    while True:
        try:
            if not TRADES.exists(): time.sleep(EVERY); continue
            data=json.loads(TRADES.read_text() or "{}"); changed=False
            for k,tr in list(data.items()):
                if not isinstance(tr,dict): continue
                st=str(tr.get("status","")).upper()
                if st.startswith("CLOSED") or st in {"STOP","CANCEL","CANCELED"}:
                    continue
                side=(tr.get("side") or "").upper()
                sym =(tr.get("symbol") or "").upper()
                tf  = str(tr.get("tf") or "")
                sl  = tr.get("stop_loss") or tr.get("sl")
                if not sym or sl is None: continue
                sl=float(sl)
                price=last_price(sym)
                crossed = (price is not None) and ((side=="LONG" and price<=sl) or (side=="SHORT" and price>=sl))
                ksent=key(k, side, sl)
                if crossed and (not tr.get("sl_sent")) and (ksent not in sent):
                    entry=float(tr.get("entry_price") or tr.get("avg_entry") or tr.get("entry") or 0) or 0.0
                    delta=pnl_pct(side, entry, price or sl)
                    caption=f"{TAG} 🛑 Stop Loss | {sym} {side} on {tf}"
                    out = OUTDIR / f"stop_{sym}_{int(time.time())}.png"
                    try:
                        generate_stop_card(
                            symbol=sym, side=side, leverage=str(tr.get("lev") or tr.get("leverage") or ""),
                            roi_pct=delta, entry_price=float(entry),
                            filled_price=float(price if price is not None else sl),
                            sl_price=float(sl), out_path=str(out), bg_path=STOP_BG,
                        )
                        ok = send_photo(out, caption)
                    except Exception as e:
                        ok = False
                        print("[sl] erro card:", e, flush=True)
                    if not ok:
                        # fallback texto
                        try:
                            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                          data={"chat_id":CHAT,"text":f"{caption}\nFilled: {(price or sl):g}\nROI (est.): {delta:.4f}%"},
                                          timeout=10)
                        except Exception: pass
                    tr["sl_sent"]=True
                    if SET_STATUS: tr["status"]="STOP"
                    sent.add(ksent); changed=True
            if changed: atomic_write(TRADES, data); save_sent(sent)
        except Exception as e:
            print("[sl] erro:", e, flush=True)
        time.sleep(EVERY)

if __name__=="__main__": loop()
