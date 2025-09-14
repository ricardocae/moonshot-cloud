import os
# diag_quase_rompimentos.py
# Uso:
#   - Salve este arquivo na pasta do projeto (mesma pasta do moonshot_agent.py)
#   - Rode:  python3 diag_quase_rompimentos.py | tee near_breaks.txt

import yaml, math, importlib

# importa funções do seu projeto (precisa rodar na pasta do Moonshot)
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
    # Só calcula SHORT se:
    # 1) existir a função no seu moonshot_agent
    # 2) enable_shorts estiver True no YAML
    if getattr(M, "explain_breakout_short", None) and cfg.get("enable_shorts", True):
        return M.explain_breakout_short(df, cfg)
    return None

def main():
    cfg = _load_cfg()
    syms = M.load_json(cfg.get("symbols_cache_file","moonshot_symbols.json"), [])
    if not syms:
        syms = M.discover_perp_symbols(cfg)

    rows = []
    for sym in syms:
        if sym == "BTCUSDT":
            continue
        for tf in cfg["timeframes"]:
            df = M.fetch_klines(sym, interval=tf, limit=200, category=cfg.get("category","linear"))
            if df is None or len(df) < (cfg["breakout_lookback"] + 5):
                continue

            exL = M.explain_breakout_long(df, cfg)
            exS = _maybe_short(df, cfg)

            atr = exL["atr"] or 0.0
            if atr <= 0:
                continue

            triggerL = exL["resistance"] + exL["buf"]
            gapL = (triggerL - exL["close"]) / atr

            if exS:
                atrS = exS["atr"] or atr
                triggerS = exS["support"] - exS["buf"]
                gapS = (exS["close"] - triggerS) / atrS
            else:
                triggerS = math.inf
                gapS = math.inf

            # Escolhe o lado mais "ativo" (|gap| menor)
            cand = [("LONG", gapL, exL, triggerL)]
            if exS:
                cand.append(("SHORT", gapS, exS, triggerS))
            side, gap, ex, trig = sorted(cand, key=lambda x: abs(x[1]))[0]

            rows.append({
                "sym": sym, "tf": tf, "side": side,
                "gap_atr": round(gap, 3),
                "reason": _reason(ex),
                "close": round(ex["close"], 8),
                "trigger": round(trig, 8),
                "rsi": round(ex["rsi"], 2),
                "ema_ok": ex["cond_ema"],
                "vol_ok": ex["cond_vol"],
                "body_ok": ex["cond_body"],
            })

    rows = sorted(rows, key=lambda r: abs(r["gap_atr"]))[:20]
    print("Top 20 quase-rompimentos (|gap ATR| menor primeiro):")
    for r in rows:
        print(f"{r['sym']:12} {r['tf']:>2}m {r['side']:5} gap={r['gap_atr']:>5} ATR  "
              f"reason={r['reason']:>8}  close={r['close']}  trigger={r['trigger']}  "
              f"RSI={r['rsi']}  EMA={r['ema_ok']}  VOL={r['vol_ok']}  BODY={r['body_ok']}")

if __name__ == "__main__":
    main()
