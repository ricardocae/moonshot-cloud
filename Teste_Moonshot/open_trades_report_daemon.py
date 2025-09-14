#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envia relatório periódico de trades ABERTAS para o Telegram.

- Lê .env automaticamente (.env_moonshot ou .env)
- PERIODICIDADE: REPORT_EVERY_MIN (default 60)
- TTL: MOONSHOT_TRADE_MAX_AGE_H (default 96)
- Evita spam: REPORT_ONLY_IF_CHANGED=1 (hash do estado)
- Envia mesmo vazio? REPORT_SEND_WHEN_EMPTY=0/1 (default 0)
- Prefixo de tag: REPORT_TAG (ex.: [MOONSHOT])
- Arquivo de trades: REPORT_TRADES_FILE (default moonshot_trades.json)

One-shot: --once (apenas 1 envio e sai)
"""

import os, time, json, argparse, requests, datetime, hashlib
from pathlib import Path
from typing import Dict, Any, List

BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"
STALE_STATUSES = {"closed","stopped","tp3","done","expired","abort","aborted","invalid","cooldown","no_entry"}

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

def load_dotenv(path: Path) -> Dict[str,str]:
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

def resolve_env() -> Dict[str,str]:
    # prioridade: ambiente > .env_moonshot > .env
    env = dict(os.environ)
    env_file = None
    for c in (Path(".env_moonshot"), Path(".env")):
        if c.exists(): env_file = c; break
    if env_file:
        file_env = load_dotenv(env_file)
        for k,v in file_env.items():
            env.setdefault(k, v)
    return env

def get_symbol(tr): return (tr.get("symbol") or (tr.get("signal") or {}).get("symbol") or "").upper()
def get_side(tr):
    s = (tr.get("side") or tr.get("direction") or tr.get("type") or "").upper()
    if s.startswith("L"): return "LONG"
    if s.startswith("S"): return "SHORT"
    s2 = ((tr.get("signal") or {}).get("side") or "").upper()
    if s2.startswith("L"): return "LONG"
    if s2.startswith("S"): return "SHORT"
    return "LONG"
def get_entry(tr):
    for k in ("entry","entry_price","entryPrice","avg_entry","price"):
        v = tr.get(k)
        if v is not None: return parse_float(v)
    s = tr.get("signal") or {}
    for k in ("entry","entry_price","price"):
        v = s.get(k)
        if v is not None: return parse_float(v)
    return None
def get_stop(tr):
    for k in ("stop","sl","stop_loss","stopLoss"):
        v = tr.get(k)
        if v is not None: return parse_float(v)
    s = tr.get("signal") or {}
    for k in ("stop","sl","stop_loss"):
        v = s.get(k)
        if v is not None: return parse_float(v)
    return None
def get_tps(tr) -> Dict[str,float]:
    if isinstance(tr.get("tps"), dict):
        return {k: parse_float(tr["tps"].get(k)) for k in ("TP1","TP2","TP3")}
    if isinstance(tr.get("tps"), list):
        arr = tr["tps"]; return {"TP1": parse_float(arr[0]) if len(arr)>0 else None,
                                 "TP2": parse_float(arr[1]) if len(arr)>1 else None,
                                 "TP3": parse_float(arr[2]) if len(arr)>2 else None}
    return {"TP1": parse_float(tr.get("TP1") or tr.get("tp1")),
            "TP2": parse_float(tr.get("TP2") or tr.get("tp2")),
            "TP3": parse_float(tr.get("TP3") or tr.get("tp3"))}
def get_notified(tr) -> Dict[str,bool]:
    n = tr.get("notified") or {}
    return {"TP1": bool(n.get("TP1",False)), "TP2": bool(n.get("TP2",False)),
            "TP3": bool(n.get("TP3",False)), "STOP": bool(n.get("STOP",False))}
def get_created_dt(tr):
    created_ts = tr.get("created_at") or tr.get("created") or (tr.get("signal") or {}).get("dt")
    return as_utc(created_ts)

def detect_open(tr: Dict[str,Any], now: datetime.datetime, max_age_h: int) -> bool:
    if tr is None or not isinstance(tr, dict): return False
    if str(tr.get("closed","")).lower() in ("1","true","yes"): return False
    status = str(tr.get("status","")).lower()
    if status in STALE_STATUSES: return False
    if tr.get("closed_at") or tr.get("exit_at"): return False
    if tr.get("stop_hit") and tr.get("exit_price"): return False
    if tr.get("active") is False or tr.get("is_open") is False: return False
    exp = tr.get("expires_at")
    if exp:
        expdt = as_utc(exp)
        if expdt and now > expdt: return False
    if max_age_h and max_age_h > 0:
        created = get_created_dt(tr)
        if created and (now - created).total_seconds() > max_age_h*3600:
            return False
    return True

def fetch_last_price(symbol: str) -> float:
    params = {"category":"linear","symbol":symbol}
    r = requests.get(BYBIT_TICKER_URL, params=params, timeout=15)
    r.raise_for_status()
    js = r.json()
    lst = ((js.get("result") or {}).get("list") or [])
    if not lst: return None
    return parse_float(lst[0].get("lastPrice"))

def pnl_percent(side: str, entry: float, last: float) -> float:
    if not entry or not last: return None
    return ((last - entry)/entry*100.0) if side=="LONG" else ((entry - last)/entry*100.0)

def build_rows(trades_path: Path, max_age_h: int) -> List[Dict[str,Any]]:
    if not trades_path.exists(): return []
    data = json.loads(trades_path.read_text(encoding="utf-8"))
    now = datetime.datetime.utcnow()
    symbols = set()
    lst = []
    it = (data.items() if isinstance(data, dict) else enumerate(data))
    # 1) coletar símbolos
    for _, tr in it:
        if detect_open(tr, now, max_age_h):
            sym = get_symbol(tr)
            if sym: symbols.add(sym)
    # 2) preços
    price_cache = {}
    for sym in symbols:
        try:
            price_cache[sym] = fetch_last_price(sym); time.sleep(0.15)
        except Exception:
            price_cache[sym] = None
    # 3) montar linhas
    it2 = (data.items() if isinstance(data, dict) else enumerate(data))
    for _, tr in it2:
        if not detect_open(tr, now, max_age_h): continue
        symbol = get_symbol(tr); side = get_side(tr)
        entry = get_entry(tr); stop = get_stop(tr); tps = get_tps(tr)
        last = price_cache.get(symbol); pnl = pnl_percent(side, entry, last)
        n = get_notified(tr); created = get_created_dt(tr)
        lst.append({
            "symbol": symbol, "side": side, "entry": entry, "last": last,
            "pnl": None if pnl is None else round(pnl,2),
            "sl": stop, "tp1": (tps or {}).get("TP1"), "tp2": (tps or {}).get("TP2"), "tp3": (tps or {}).get("TP3"),
            "notified": n, "created": (None if not created else created.isoformat(timespec='seconds')),
        })
    # ordenar por PnL
    lst.sort(key=lambda r: (-9999 if r["pnl"] is None else r["pnl"]), reverse=True)
    return lst

def render_text(rows: List[Dict[str,Any]], tag: str="") -> str:
    if not rows:
        return f"{tag} 📉 Nenhuma trade aberta."
    lines = [f"{tag} 📈 Trades em aberto ({len(rows)}):"]
    for r in rows:
        lines.append(
            "• <b>{sym}</b> {side} | entry <code>{e}</code> → last <code>{l}</code> | "
            "<b>PnL {p}%</b> | SL <code>{sl}</code> | TP1 <code>{t1}</code> | TP2 <code>{t2}</code> | TP3 <code>{t3}</code> | "
            "N[{n1}{n2}{n3}{ns}]".format(
                sym=r["symbol"], side=r["side"],
                e="-" if r["entry"] is None else f"{r['entry']:.6f}",
                l="-" if r["last"]  is None else f"{r['last']:.6f}",
                p="-" if r["pnl"]   is None else f"{r['pnl']:.2f}",
                sl="-" if r["sl"]   is None else f"{r['sl']:.6f}",
                t1="-" if r["tp1"]  is None else f"{r['tp1']:.6f}",
                t2="-" if r["tp2"]  is None else f"{r['tp2']:.6f}",
                t3="-" if r["tp3"]  is None else f"{r['tp3']:.6f}",
                n1="1" if r["notified"].get("TP1") else "-",
                n2="2" if r["notified"].get("TP2") else "-",
                n3="3" if r["notified"].get("TP3") else "-",
                ns="S" if r["notified"].get("STOP") else "-",
            )
        )
    return "\n\n".join(lines)

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode":"HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code == 200: return True
        if r.status_code == 429:
            retry = (r.json().get("parameters", {}) or {}).get("retry_after", 15)
            time.sleep(int(retry)+1)
            r2 = requests.post(url, json=payload, timeout=20)
            return r2.status_code == 200
        print("[TELEGRAM ERROR]", r.status_code, r.text)
        return False
    except Exception as e:
        print("[TELEGRAM EXC]", repr(e))
        return False

def state_hash(rows: List[Dict[str,Any]]) -> str:
    # Hash só do essencial para detectar mudanças
    key_rows = []
    for r in rows:
        key_rows.append({
            "symbol": r["symbol"], "side": r["side"], "entry": r["entry"],
            "last": r["last"], "pnl": r["pnl"], "sl": r["sl"],
            "tp1": r["tp1"], "tp2": r["tp2"], "tp3": r["tp3"],
            "notified": r["notified"]
        })
    blob = json.dumps(key_rows, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Envia uma vez e sai")
    args = ap.parse_args()

    env = resolve_env()
    token = env.get("TELEGRAM_BOT_TOKEN","").strip()
    chat  = env.get("TELEGRAM_CHAT_ID","").strip()
    tag   = env.get("REPORT_TAG","").strip()
    base = Path(__file__).resolve().parent
    base = Path(__file__).resolve().parent
    trades_file = Path(env.get("REPORT_TRADES_FILE","moonshot_trades.json"))
    if not trades_file.is_absolute():
        trades_file = base / trades_file
    print(f"[daemon] usando trades: {trades_file}", flush=True)
    if not trades_file.is_absolute():
        trades_file = base / trades_file
    print(f"[daemon] usando trades: {trades_file}", flush=True)
    every_min = int(env.get("REPORT_EVERY_MIN","60"))
    ttl_h = int(env.get("MOONSHOT_TRADE_MAX_AGE_H","96"))
    only_if_changed = int(env.get("REPORT_ONLY_IF_CHANGED","1")) == 1
    send_when_empty = int(env.get("REPORT_SEND_WHEN_EMPTY","0")) == 1
    state_file = Path(env.get("REPORT_STATE_FILE",".open_trades_report_state.json"))

    if not token or not chat:
        print("[ERRO] Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (no .env_moonshot).")
        return

    def run_once():
        rows = build_rows(trades_file, ttl_h)
        if not rows and not send_when_empty:
            print("[INFO] Nenhuma trade aberta e REPORT_SEND_WHEN_EMPTY=0 — não enviando.")
            return None
        txt = render_text(rows, tag=tag)
        if only_if_changed:
            h = state_hash(rows)
            prev = state_file.exists() and state_file.read_text(encoding="utf-8") or ""
            if h == prev:
                print("[INFO] Estado não mudou — não enviando.")
                return h
            ok = send_telegram(token, chat, txt)
            if ok:
                state_file.write_text(h, encoding="utf-8")
            return h
        else:
            send_telegram(token, chat, txt)
            return None

    if args.once:
        run_once()
        return

    print(f"[daemon] Report a cada {every_min}min | TTL={ttl_h}h | trades={trades_file} | tag='{tag}'")
    while True:
        try:
            run_once()
        except Exception as e:
            print("[LOOP EXC]", repr(e))
        # dorme até o próximo ciclo
        time.sleep(max(30, every_min*60))

if __name__ == "__main__":
    main()
