import os, time, json, pathlib, requests, fcntl, sys, hashlib
from pathlib import Path
import sys
BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path: sys.path.insert(0, str(BASE))
from moonshot_card import generate_trade_card  # << usa seu gerador de card

BASE = pathlib.Path(__file__).resolve().parent.parent
env = os.environ.copy()
for line in (BASE/".env_moonshot").read_text().splitlines():
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1); env.setdefault(k.strip(), v.strip().strip("'").strip('"'))

TOKEN=env.get("TELEGRAM_BOT_TOKEN")
CHAT =env.get("TELEGRAM_TP_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")
TAG  =(env.get("TP_TAG") or "[TESTE]").strip()
EVERY=int(env.get("TP_WATCH_EVERY_SEC","10"))
TRF  =env.get("REPORT_TRADES_FILE") or "moonshot_trades.json"
TRADES = pathlib.Path(TRF) if pathlib.Path(TRF).is_absolute() else (BASE/TRF)
SET_STATUS = int(env.get("TP_SET_STATUS","1"))
SENT_FILE = pathlib.Path(os.path.expanduser(env.get("TPS_SENT_FILE") or "~/.moonshot_shared/tps_sent.json"))
TP_BG = env.get("TP_CARD_TEMPLATE", "assets/moonshot/bg_tp.jpg")
OUTDIR = pathlib.Path(env.get("CARD_OUT_DIR") or (BASE/"out"))
OUTDIR.mkdir(parents=True, exist_ok=True)

# lock de instância
lock=open(f"/tmp/tp_watcher_{BASE.name}.lock","w")
try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError: print("[tp] já existe outra instância; saindo.", flush=True); sys.exit(0)

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
def key(kjson, lvl, tp_val): return hashlib.sha1(f"{kjson}|TP{lvl}|{tp_val}".encode()).hexdigest()

def send_photo(path, caption):
    if not (TOKEN and CHAT): return False
    try:
        with open(path, "rb") as f:
            r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                            data={"chat_id":CHAT,"caption":caption},
                            files={"photo":("tp.png", f, "image/png")}, timeout=30)
        return r.ok
    except Exception: return False

def loop():
    print(f"[tp] watching {TRADES} every {EVERY}s | bg={TP_BG}", flush=True)
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
                if not sym or not side: continue
                entry=float(tr.get("entry_price") or tr.get("avg_entry") or tr.get("entry") or 0) or 0.0
                tps = tr.get("tp_levels") or tr.get("tps") or []
                if not tps: continue
                price=last_price(sym)
                for idx,tpv in enumerate(tps, start=1):
                    if tpv in (None,"",0): continue
                    tpv=float(tpv)
                    sent_key=key(k, idx, tpv)
                    flag=f"tp{idx}_sent"
                    if tr.get(flag) or sent_key in sent: 
                        continue
                    hit = (price is not None) and ((side=="LONG" and price>=tpv) or (side=="SHORT" and price<=tpv))
                    if hit:
                        delta=pnl_pct(side, entry, price)
                        caption=f"{TAG} 🟢 TP{idx} atingido — {sym} {tf} ({side})"
                        # gera card com o seu template
                        out = OUTDIR / f"tp{idx}_{sym}_{int(time.time())}.png"
                        try:
                            generate_trade_card(
                                symbol=sym, side=side, leverage=str(tr.get("lev") or tr.get("leverage") or ""),
                                tp_label=f"TP{idx}", roi_pct=delta,
                                entry_price=float(entry), last_price=float(price),
                                stop_text=str(tr.get("stop_loss") or tr.get("sl") or ""),
                                out_path=str(out), bg_path=TP_BG,
                            )
                            ok = send_photo(out, caption)
                        except Exception as e:
                            ok = False
                            print("[tp] erro card:", e, flush=True)
                        if not ok:
                            # fallback texto
                            try:
                                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                                              data={"chat_id":CHAT,"text":f"{caption}\nEntry {entry:g} → Price {price:g} (TP{idx} {tpv:g}) | ROI {delta:.2f}%"},
                                              timeout=10)
                            except Exception: pass
                        tr[flag]=True
                        if SET_STATUS and idx==len(tps): tr["status"]=f"CLOSED_TP{idx}"
                        sent.add(sent_key); changed=True
            if changed: atomic_write(TRADES, data); save_sent(sent)
        except Exception as e:
            print("[tp] erro:", e, flush=True)
        time.sleep(EVERY)

if __name__=="__main__": loop()
