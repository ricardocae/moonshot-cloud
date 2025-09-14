import os
import yaml, sys
from moonshot_agent import fetch_klines, explain_breakout, passes_liquidity, fetch_tickers_map

if len(sys.argv) < 3:
    print("Uso: python3 moonshot_diag.py SYMBOL TF_MIN  (ex.: python3 moonshot_diag.py TAUSDT 5)")
    raise SystemExit(1)

sym = sys.argv[1].upper()
tf = sys.argv[2]
cfg = yaml.safe_load(open("moonshot_config.yaml"))

tick_map = fetch_tickers_map(category=cfg.get("category","linear"))
liq = passes_liquidity(sym, cfg, ticker_map=tick_map)
print(f"[LIQ] {sym}: {liq}")
if not liq:
    t = tick_map.get(sym)
    turn = float(t.get("turnover24h","0")) if t else 0.0
    print(f"turnover24h={turn}")
    raise SystemExit(0)

df = fetch_klines(sym, interval=tf, limit=200, category=cfg.get("category","linear"))
if df is None or len(df) < (cfg["breakout_lookback"] + 5):
    print("Dados insuficientes para análise.")
    raise SystemExit(0)

from moonshot_agent import explain_breakout
ex = explain_breakout(df, cfg)
print("ok=", ex["ok"])
print(f"break={ex['cond_break']} (close={ex['close']} res={ex['resistance']} buf={ex['buf']})")
print(f"vol={ex['cond_vol']} (vol={ex['vol']} vs {ex['vol_ma']*ex['vol_mult']})")
print(f"ema={ex['cond_ema']} (ema9={ex['ema_s']} ema20={ex['ema_l']} slope={ex['slope_s']})")
print(f"rsi={ex['cond_rsi']} ({ex['rsi']} vs {ex['rsi_min']})")
print(f"entry={ex['entry']} sl={ex['sl']} tps={ex['tps']} atr={ex['atr']}")
