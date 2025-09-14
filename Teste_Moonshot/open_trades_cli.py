#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, json, time, math, argparse, requests, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"

def parse_float(x, default=None):
    try:
        if x is None: return default
        return float(x)
    except Exception:
        return default

def as_utc(ts):
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12: ts = ts/1000.0
            return datetime.datetime.utcfromtimestamp(ts)
        if isinstance(ts, str) and ts.isdigit():
            t = int(ts)
            if t > 1e12: t = t/1000.0
            return datetime.datetime.utcfromtimestamp(t)
        return datetime.datetime.fromisoformat(str(ts).replace("Z","+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def load_env_file(path: Path) -> Dict[str,str]:
    env = {}
    if not path.exists(): return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("export "): line = line[len("export "):].strip()
        if "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def detect_open(tr: Dict[str,Any]) -> bool:
    if tr is None or not isinstance(tr, dict): return False
    if str(tr.get("closed", "")).lower() in ("1","true","yes"): return False
    if str(tr.get("status","")).lower() in ("closed","stopped","stp","tp3","done"): return False
    if tr.get("closed_at") or tr.get("exit_at"): return False
    if tr.get("stop_hit") and tr.get("exit_price"): return False
    return True

def get_entry(tr):
    for k in ("entry","entry_price","entryPrice","avg_entry","price"):
        v = tr.get(k)
        if v is not None: return parse_float(v)
    sig = tr.get("signal") or {}
    for k in ("entry","entry_price","price"):
        v = sig.get(k)
        if v is not None: return parse_float(v)
    return None

def get_stop(tr):
    for k in ("stop","sl","stop_loss","stopLoss"):
        v = tr.get(k)
        if v is not None: return parse_float(v)
    sig = tr.get("signal") or {}
    for k in ("stop","sl","stop_loss"):
        v = sig.get(k)
        if v is not None: return parse_float(v)
    return None

def get_side(tr):
    s = (tr.get("side") or tr.get("direction") or tr.get("type") or "").upper()
    if s.startswith("L"): return "LONG"
    if s.startswith("S"): return "SHORT"
    s2 = ((tr.get("signal") or {}).get("side") or "").upper()
    if s2.startswith("L"): return "LONG"
    if s2.startswith("S"): return "SHORT"
    return "LONG"

def get_symbol(tr):
    return (tr.get("symbol") or (tr.get("signal") or {}).get("symbol") or "").upper()

def get_leverage(tr):
    for k in ("leverage","lev","levx"):
        v = tr.get(k)
        if v is not None: return str(v)
    return ""

def get_qty(tr):
    for k in ("qty","quantity","size","amount","contracts"):
        v = tr.get(k)
        if v is not None: return parse_float(v)
    return None

def get_tps(tr) -> Dict[str,float]:
    if isinstance(tr.get("tps"), dict):
        out = {}
        for k in ("TP1","TP2","TP3"):
            out[k] = parse_float(tr["tps"].get(k))
        return out
    if isinstance(tr.get("tps"), list):
        arr = tr["tps"]
        return {
            "TP1": parse_float(arr[0]) if len(arr)>0 else None,
            "TP2": parse_float(arr[1]) if len(arr)>1 else None,
            "TP3": parse_float(arr[2]) if len(arr)>2 else None,
        }
    out = {
        "TP1": parse_float(tr.get("TP1") or tr.get("tp1")),
        "TP2": parse_float(tr.get("TP2") or tr.get("tp2")),
        "TP3": parse_float(tr.get("TP3") or tr.get("tp3")),
    }
    return out

def get_notified(tr) -> Dict[str,bool]:
    n = tr.get("notified") or {}
    return {
        "TP1": bool(n.get("TP1", False)),
        "TP2": bool(n.get("TP2", False)),
        "TP3": bool(n.get("TP3", False)),
        "STOP": bool(n.get("STOP", False)),
    }

def human_dt(ts):
    if not ts: return "-"
    try:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

def age_hms(dt: datetime.datetime):
    if not dt: return "-"
    delta = datetime.datetime.utcnow() - dt
    s = int(delta.total_seconds())
    h = s//3600; s = s%3600
    m = s//60; s=s%60
    return f"{h:02d}h{m:02d}m"

def fetch_last_price(symbol: str) -> float:
    params = {"category":"linear", "symbol": symbol}
    r = requests.get(BYBIT_TICKER_URL, params=params, timeout=15)
    r.raise_for_status()
    js = r.json()
    lst = ((js.get("result") or {}).get("list") or [])
    if not lst: return None
    return parse_float(lst[0].get("lastPrice"))

def pnl_percent(side: str, entry: float, last: float) -> float:
    if not entry or not last: return None
    if side == "LONG":
        return (last - entry) / entry * 100.0
    else:
        return (entry - last) / entry * 100.0

def progress_to(target: float, entry: float, last: float, side: str):
    if not target or not entry or not last: return None
    if side == "LONG":
        span = target - entry
        if span <= 0: return None
        done = last - entry
    else:
        span = entry - target
        if span <= 0: return None
        done = entry - last
    return max(0.0, done / span * 100.0)

def compute_R(entry: float, stop: float, target: float, side: str):
    if not entry or not stop or not target: return None
    risk = (entry - stop) if side=="LONG" else (stop - entry)
    reward = (target - entry) if side=="LONG" else (entry - target)
    if risk <= 0: return None
    return reward / risk

def print_table(rows: List[Dict[str,Any]]):
    if not rows:
        print("Sem trades em aberto.")
        return
    cols = ["Symbol","Side","Lev","Entry","Last","PnL%","SL","TP1","TP2","TP3","Prog1","Prog2","Prog3","R1","R2","R3","Notified","Desde","Criada"]
    widths = {c: len(c) for c in cols}
    def s(x): return "-" if x is None else str(x)
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(s(r.get(c))))
    line = " | ".join(c.ljust(widths[c]) for c in cols)
    sep  = "-+-".join("-"*widths[c] for c in cols)
    print(line)
    print(sep)
    for r in rows:
        print(" | ".join(s(r.get(c)).ljust(widths[c]) for c in cols))

def write_html(rows: List[Dict[str,Any]], path: Path):
    html = []
    html.append("<html><head><meta charset='utf-8'><title>Open Trades</title>")
    html.append("<style>body{font-family:Arial,Helvetica,sans-serif} table{border-collapse:collapse;width:100%} th,td{border:1px solid #ddd;padding:8px;font-size:14px} th{background:#111;color:#fff;text-align:left} tr:hover{background:#f6f6f6}</style>")
    html.append("</head><body><h2>Trades em aberto</h2><table>")
    cols = ["Symbol","Side","Lev","Entry","Last","PnL%","SL","TP1","TP2","TP3","Prog1","Prog2","Prog3","R1","R2","R3","Notified","Desde","Criada"]
    html.append("<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>")
    def esc(x):
        x = "-" if x is None else str(x)
        return x.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    for r in rows:
        html.append("<tr>" + "".join(f"<td>{esc(r.get(c))}</td>" for c in cols) + "</tr>")
    html.append("</table></body></html>")
    path.write_text("\n".join(html), encoding="utf-8")
    print(f"[OK] HTML salvo em: {path}")

def send_telegram_summary(rows: List[Dict[str,Any]], env: Dict[str,str]):
    token = env.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat  = env.get("TELEGRAM_CHAT_ID")   or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[TELEGRAM] Sem TELEGRAM_BOT_TOKEN/CHAT_ID.")
        return
    if not rows:
        text = "📉 Nenhuma trade aberta."
    else:
        lines = ["📈 Trades em aberto:"]
        for r in rows:
            lines.append(f"• <b>{r['Symbol']}</b> {r['Side']} lev {r['Lev']} | entry {r['Entry']} → last {r['Last']} | <b>PnL {r['PnL%']}%</b> | SL {r['SL']} | TP1 {r['TP1']} | TP2 {r['TP2']} | TP3 {r['TP3']} | Notif {r['Notified']} | {r['Desde']}")
        text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        print("[TELEGRAM]", r.status_code, r.text[:200])
    except Exception as e:
        print("[TELEGRAM EXC]", repr(e))

def main():
    ap = argparse.ArgumentParser(description="Listar trades em aberto (detalhe)")
    ap.add_argument("--trades-file", default="moonshot_trades.json", help="Caminho do JSON de trades")
    ap.add_argument("--html", help="Salvar HTML em arquivo (ex.: open_trades.html)")
    ap.add_argument("--telegram", action="store_true", help="Enviar resumo no Telegram (usa .env_moonshot se existir)")
    ap.add_argument("--env-file", help="Caminho .env para Telegram (padrão: .env_moonshot, fallback .env)")
    args = ap.parse_args()

    trades_path = Path(args.trades_file)
    if not trades_path.exists():
        print(f"[ERRO] Não achei {trades_path}")
        return

    data = json.loads(trades_path.read_text(encoding="utf-8"))
    rows = []
    env_local = {}

    envfile = Path(args.env_file) if args.env_file else None
    if envfile is None:
        for c in (Path(".env_moonshot"), Path(".env")):
            if c.exists():
                envfile = c
                break
    if envfile and envfile.exists():
        env_local = load_env_file(envfile)

    symbols = set()

    for key, tr in (data.items() if isinstance(data, dict) else enumerate(data)):
        if not detect_open(tr):
            continue
        symbol = get_symbol(tr)
        if not symbol:
            continue
        symbols.add(symbol)

    price_cache = {}
    for sym in symbols:
        try:
            price_cache[sym] = fetch_last_price(sym)
            time.sleep(0.15)
        except Exception:
            price_cache[sym] = None

    for key, tr in (data.items() if isinstance(data, dict) else enumerate(data)):
        if not detect_open(tr):
            continue
        symbol = get_symbol(tr)
        if not symbol:
            continue
        side   = get_side(tr)
        lev    = get_leverage(tr)
        entry  = get_entry(tr)
        stop   = get_stop(tr)
        tps    = get_tps(tr)
        last   = price_cache.get(symbol)
        pnl    = pnl_percent(side, entry, last)
        p1     = progress_to((tps or {}).get("TP1"), entry, last, side) if tps else None
        p2     = progress_to((tps or {}).get("TP2"), entry, last, side) if tps else None
        p3     = progress_to((tps or {}).get("TP3"), entry, last, side) if tps else None
        r1     = compute_R(entry, stop, (tps or {}).get("TP1"), side) if tps else None
        r2     = compute_R(entry, stop, (tps or {}).get("TP2"), side) if tps else None
        r3     = compute_R(entry, stop, (tps or {}).get("TP3"), side) if tps else None
        noti   = get_notified(tr)
        created_ts = tr.get("created_at") or tr.get("created") or (tr.get("signal") or {}).get("dt")
        created = as_utc(created_ts)
        rows.append({
            "Symbol": symbol,
            "Side": side,
            "Lev": lev or "-",
            "Entry": f"{entry:.6f}" if entry else "-",
            "Last": f"{last:.6f}" if last else "-",
            "PnL%": f"{pnl:.2f}" if pnl is not None else "-",
            "SL": f"{stop:.6f}" if stop else "-",
            "TP1": f"{(tps or {}).get('TP1'):.6f}" if (tps or {}).get('TP1') else "-",
            "TP2": f"{(tps or {}).get('TP2'):.6f}" if (tps or {}).get('TP2') else "-",
            "TP3": f"{(tps or {}).get('TP3'):.6f}" if (tps or {}).get('TP3') else "-",
            "Prog1": f"{p1:.0f}%" if p1 is not None else "-",
            "Prog2": f"{p2:.0f}%" if p2 is not None else "-",
            "Prog3": f"{p3:.0f}%" if p3 is not None else "-",
            "R1": f"{r1:.2f}" if r1 is not None else "-",
            "R2": f"{r2:.2f}" if r2 is not None else "-",
            "R3": f"{r3:.2f}" if r3 is not None else "-",
            "Notified": f"1:{int(noti['TP1'])} 2:{int(noti['TP2'])} 3:{int(noti['TP3'])} S:{int(noti['STOP'])}",
            "Desde": age_hms(created),
            "Criada": human_dt(created),
        })

    rows.sort(key=lambda r: (r["PnL%"]=="-" and -9999) or float(r["PnL%"]), reverse=True)
    print_table(rows)

    if args.html:
        write_html(rows, Path(args.html))

    if args.telegram:
        send_telegram_summary(rows, env_local)

if __name__ == "__main__":
    main()
