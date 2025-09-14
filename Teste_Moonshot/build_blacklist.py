#!/usr/bin/env python3
# build_blacklist.py — gera blacklist para o #moonshot
# Regras padrão:
#  - baixa liquidez (turnover 24h < --min-turnover)
#  - amostra mínima (--min-trades)
#  - taxa de STOP >= --stop-rate OU winrate TP3 <= --max-tp3-win
#  - PnL líquido <= --max-netpnl (em USDT, aproximado via roi_pct*notional/100)

import os, json, math, argparse, statistics as st
from datetime import datetime, timezone, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yaml

BYBIT = "https://api.bybit.com"

def _session():
    s = requests.Session()
    r = Retry(total=2, connect=2, read=2, backoff_factor=0.5,
              status_forcelist=[429,500,502,503,504],
              allowed_methods=["GET","POST"])
    s.mount("https://", HTTPAdapter(max_retries=r))
    s.headers.update({"User-Agent":"MoonshotBlacklist/1.0"})
    return s

S = _session()

def safe_get(url, params=None, timeout=12):
    try:
        r = S.get(url, params=params, timeout=timeout); r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print("[net]", e)
        return None

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path,"r",encoding="utf-8") as f: return json.load(f)
        except Exception: pass
    return default

def load_cfg(path="moonshot_config.yaml"):
    with open(path,"r",encoding="utf-8") as f: return yaml.safe_load(f)

def fetch_tickers_map(category="linear"):
    data = safe_get(f"{BYBIT}/v5/market/tickers", {"category":category})
    lst = (data or {}).get("result", {}).get("list", []) or []
    out = {}
    for it in lst:
        sym = it.get("symbol"); 
        if not sym: continue
        try:
            t24 = float(it.get("turnover24h","0"))
            lp  = float(it.get("lastPrice","0"))
        except Exception:
            t24, lp = 0.0, 0.0
        out[sym] = {"turnover24h": t24, "lastPrice": lp}
    return out

def est_pnl_usdt(t):
    """aproxima PnL do trade usando roi_pct*notional/100, se existir."""
    roi = float(t.get("roi_pct", 0.0))
    notion = float(t.get("notional", 0.0))
    return (roi/100.0) * notion

def within_days(ts_str, days):
    if not ts_str: return True
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        return dt >= (datetime.now(timezone.utc) - timedelta(days=days))
    except Exception:
        return True

def build(args):
    cfg = load_cfg(args.config)
    trades = load_json(cfg.get("trades_file","moonshot_trades.json"), {})
    tick = fetch_tickers_map(cfg.get("category","linear"))

    # agrega por símbolo (fechados nos últimos X dias)
    agg = {}
    for key, tr in trades.items():
        if tr.get("status") not in ("CLOSED_TP3","STOP"): 
            continue
        if args.days and not within_days(tr.get("closed_at") or tr.get("created_at"), args.days):
            continue

        sym = tr.get("symbol")
        a = agg.setdefault(sym, {"closed":0,"stops":0,"tp3":0,"tp1_hits":0,"pnl":0.0})

        a["closed"] += 1
        if tr["status"] == "STOP": a["stops"] += 1
        if tr["status"] == "CLOSED_TP3": a["tp3"] += 1
        if any(u.get("event")=="TP1" for u in tr.get("updates",[])): a["tp1_hits"] += 1
        a["pnl"] += est_pnl_usdt(tr)

    # decide blacklist
    bl = []
    rows = []
    for sym, a in agg.items():
        closed = a["closed"]
        stops  = a["stops"]
        tp3    = a["tp3"]
        pnl    = round(a["pnl"], 2)
        stop_rate = (stops/closed) if closed>0 else 0.0
        tp3_win   = (tp3/closed) if closed>0 else 0.0

        tinfo = tick.get(sym, {})
        t24 = float(tinfo.get("turnover24h", 0.0))

        reason = []
        if t24 < args.min_turnover: reason.append(f"low_liq({int(t24)})")
        if closed >= args.min_trades and stop_rate >= args.stop_rate: reason.append(f"stop_rate={stop_rate:.2f}")
        if closed >= args.min_trades and tp3_win <= args.max_tp3_win: reason.append(f"tp3_win={tp3_win:.2f}")
        if closed >= args.min_trades and pnl <= args.max_netpnl: reason.append(f"netPnL={pnl:.2f}")

        if reason:
            bl.append(sym)

        rows.append({
            "symbol": sym, "closed": closed, "stops": stops, "tp3": tp3,
            "stop_rate": round(stop_rate,3), "tp3_win": round(tp3_win,3),
            "pnl": pnl, "turnover24h": int(t24), "flag": ",".join(reason)
        })

    # ordena por flags > stop_rate > closed
    rows.sort(key=lambda r: (r["flag"]=="", -r["stop_rate"], -r["closed"]))

    # salva
    out_path = args.output
    with open(out_path,"w",encoding="utf-8") as f:
        json.dump(sorted(list(set(bl))), f, indent=2)
    print(f"\nBlacklist salva em: {out_path}  (total={len(set(bl))})\n")

    # tabela (resumo)
    print(" symbol        closed  stops  tp3  stop%   tp3%   PnL($)  turnover24h  flags")
    for r in rows:
        print(f" {r['symbol']:<12} {r['closed']:>6} {r['stops']:>6} {r['tp3']:>4}  "
              f"{r['stop_rate']:.2f}  {r['tp3_win']:.2f}  {r['pnl']:>7.2f}  {r['turnover24h']:>11}  {r['flag']}")

    # YAML para colar no config
    if bl:
        print("\n--- Cole no seu moonshot_config.yaml ---")
        print("denylist:")
        for s in sorted(set(bl)):
            print(f"  - {s}")
    else:
        print("\nNenhum símbolo marcado nas regras atuais.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Gera blacklist para o Moonshot")
    ap.add_argument("--config", default="moonshot_config.yaml")
    ap.add_argument("--output", default="moonshot_blacklist.json")
    ap.add_argument("--days", type=int, default=14, help="janela de análise (dias)")
    ap.add_argument("--min-trades", type=int, default=6, help="mínimo de trades fechados por símbolo")
    ap.add_argument("--stop-rate", type=float, default=0.65, help="marca se stop_rate >= X")
    ap.add_argument("--max-tp3-win", type=float, default=0.15, help="marca se winrate TP3 <= X")
    ap.add_argument("--max-netpnl", type=float, default=-10.0, help="marca se PnL líquido <= X (USDT)")
    ap.add_argument("--min-turnover", type=float, default=1_000_000, help="mínimo de turnover 24h (USDT)")
    build(ap.parse_args())
