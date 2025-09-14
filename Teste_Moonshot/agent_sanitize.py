import os
# agent_sanitize.py
from pathlib import Path
import re, time, py_compile

AGENT = Path("moonshot_agent.py")
bak = AGENT.with_suffix(AGENT.suffix + f".sanitize.{int(time.time())}.bak")
bak.write_bytes(AGENT.read_bytes())
print(f"[backup] {bak.name}")

def normalize_text(p: Path):
    txt = p.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n")
    if "\t" in txt:
        txt = txt.replace("\t","    ")
    p.write_text(txt, encoding="utf-8")

def ensure_helpers(src: str) -> str:
    parts = []
    if "def dmi_adx(" not in src:
        parts.append("""
# [QUALITY_PATCH] DMI/ADX helper
def dmi_adx(df, n: int = 14):
    import pandas as pd
    h, l, c = df['high'], df['low'], df['close']
    up = h.diff(); dn = -l.diff()
    plus_dm  = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    pdm = plus_dm.ewm(alpha=1/n, adjust=False).mean()
    mdm = minus_dm.ewm(alpha=1/n, adjust=False).mean()
    plus_di  = 100 * (pdm / atr)
    minus_di = 100 * (mdm / atr)
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx = dx.ewm(alpha=1/n, adjust=False).mean()
    return plus_di, minus_di, adx
""")
    if "def htf_direction(" not in src:
        parts.append("""
# [QUALITY_PATCH] HTF direction helper
def htf_direction(df, ema_s_len: int, ema_l_len: int) -> str:
    es = df['close'].ewm(span=ema_s_len, adjust=False).mean()
    el = df['close'].ewm(span=ema_l_len, adjust=False).mean()
    if len(df) < max(ema_s_len, ema_l_len) + 2:
        return 'NEUTRAL'
    up   = (es.iloc[-1] > el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] > 0)
    down = (es.iloc[-1] < el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] < 0)
    return 'LONG' if up else ('SHORT' if down else 'NEUTRAL')
""")
    if parts:
        src = src.rstrip() + "\n\n" + "\n".join(s.strip("\n") for s in parts) + "\n"
    return src

def canonical_quality_block():
    return (
        "        # [QUALITY_PATCH] regime filters (ATR%, ADX, HTF)\n"
        "        # 0) DF suficiente?\n"
        "        if df is None or len(df) < (int(cfg.get('breakout_lookback', 20)) + 5):\n"
        "            if log_each: print(f\"[rej] {sym:12} {tf}m (DF insuficiente)\")\n"
        "            continue\n"
        "        # 1) ATR% mínimo no TF\n"
        "        try:\n"
        "            atr_len = int(cfg.get('atr_len', 14))\n"
        "            pc = df['close'].shift(1)\n"
        "            tr = (df['high'] - df['low']).combine((df['high'] - pc).abs(), max).combine((df['low'] - pc).abs(), max)\n"
        "            atr_series = tr.ewm(alpha=1/atr_len, adjust=False).mean()\n"
        "            atr_abs = float(atr_series.iloc[-2])\n"
        "            price   = float(df['close'].iloc[-2])\n"
        "            atr_pct = (atr_abs / max(price, 1e-12)) * 100.0\n"
        "            min_atr_pct = float(cfg.get('min_atr_pct_trade_15m', 0.0)) if str(tf) == '15' else 0.0\n"
        "            if atr_pct < min_atr_pct:\n"
        "                if log_each: print(f\"[rej] {sym:12} {tf}m (atr% {atr_pct:.2f} < {min_atr_pct})\")\n"
        "                continue\n"
        "        except Exception:\n"
        "            pass\n"
        "        # 2) ADX\n"
        "        if cfg.get('adx_filter', {}).get('enabled', False):\n"
        "            try:\n"
        "                pdi, mdi, adxv = dmi_adx(df, int(cfg.get('adx_filter', {}).get('len', 14)))\n"
        "                adx_last = float(adxv.iloc[-2])\n"
        "                side_bias_adx = 'LONG' if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else 'SHORT'\n"
        "                if adx_last < float(cfg['adx_filter']['min_adx']):\n"
        "                    if log_each: print(f\"[rej] {sym:12} {tf}m (ADX {adx_last:.1f} < {cfg['adx_filter']['min_adx']})\")\n"
        "                    continue\n"
        "            except Exception:\n"
        "                continue\n"
        "        # 3) Confirmação HTF\n"
        "        if cfg.get('htf_confirm', {}).get('enabled', False):\n"
        "            try:\n"
        "                htf_tf = str(cfg['htf_confirm']['tf'])\n"
        "                df_htf = get_df(sym, htf_tf)\n"
        "                bias = htf_direction(df_htf, int(cfg['htf_confirm']['ema_short']), int(cfg['htf_confirm']['ema_long']))\n"
        "                if not cfg['htf_confirm'].get('allow_neutral', False) and bias == 'NEUTRAL':\n"
        "                    if log_each: print(f\"[rej] {sym:12} {tf}m (HTF {htf_tf} bias NEUTRAL)\")\n"
        "                    continue\n"
        "            except Exception:\n"
        "                if log_each: print(f\"[rej] {sym:12} {tf}m (HTF erro)\")\n"
        "                continue\n"
    )

def canonical_align_block():
    return (
        "        # [QUALITY_PATCH] align signal with regime filters\n"
        "        ok_dir = True\n"
        "        try:\n"
        "            if cfg.get('adx_filter', {}).get('enabled', False):\n"
        "                desired = 'LONG' if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else 'SHORT'\n"
        "                ok_dir &= (best and best.get('side') == desired)\n"
        "            if cfg.get('htf_confirm', {}).get('enabled', False):\n"
        "                ok_dir &= (best and (bias == 'NEUTRAL' or best.get('side') == bias))\n"
        "        except Exception:\n"
        "            pass\n"
        "        if best is None or not ok_dir:\n"
        "            continue\n"
    )

def sanitize():
    normalize_text(AGENT)
    src = AGENT.read_text(encoding="utf-8")
    src = ensure_helpers(src)

    # Remover qualquer bloco antigo quebrado entre o marcador e o próximo ponto lógico
    if "[QUALITY_PATCH] regime filters" in src:
        s = src.find("[QUALITY_PATCH] regime filters")
        # achar fim: próximo marcador/uso
        ends = []
        for pat in ("[QUALITY_PATCH] align signal", "explain_breakout_long_at(", "explain_breakout_short_at(", "\n        best"):
            i = src.find(pat, s+1)
            if i != -1: ends.append(i)
        e = min(ends) if ends else s
        src = src[:s] + src[e:]

    # Inserir bloco canônico logo após a primeira linha com df = get_df(
    anchor = "df = get_df("
    k = src.find(anchor)
    if k != -1:
        ins_at = src.find("\n", k) + 1
        src = src[:ins_at] + canonical_quality_block() + src[ins_at:]

    # Remover/evitar duplicação do bloco de alinhamento e inserir versão canônica antes de "if best is None"
    if "[QUALITY_PATCH] align signal" in src:
        a = src.find("[QUALITY_PATCH] align signal")
        b = src.find("\n        if best is None", a+1)
        if b != -1:
            src = src[:a] + src[b:]
    pos_best = src.find("\n        if best is None")
    if pos_best != -1:
        src = src[:pos_best] + canonical_align_block() + src[pos_best:]

    # Garantir que todo try tenha um except/finally no mesmo nível
    lines = src.splitlines(True)
    def indent(s): return len(s) - len(s.lstrip(" "))
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("try:"):
            lv = indent(lines[i])
            j = i + 1
            found = False
            while j < len(lines):
                if lines[j].strip() and indent(lines[j]) <= lv and not lines[j].lstrip().startswith(("#",)):
                    break
                if lines[j].lstrip().startswith(("except", "finally")) and indent(lines[j]) == lv:
                    found = True; break
                j += 1
            if not found:
                pad = " " * lv
                lines.insert(j, pad + "except Exception:\n")
                lines.insert(j+1, pad + "    pass\n")
                i = j + 2
            else:
                i = j + 1
        else:
            i += 1

    AGENT.write_text("".join(lines), encoding="utf-8")
    py_compile.compile(str(AGENT), doraise=True)
    print("[ok] moonshot_agent.py: sintaxe OK.")

if __name__ == "__main__":
    sanitize()
