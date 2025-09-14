import os
# surgical_fix_quality_block.py
from pathlib import Path
import re, time, py_compile

p = Path("moonshot_agent.py")
bak = p.with_suffix(p.suffix + f".surgical.{int(time.time())}.bak")
bak.write_bytes(p.read_bytes())
print(f"[backup] {bak.name}")

src = p.read_text(encoding="utf-8")

# âncora onde o patch foi inserido
anchor = "[QUALITY_PATCH] regime filters"
i = src.find(anchor)
if i < 0:
    raise SystemExit("Âncora '[QUALITY_PATCH] regime filters' não encontrada. Abortando para evitar dano.")

# Encontrar o fim do bloco atual (antes de calcular explain_breakout* ou do próximo marcador)
# Vamos procurar a primeira ocorrência relevante após a âncora:
candidates = []
for pat in (
    r"\[QUALITY_PATCH\] align signal",               # nosso próximo bloco
    r"explain_breakout_long_at\(",                   # primeiro uso
    r"explain_breakout_short_at\(",
    r"\nbest\s*=",
):
    m = re.search(pat, src[i:], flags=re.DOTALL)
    if m:
        candidates.append(i + m.start())

if not candidates:
    # se não encontrou, corta um tamanho máximo de janela (seguro)
    j = i + 600
else:
    j = min(candidates)

head = src[:i]
tail = src[j:]  # vamos reconstruir o miolo

CANON = """
        # [QUALITY_PATCH] regime filters (ATR%%, ADX, HTF)

        # 0) Garantir DF suficiente ANTES de tudo
        if df is None or len(df) < (int(cfg.get("breakout_lookback", 20)) + 5):
            if log_each: print(f"[rej] {sym:12} {tf}m (DF insuficiente)")
            continue

        # 1) ATR%% mínimo no TF (evita chop)
        try:
            atr_len = int(cfg.get("atr_len", 14))
            pc = df["close"].shift(1)
            # True Range e ATR (EMA)
            tr = (df["high"] - df["low"]).combine((df["high"] - pc).abs(), max).combine((df["low"] - pc).abs(), max)
            atr_series = tr.ewm(alpha=1/atr_len, adjust=False).mean()
            atr_abs = float(atr_series.iloc[-2])
            price   = float(df["close"].iloc[-2])
            atr_pct = (atr_abs / max(price, 1e-12)) * 100.0
            min_atr_pct = float(cfg.get("min_atr_pct_trade_15m", 0.0)) if str(tf) == "15" else 0.0
            if atr_pct < min_atr_pct:
                if log_each: print(f"[rej] {sym:12} {tf}m (atr% {atr_pct:.2f} < {min_atr_pct})")
                continue
        except Exception:
            pass

        # 2) ADX (força de tendência)
        if cfg.get("adx_filter", {}).get("enabled", False):
            try:
                pdi, mdi, adxv = dmi_adx(df, int(cfg.get("adx_filter", {}).get("len", 14)))
                adx_last = float(adxv.iloc[-2])
                side_bias_adx = "LONG" if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else "SHORT"
                if adx_last < float(cfg["adx_filter"]["min_adx"]):
                    if log_each: print(f"[rej] {sym:12} {tf}m (ADX {adx_last:.1f} < {cfg['adx_filter']['min_adx']})")
                    continue
            except Exception:
                # se der erro em série/índice, não quebra o loop
                continue

        # 3) Confirmação pela TF maior
        if cfg.get("htf_confirm", {}).get("enabled", False):
            try:
                htf_tf = str(cfg["htf_confirm"]["tf"])
                df_htf = get_df(sym, htf_tf)
                # direção pela EMA curta/longa (def htf_direction já adicionada no módulo)
                bias = htf_direction(df_htf,
                                     int(cfg["htf_confirm"]["ema_short"]),
                                     int(cfg["htf_confirm"]["ema_long"]))
                if not cfg["htf_confirm"].get("allow_neutral", False) and bias == "NEUTRAL":
                    if log_each: print(f"[rej] {sym:12} {tf}m (HTF {htf_tf} bias NEUTRAL)")
                    continue
            except Exception:
                # se não conseguir obter DF do HTF, rejeitamos por segurança
                if log_each: print(f"[rej] {sym:12} {tf}m (HTF erro)")
                continue
""".rstrip("\n")

new_src = head + anchor + CANON + "\n" + tail
p.write_text(new_src, encoding="utf-8")

# valida sintaxe
py_compile.compile(str(p), doraise=True)
print("[ok] Sintaxe OK após o reparo cirúrgico.")
