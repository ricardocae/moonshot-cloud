import os
# apply_quality_patch.py
from __future__ import annotations
import re, sys, time, json, os
from pathlib import Path

YAML_PATH = Path("moonshot_config.yaml")
AGENT_PATH = Path("moonshot_agent.py")

BACKUP_SUFFIX = f".bak.{int(time.time())}"

YAML_BLOCK = """
# === quality filters (auto-added) ===
htf_confirm:
  enabled: true
  tf: "60"
  ema_short: 50
  ema_long: 200
  allow_neutral: false

adx_filter:
  enabled: true
  len: 14
  min_adx: 18

min_atr_pct_trade_15m: 0.35
breakout_buffer_atr: 0.22
vol_spike_min_mult: 1.25
"""

FUNC_DMI_ADX = r"""
# [QUALITY_PATCH] DMI/ADX
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
"""

FUNC_HTF_DIR = r"""
# [QUALITY_PATCH] HTF direction by EMAs
def htf_direction(df, ema_s_len: int, ema_l_len: int) -> str:
    import pandas as pd
    from math import isnan
    es = df["close"].ewm(span=ema_s_len, adjust=False).mean()
    el = df["close"].ewm(span=ema_l_len, adjust=False).mean()
    if len(df) < max(ema_s_len, ema_l_len) + 2:
        return "NEUTRAL"
    up = (es.iloc[-1] > el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] > 0)
    down = (es.iloc[-1] < el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] < 0)
    return "LONG" if up else ("SHORT" if down else "NEUTRAL")
"""

BLOCK_FILTERS = r"""
        # [QUALITY_PATCH] regime filters (ATR%, ADX, HTF)
        try:
            atr_len = int(cfg.get("atr_len", 14))
            atr_abs = (df["high"].combine(df["low"], max) - df["low"]).rolling(1).max()  # placeholder to ensure df
            # real ATR:
            pc = df["close"].shift(1)
            tr = (df["high"] - df["low"]).combine((df["high"] - pc).abs(), max).combine((df["low"] - pc).abs(), max)
            atr_abs = tr.ewm(alpha=1/atr_len, adjust=False).mean()
            price = float(df["close"].iloc[-2])
            atr_pct = float(atr_abs.iloc[-2] / max(price, 1e-12) * 100.0)
            min_atr_pct = float(cfg.get("min_atr_pct_trade_15m", 0.0)) if str(tf) == "15" else 0.0
            if atr_pct < min_atr_pct:
                if log_each: print(f"[rej] {sym:12} {tf}m (atr% {atr_pct:.2f} < {min_atr_pct})")
                continue
        except Exception:
            pass

        if cfg.get("adx_filter", {}).get("enabled", False):
            pdi, mdi, adxv = dmi_adx(df, int(cfg.get("adx_filter", {}).get("len", 14)))
            adx_last = float(adxv.iloc[-2])
            side_bias_adx = "LONG" if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else "SHORT"
            if adx_last < float(cfg["adx_filter"]["min_adx"]):
                if log_each: print(f"[rej] {sym:12} {tf}m (ADX {adx_last:.1f} < {cfg['adx_filter']['min_adx']})")
                continue

        if cfg.get("htf_confirm", {}).get("enabled", False):
            htf_tf = str(cfg["htf_confirm"]["tf"])
            df_htf = get_df(sym, htf_tf)
            bias = htf_direction(df_htf,
                                 int(cfg["htf_confirm"]["ema_short"]),
                                 int(cfg["htf_confirm"]["ema_long"]))
            if not cfg["htf_confirm"].get("allow_neutral", False) and bias == "NEUTRAL":
                if log_each: print(f"[rej] {sym:12} {tf}m (HTF {htf_tf} bias NEUTRAL)")
                continue
"""

BLOCK_ALIGN = r"""
        # [QUALITY_PATCH] align signal with regime filters
        ok_dir = True
        try:
            if cfg.get("adx_filter", {}).get("enabled", False):
                desired = "LONG" if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else "SHORT"
                ok_dir &= (best and best.get("side") == desired)
            if cfg.get("htf_confirm", {}).get("enabled", False):
                ok_dir &= (best and (bias == "NEUTRAL" or best.get("side") == bias))
        except Exception:
            pass
        if best is None or not ok_dir:
            continue
"""

def file_backup(p: Path):
    if p.exists():
        pb = p.with_suffix(p.suffix + BACKUP_SUFFIX)
        pb.write_bytes(p.read_bytes())
        return str(pb)
    return None

def patch_yaml():
    if not YAML_PATH.exists():
        print(f"[YAML] arquivo não encontrado: {YAML_PATH}")
        return
    text = YAML_PATH.read_text(encoding="utf-8")
    if "htf_confirm:" in text or "adx_filter:" in text or "min_atr_pct_trade_15m" in text:
        print("[YAML] já contém blocos de quality – pulando.")
        return
    file_backup(YAML_PATH)
    YAML_PATH.write_text(text.rstrip() + "\n\n" + YAML_BLOCK.strip() + "\n", encoding="utf-8")
    print("[YAML] quality filters adicionados.")

def insert_after(patterns, snippet, text):
    for pat in patterns:
        m = re.search(pat, text, flags=re.DOTALL)
        if m:
            idx = m.end()
            return text[:idx] + "\n" + snippet.strip() + "\n" + text[idx:], True
    return text, False

def patch_agent():
    if not AGENT_PATH.exists():
        print(f"[AGENT] arquivo não encontrado: {AGENT_PATH}")
        return
    src = AGENT_PATH.read_text(encoding="utf-8")

    # a) adicionar funções dmi_adx / htf_direction
    if "def dmi_adx(" not in src:
        src, ok = insert_after([r"\ndef\s+ema\(", r"import pandas as pd.*?\n"], FUNC_DMI_ADX, src)
        print("[AGENT] add dmi_adx:", "OK" if ok else "FALLBACK")
        if not ok:
            src = src + "\n" + FUNC_DMI_ADX
    else:
        print("[AGENT] dmi_adx já existe.")

    if "def htf_direction(" not in src:
        src = src + "\n" + FUNC_HTF_DIR
        print("[AGENT] add htf_direction: OK")
    else:
        print("[AGENT] htf_direction já existe.")

    # b) inserir blocos no loop de avaliação
    if "[QUALITY_PATCH] regime filters" not in src:
        # tentar ancorar após linha: df = get_df(sym, tf)
        pat = r"\n\s*df\s*=\s*get_df\(\s*sym\s*,\s*tf\s*\).*?\n"
        src, ok = insert_after([pat], BLOCK_FILTERS, src)
        print("[AGENT] filtros de regime:", "OK" if ok else "MANUAL")
    else:
        print("[AGENT] filtros já presentes.")

    if "[QUALITY_PATCH] align signal" not in src:
        # ancorar antes do primeiro "if best is None"
        m = re.search(r"\n\s*if\s+best\s+is\s+None\s*:", src)
        if m:
            idx = m.start()
            src = src[:idx] + "\n" + BLOCK_ALIGN.strip() + "\n" + src[idx:]
            print("[AGENT] alinhamento direcional: OK")
        else:
            print("[AGENT] alinhamento: ANCORAGEM NÃO ENCONTRADA (faça manual se necessário).")

    file_backup(AGENT_PATH)
    AGENT_PATH.write_text(src, encoding="utf-8")
    print("[AGENT] patch salvo.")

if __name__ == "__main__":
    patch_yaml()
    patch_agent()
    print("\nDone.")
