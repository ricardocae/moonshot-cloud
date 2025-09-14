import os, json, pathlib, requests

BASE = pathlib.Path(__file__).resolve().parent.parent

# ==== carregar .env_moonshot ====
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

primary = env.get("REPORT_TRADES_FILE") or "moonshot_trades.json"
extras  = env.get("EXTRA_TRADES_FILES","").replace(";",",")
extra_list = [x.strip() for x in extras.split(",") if x.strip()]

def abspath(p):
    P = pathlib.Path(p)
    return P if P.is_absolute() else (BASE / P)

FILES = []
for fp in [primary] + extra_list:
    P = abspath(fp)
    if P.exists():
        FILES.append(P)

def src_tag(fp: pathlib.Path) -> str:
    s = str(fp)
    if "Moonshot_agresivo" in s: return "Agresivo"
    if s.rstrip("/").endswith("/Moonshot/moonshot_trades.json"): return "Moonshot"
    if s.rstrip("/").endswith("/Teste_Moonshot/moonshot_trades.json"): return "Teste"
    parts = pathlib.Path(s).parts
    return parts[-2] if len(parts) >= 2 else parts[-1]

def is_open_like(status: str) -> bool:
    if not status: return False
    s = str(status).upper().strip()
    if s in {"STOP","STOPPED","CANCEL","CANCELED","CANCELLED"}: return False
    if s.startswith("CLOSED"): return False
    return s.startswith("OPEN") or s.startswith("TP") or "BREAKEVEN" in s or "PARTIAL" in s or "REDUCE" in s or "TRAIL" in s

def bybit_last(symbol: str):
    try:
        r = requests.get("https://api.bybit.com/v5/market/tickers",
                         params={"category":"linear","symbol":symbol}, timeout=10)
        j = r.json()
        lst = (j.get("result") or {}).get("list") or []
        if lst: return float(lst[0]["lastPrice"])
    except Exception:
        pass
    return None

def pnl_pct(side, entry, price):
    if not entry or not price: return 0.0
    return (price/entry-1.0)*100.0 if (side or "").upper()=="LONG" else (1.0-price/entry)*100.0

def rank_status(s: str) -> int:
    s = (s or "").upper()
    if s.startswith("OPEN"): return 5
    if "TP2" in s: return 4
    if "TP1" in s: return 3
    if "BREAKEVEN" in s or "TRAIL" in s: return 2
    if "PARTIAL" in s or "REDUCE" in s: return 1
    return 0

# ==== agrega por (symbol, tf) escolhendo o status "mais aberto" ====
agg = {}
for fp in FILES:
    try:
        data = json.loads(fp.read_text() or "{}")
    except Exception:
        continue
    source = src_tag(fp)
    for k,t in (data.items() if isinstance(data, dict) else []):
        if not isinstance(t, dict): continue
        if not is_open_like(t.get("status")): continue
        sym = (t.get("symbol") or "").upper()
        tf  = str(t.get("tf") or t.get("timeframe") or "")
        key = (sym, tf)
        prev = agg.get(key)
        if (prev is None) or (rank_status(t.get("status")) > rank_status(prev.get("status",""))) \
           or ((t.get("opened_at") or "") > (prev.get("opened_at") or "")):
            t2 = dict(t)
            t2["_source"] = source
            agg[key] = t2

# ==== monta mensagem ====
lines = []
for (sym, tf), t in sorted(agg.items()):
    side  = (t.get("side") or "").upper()
    entry = t.get("entry_price") or t.get("avg_entry") or t.get("entry") or 0
    entry = float(entry) if entry not in (None,"",0) else 0.0
    last  = bybit_last(sym) or entry
    pnl   = pnl_pct(side, entry, last)
    tps   = t.get("tp_levels") or t.get("tps") or []
    tp1   = tps[0] if len(tps)>=1 else "-"
    tp2   = tps[1] if len(tps)>=2 else "-"
    tp3   = tps[2] if len(tps)>=3 else "-"
    sl    = t.get("stop_loss") or t.get("sl") or "-"
    src   = f" [{t.get('_source')}]" if t.get("_source") else ""
    tf2   = f" {tf}" if tf else ""
    lines.append(f"• {sym}{tf2} {side}{src} | entry {entry:g} → last {last:g} | PnL {pnl:.2f}% | SL {sl} | TP1 {tp1} | TP2 {tp2} | TP3 {tp3} | N[----]")

header = f"{(TAG+' ') if TAG else ''}📈 Trades em aberto (agregado) ({len(agg)}):"
msg = header + ("\n\n" + "\n".join(lines) if lines else "\n\n(nenhuma)")

print(msg)
if TOKEN and CHAT_ID:
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
    except Exception:
        pass
