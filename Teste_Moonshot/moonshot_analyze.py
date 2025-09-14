import os
# moonshot_analyze.py
from __future__ import annotations
import json, yaml, math, statistics as st
from collections import defaultdict, Counter
from datetime import datetime, timezone

CFG_PATH = "moonshot_config.yaml"
TRADES_PATH = "moonshot_trades.json"

def load_json(p, default):
    try:
        return json.load(open(p, "r", encoding="utf-8"))
    except Exception:
        return default

def pct(x): return f"{x*100:.1f}%"

def main():
    cfg = yaml.safe_load(open(CFG_PATH, "r", encoding="utf-8"))
    trades = load_json(TRADES_PATH, {})
    if not trades:
        print("Sem trades no arquivo.")
        return

    rows = []
    for k,t in trades.items():
        sym = t.get("symbol"); tf = str(t.get("tf") or t.get("timeframe") or "")
        side = t.get("side")
        status = (t.get("status") or "").upper()
        roi = float(t.get("roi_est", 0.0)) if "roi_est" in t else float(t.get("roi", 0.0))
        open_ts = t.get("created_at") or t.get("opened_at")
        close_ts = t.get("closed_at"); reason = t.get("exit_reason","")
        rows.append((sym, tf, side, status, roi, reason, open_ts, close_ts))

    # win/lose por TF/side
    buckets = defaultdict(list)
    for sym,tf,side,status,roi,reason,op,cl in rows:
        if tf == "": continue
        key = (tf, side or "?")
        win = 1 if status in ("CLOSED_TP3","CLOSED_TP2","CLOSED_TP1") or ("TP" in reason) else (0 if "STOP" in (status+reason) else None)
        if win is not None:
            buckets[key].append((win, roi))

    print("=== Winrate por TF/Side ===")
    for key, vals in sorted(buckets.items(), key=lambda x: (int(x[0][0]), x[0][1])):
        wins = sum(v for v,_ in vals); n = len(vals)
        rois = [r for _,r in vals]
        print(f"{key}: n={n} | winrate={pct(wins/n)} | ROI mediana={st.median(rois):.3f} | p25={st.quantiles(rois,n=4)[0]:.3f} p75={st.quantiles(rois,n=4)[-1]:.3f}")

    # sugestão de thresholds
    print("\n=== Sugestões de filtros ===")
    print("- Se winrate < 50% no 15m, experimente subir ADX mínimo para 20–22.")
    print("- Se muitos 'no_break', aumentar breakout_buffer_atr (ex.: 0.25).")
    print("- Se muito STOP pelo chop, aumente min_atr_pct_trade_15m (0.50).")

    # top símbolos/pares
    sym_stats = defaultdict(lambda: [0,0,0.0])  # n, wins, roi_sum
    for sym,tf,side,status,roi,reason,op,cl in rows:
        win = 1 if "TP" in (status+reason) else 0 if "STOP" in (status+reason) else None
        if win is None: continue
        sym_stats[sym][0]+=1; sym_stats[sym][1]+=win; sym_stats[sym][2]+=roi
    best = sorted(((s,v[1]/v[0], v[0]) for s,v in sym_stats.items() if v[0]>=5), key=lambda x: (-x[1], -x[2]))[:10]
    if best:
        print("\nTop símbolos (n≥5):")
        for s,wr,n in best:
            print(f" - {s}: winrate={pct(wr)} (n={n})")

if __name__ == "__main__":
    main()
