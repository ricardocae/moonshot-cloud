import os, json, pathlib, requests

BASE = pathlib.Path(__file__).resolve().parent.parent

# env (.env_moonshot)
env = os.environ.copy()
env_file = BASE / ".env_moonshot"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: 
            continue
        k,v = line.split("=",1)
        env.setdefault(k.strip(), v.strip().strip("'").strip('"'))

TAG     = (env.get("REPORT_TAG") or "").strip()
TOKEN   = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT")
CHAT_ID = env.get("TELEGRAM_CHAT_ID")

trades_file = env.get("REPORT_TRADES_FILE") or "moonshot_trades.json"
trades_path = pathlib.Path(trades_file)
if not trades_path.is_absolute():
    trades_path = BASE / trades_file

def is_open_like(status:str) -> bool:
    if not status: return False
    s = str(status).upper().strip()
    if s in {"STOP","STOPPED","CANCEL","CANCELED","CANCELLED"}: return False
    if s.startswith("CLOSED"): return False
    # segue aberto: OPEN/OPEN_*, TP1/TP2, BREAKEVEN, PARTIAL/REDUCE, TRAIL...
    return s.startswith("OPEN") or s.startswith("TP") or "BREAKEVEN" in s or "PARTIAL" in s or "REDUCE" in s or "TRAIL" in s

def bybit_last(symbol:str):
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers",
                         params={"category":"linear","symbol":symbol}, timeout=10)
        j = r.json()
        lst = (j.get("result") or {}).get("list") or []
        if lst:
            return float(lst[0]["lastPrice"])
    except Exception:
        pass
    return None

def pnl_pct(side, entry, price):
    if not entry or not price: return 0.0
    return (price/entry-1.0)*100.0 if (side or "").upper() == "LONG" else (1.0 - price/entry)*100.0

data = {}
if trades_path.exists() and trades_path.stat().st_size > 0:
    data = json.loads(trades_path.read_text())

open_items = [(k,v) for k,v in data.items() if isinstance(v,dict) and is_open_like(v.get("status"))]

# monta linhas
lines = []
for k,t in sorted(open_items, key=lambda kv: (kv[1].get("symbol",""), str(kv[1].get("tf","")))):
    sym   = (t.get("symbol") or "").upper()
    side  = (t.get("side") or "").upper()
    entry = t.get("entry_price") or t.get("avg_entry") or t.get("entry") or 0
    entry = float(entry) if entry not in (None,"",0) else 0.0
    last  = bybit_last(sym) or entry
    pnl   = pnl_pct(side, entry, last)

    tps = t.get("tp_levels") or t.get("tps") or []
    tp1 = tps[0] if len(tps)>=1 else "-"
    tp2 = tps[1] if len(tps)>=2 else "-"
    tp3 = tps[2] if len(tps)>=3 else "-"
    sl  = t.get("stop_loss") or t.get("sl") or "-"

    lines.append(f"• {sym} {side} | entry {entry:g} → last {last:g} | PnL {pnl:.2f}% | SL {sl} | TP1 {tp1} | TP2 {tp2} | TP3 {tp3} | N[----]")

header = f"{(TAG+' ') if TAG else ''}📈 Trades em aberto ({len(open_items)}):"
msg = header + ("\n\n" + "\n".join(lines) if lines else "\n\n(nenhuma)")

print(msg)

if TOKEN and CHAT_ID:
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
    except Exception:
        pass
