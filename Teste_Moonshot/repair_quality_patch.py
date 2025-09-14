import os
# repair_quality_patch.py
from __future__ import annotations
from pathlib import Path
import re, time

AGENT = Path("moonshot_agent.py")
bak = AGENT.with_suffix(AGENT.suffix + f".fixbak.{int(time.time())}")
AGENT.write_bytes(AGENT.read_bytes())  # só pra falhar cedo se não existir
bak.write_bytes(AGENT.read_bytes())

src = AGENT.read_text(encoding="utf-8")

# 1) Remover blocos quebrados inseridos pelo patch (entre os marcadores [QUALITY_PATCH])
# Remove DMI/ADX
src = re.sub(
    r"\n# \[QUALITY_PATCH\] DMI/ADX.*?(?=\n# \[QUALITY_PATCH\]|^\s*def\s)",
    "\n",
    src,
    flags=re.DOTALL | re.MULTILINE,
)
# Remove HTF direction
src = re.sub(
    r"\n# \[QUALITY_PATCH\] HTF direction.*?(?=\n# \[QUALITY_PATCH\]|^\s*def\s)",
    "\n",
    src,
    flags=re.DOTALL | re.MULTILINE,
)

# Também remove quaisquer definições avulsas duplicadas que ficaram sobrando
src = re.sub(r"\n\s*def\s+dmi_adx\s*\(.*?\)\s*:\s*.*?return\s+plus_di,\s*minus_di,\s*adx\s*\n",
             "\n", src, flags=re.DOTALL)
src = re.sub(r"\n\s*def\s+htf_direction\s*\(.*?\)\s*:\s*.*?(?:\n(?=def)|\Z)",
             "\n", src, flags=re.DOTALL)

# 2) Inserir versões corretas no nível de módulo (no final do arquivo é suficiente)
CANON = r"""
# [QUALITY_PATCH] DMI/ADX (canon)
def dmi_adx(df, n: int = 14):
    import pandas as pd
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    pdm = plus_dm.ewm(alpha=1/n, adjust=False).mean()
    mdm = minus_dm.ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100 * (pdm / atr)
    minus_di = 100 * (mdm / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx = dx.ewm(alpha=1/n, adjust=False).mean()
    return plus_di, minus_di, adx

# [QUALITY_PATCH] HTF direction (canon)
def htf_direction(df, ema_s_len: int, ema_l_len: int) -> str:
    es = df["close"].ewm(span=ema_s_len, adjust=False).mean()
    el = df["close"].ewm(span=ema_l_len, adjust=False).mean()
    if len(df) < max(ema_s_len, ema_l_len) + 2:
        return "NEUTRAL"
    up = (es.iloc[-1] > el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] > 0)
    down = (es.iloc[-1] < el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] < 0)
    return "LONG" if up else ("SHORT" if down else "NEUTRAL")
"""
src = src.rstrip() + "\n\n" + CANON.strip() + "\n"

AGENT.write_text(src, encoding="utf-8")
print(f"[backup] {bak}")

# 3) Checar sintaxe
import py_compile
try:
    py_compile.compile(str(AGENT), doraise=True)
    print("[ok] Sintaxe compilou sem erros.")
except Exception as e:
    print("[erro] Ainda há problema de sintaxe:", e)
    print("Arquivo de backup salvo em:", bak)
