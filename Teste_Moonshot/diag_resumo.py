import os
# diag_resumo.py
# Uso:
#   - Salve este arquivo na pasta do projeto (mesma pasta do moonshot_agent.py)
#   - Rode:  python3 diag_resumo.py | tee rej_resumo.txt

import yaml, importlib
from collections import Counter, defaultdict

M = importlib.import_module("moonshot_agent")

def _load_cfg():
    with open("moonshot_config.yaml", "r") as f:
        return yaml.safe_load(f)

def _reason(ex):
    if not ex["cond_break"]: return "no_break"
    if not ex["cond_vol"]:   return "no_vol"
    if not ex["cond_ema"]:   return "no_ema"
    if not ex["cond_rsi"]:   return "no_rsi"
    if not ex["cond_body"]:  return "no_body"
    return "ok"

def _maybe_short(df, cfg):
    if getattr(M, "explain_breakout_short", None) and cfg.get("enable_shorts", True):
        return M.explain_breakout_short(df, cfg)
    return None

def main():
    cfg = _load_cfg()
    syms = M.load_json(cfg.get("symbols_cache_file","moonshot_symbols.json"), [])
    if not syms:
        syms = M.discover_perp_symbols(cfg)

    counts = {"LONG": Counter(), "SHORT": Counter()}
    examples = defaultdict(list)

    for sym in syms:
        if sym == "BTCUSDT":
            continue
        for tf in cfg["timeframes"]:
            df = M.fetch_klines(sym, interval=tf, limit=200, category=cfg.get("category","linear"))
            if df is None or len(df) < (cfg["breakout_lookback"] + 5):
                continue

            # LONG
            exL = M.explain_breakout_long(df, cfg)
            rL = _reason(exL)
            counts["LONG"][rL] += 1
            if len(examples[("LONG", rL)]) < 3:
                examples[("LONG", rL)].append(sym + f" {tf}m")

            # SHORT
            exS = _maybe_short(df, cfg)
            if exS:
                rS = _reason(exS)
                counts["SHORT"][rS] += 1
                if len(examples[("SHORT", rS)]) < 3:
                    examples[("SHORT", rS)].append(sym + f" {tf}m")

    print("Resumo de rejeições por lado (LONG/SHORT):")
    for side in ("LONG", "SHORT"):
        print(f"\n== {side} ==")
        for k in ("no_break","no_vol","no_ema","no_rsi","no_body","ok"):
            v = counts[side][k]
            if v:
                ex = ", ".join(examples[(side,k)]) if examples[(side,k)] else "-"
                print(f"{k:8}: {v:5}  ex: {ex}")

if __name__ == "__main__":
    main()
