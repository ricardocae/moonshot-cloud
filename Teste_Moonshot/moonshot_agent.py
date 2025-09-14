# moonshot_agent.py — #moonshot com:
# - LONG/SHORT breakout + marubozu + volume + EMA + RSI
# - Pré-sinal (gap ATR baixo)
# - BACKSCAN (últimas N velas fechadas)
# - Fuso configurável (America/Sao_Paulo por padrão)
# - Formatação de preços por símbolo (tickSize da Bybit)
# - Blacklist automática (AutoBlacklist): filtro em discovery + ban por candles/strikes

import os
import time
import json
import math
import traceback
from datetime import datetime
from telegram_send import send_tp_card
from collections import Counter
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import yaml
import pandas as pd

BYBIT = "https://api.bybit.com"

# === AutoBlacklist ===
from moonshot_blacklist import AutoBlacklist

# ==============================
# Rede resiliente
# ==============================

def _mk_session():
    s = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "MoonshotBot/1.0"})
    return s


SESSION = _mk_session()


def safe_get_json(url, params=None, timeout=12):
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[net] {e.__class__.__name__} on {url.replace('https://','')} — {e}")
        return None
    except Exception as e:
        print(f"[net] unexpected on {url}: {e}")
        return None


def safe_post_json(url, json_payload=None, timeout=12):
    try:
        r = SESSION.post(url, json=json_payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"[net] {e.__class__.__name__} on {url.replace('https://','')} — {e}")
        return None
    except Exception as e:
        print(f"[net] unexpected on {url}: {e}")
        return None


# ==============================
# Config & util
# ==============================

def load_cfg(path: str = "moonshot_config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def dbg(cfg, msg):
    if cfg.get("debug", False):
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}][debug] {msg}")


def bmark(x: bool) -> str:
    return "✓" if bool(x) else "✗"


def to_local_str(ts_utc: pd.Timestamp, cfg: dict) -> str:
    try:
        tz = ZoneInfo(cfg.get("display_timezone", "America/Sao_Paulo"))
    except Exception:
        tz = ZoneInfo("UTC")
    dt = ts_utc.to_pydatetime().astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M %Z")


# ==============================
# Bybit REST helpers
# ==============================

def fetch_klines(symbol, interval="15", limit=200, category="linear"):
    data = safe_get_json(
        f"{BYBIT}/v5/market/kline",
        {"category": category, "symbol": symbol, "interval": str(interval), "limit": int(limit)},
    )
    if not data:
        return None
    lst = (data.get("result") or {}).get("list", []) or []
    if not lst:
        return None
    cols = ["start", "open", "high", "low", "close", "volume", "turnover"]
    df = pd.DataFrame(lst, columns=cols)
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["dt"] = pd.to_datetime(df["start"], unit="ms", utc=True)
    df = df.sort_values("dt").reset_index(drop=True)
    return df


def fetch_ticker(symbol, category="linear"):
    data = safe_get_json(f"{BYBIT}/v5/market/tickers", {"category": category, "symbol": symbol})
    lst = (data or {}).get("result", {}).get("list", []) or []
    return lst[0] if lst else None


def fetch_tickers_map(category="linear"):
    data = safe_get_json(f"{BYBIT}/v5/market/tickers", {"category": category})
    lst = (data or {}).get("result", {}).get("list", []) or []
    return {it.get("symbol"): it for it in lst if it.get("symbol")}


def fetch_instruments_page(category="linear", cursor=None):
    params = {"category": category}
    if cursor:
        params["cursor"] = cursor
    data = safe_get_json(f"{BYBIT}/v5/market/instruments-info", params)
    if not data:
        return [], None
    res = data.get("result", {}) or {}
    return res.get("list", []) or [], res.get("nextPageCursor")


def discover_perp_symbols(cfg):
    # categoria e quote desejada
    cat = cfg.get("category", "linear")
    want_q = (cfg.get("quote_coin") or "").upper().strip()

    # listas estática e dinâmica (normalizadas em UPPER)
    deny = set(s.upper().strip() for s in cfg.get("denylist", []))
    dyn_path = cfg.get("blacklist_file")
    if dyn_path and os.path.exists(dyn_path):
        try:
            deny |= set(s.upper().strip() for s in load_json(dyn_path, []))
        except Exception:
            pass

    allow = set(s.upper().strip() for s in cfg.get("allowlist", []))

    # AutoBlacklist para filtrar na descoberta
    bl_cfg = (cfg.get("blacklist") or {})
    abl = AutoBlacklist(
        path=bl_cfg.get("file", cfg.get("blacklist_file", "moonshot_blacklist.json")),
        rules=bl_cfg.get("rules", {}),
        hard_denylist=(bl_cfg.get("hard_denylist") or cfg.get("denylist") or []),
        enabled=bl_cfg.get("enabled", True),
    )
    abl.cleanup()

    if cfg.get("debug", False):
        print(
            f"[symbols] denylist total={len(deny)} (static={len(cfg.get('denylist',[]))}, "
            f"dyn={'ok' if dyn_path and os.path.exists(dyn_path) else 'none'})"
        )

    out, cursor = [], None
    while True:
        page, cursor = fetch_instruments_page(cat, cursor)
        if not page:
            break
        for it in page:
            sym = (it.get("symbol") or "").upper().strip()
            if not sym or it.get("status") != "Trading":
                continue
            if "Perpetual" not in (it.get("contractType", "") or ""):
                continue

            q = (it.get("quoteCoin") or it.get("quoteCurrency") or "").upper()
            if want_q and q != want_q:
                continue

            if allow and sym not in allow:
                continue

            if cfg.get("exclude_100000", True) and sym.startswith("100000"):
                continue
            if sym in deny:
                continue

            blocked, why = abl.is_blocked(sym)
            if blocked:
                if cfg.get("debug", False):
                    print(f"[symbols] skip {sym} (blacklisted: {why})")
                continue

            out.append(sym)

        if not cursor:
            break

    return sorted(set(out))


def last_price(symbol, category="linear"):
    t = fetch_ticker(symbol, category=category)
    if not t:
        return None
    try:
        return float(t.get("lastPrice"))
    except Exception:
        return None


# ==============================
# Metadados de preço (tickSize) e formatação
# ==============================

def _decimals_from_tick_str(tick_str: str) -> int:
    if "." in tick_str:
        return len(tick_str.split(".")[1].rstrip("0"))
    return 0


def build_symbol_meta_map(cfg) -> dict:
    cat = cfg.get("category", "linear")
    meta = {}
    cursor = None
    while True:
        page, cursor = fetch_instruments_page(cat, cursor)
        if not page:
            break
        for it in page:
            sym = it.get("symbol")
            pf = it.get("priceFilter") or {}
            tick_str = str(pf.get("tickSize") or "0.0001")
            try:
                tick = float(tick_str)
            except Exception:
                tick = 0.0001
            dp = _decimals_from_tick_str(tick_str)

            lf = it.get("leverageFilter") or {}
            try:
                maxLev = float(lf.get("maxLeverage", 25))
            except Exception:
                maxLev = 25.0

            meta[sym] = {"tick": tick, "dp": dp, "maxLev": maxLev}
        if not cursor:
            break
    return meta


def round_to_tick(x: float, tick: float) -> float:
    d = Decimal(str(x))
    t = Decimal(str(tick))
    n = (d / t).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return float(n * t)


def recommend_leverage(entry: float, sl: float, default_lev: float = 10.0, safety_mult: float = 0.85) -> float:
    gap_frac = abs(entry - sl) / max(entry, 1e-12)
    if gap_frac <= 0:
        return max(1.0, default_lev)
    lev_max_safe = (1.0 / gap_frac) * float(safety_mult)
    return max(1.0, min(default_lev, lev_max_safe))


def fmt_px(symbol: str, x: float, meta_map: dict, cfg: dict) -> str:
    m = meta_map.get(symbol)
    if not m:
        dp = int(cfg.get("default_price_decimals", 6))
        return f"{round(float(x), dp):.{dp}f}"
    val = round_to_tick(float(x), float(m["tick"]))
    return f"{val:.{int(m['dp'])}f}"


def fmt_pair_prices(symbol: str, sig: dict, meta_map: dict, cfg: dict) -> dict:
    ez_lo = fmt_px(symbol, sig["entry_zone"][0], meta_map, cfg)
    ez_hi = fmt_px(symbol, sig["entry_zone"][1], meta_map, cfg)
    sl = fmt_px(symbol, sig["sl"], meta_map, cfg)
    tps = [fmt_px(symbol, p, meta_map, cfg) for p in sig["tps"]]
    entry = fmt_px(symbol, sig["entry_price"], meta_map, cfg)
    return {"ez_lo": ez_lo, "ez_hi": ez_hi, "sl": sl, "tps": tps, "entry": entry}


# ==============================
# Indicadores
# ==============================

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0.0)
    down = -d.clip(upper=0.0)
    rs = up.rolling(n).mean() / down.rolling(n).mean()
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    df["ema_s"] = ema(df["close"], int(cfg["ema_short"]))
    df["ema_l"] = ema(df["close"], int(cfg["ema_long"]))
    df["rsi"] = rsi(df["close"], int(cfg["rsi_len"]))
    df["atr"] = atr(df, int(cfg["atr_len"]))
    df["vol_ma"] = df["volume"].rolling(int(cfg["vol_ma_len"])).mean()
    return df


# ==============================
# Setups LONG/SHORT (índice parametrizado)
# ==============================

def _body_wicks(o, h, l, c):
    rng = max(h - l, 1e-12)
    body = abs(c - o)
    up = h - max(o, c)
    lo = min(o, c) - l
    return rng, body / rng, up / rng, lo / rng


def explain_breakout_long_at(df, cfg, idx: int = -2):
    df = add_indicators(df, cfg)
    last = df.iloc[idx]
    lb = int(cfg["breakout_lookback"]) 
    end = df.index.get_loc(last.name)
    start = max(0, end - lb)
    window = df.iloc[start:end]
    resistance = float(window["high"].max())

    o, h, l, c = map(float, (last["open"], last["high"], last["low"], last["close"]))
    atrv = float(last["atr"]) 
    _, body, upw, loww = _body_wicks(o, h, l, c)

    buf = float(cfg["breakout_buffer_atr"]) * atrv
    cond_break = c > (resistance + buf)
    cond_vol = float(last["volume"]) >= float(last["vol_ma"] * cfg["vol_spike_min_mult"]) 
    slope = float(df["ema_s"].iloc[end] - df["ema_s"].iloc[end - 1]) if end - 1 >= 0 else 0.0
    cond_ema = (last["ema_s"] > last["ema_l"]) and (slope > 0)
    cond_rsi = float(last["rsi"]) >= float(cfg["rsi_min_long"]) 
    body_req = float(cfg.get("body_min_frac", 0.6))
    wick_req = float(cfg.get("wick_max_frac", 0.2))
    cond_body = (c > o) and (body >= body_req) and (upw <= wick_req) and (loww <= wick_req)

    ok = bool(cond_break and cond_vol and cond_ema and cond_rsi and cond_body)
    entry = c
    sl = float(entry - float(cfg["atr_stop_mult"]) * atrv)
    R = abs(entry - sl)
    tps = [round(entry + m * R, 8) for m in cfg["tp_multiples"]]
    dt_local = to_local_str(df["dt"].iloc[end], cfg)

    return {
        "side": "LONG",
        "ok": ok,
        "cond_break": bool(cond_break),
        "resistance": resistance,
        "buf": float(buf),
        "close": c,
        "cond_vol": bool(cond_vol),
        "vol": float(last["volume"]),
        "vol_ma": float(last["vol_ma"]),
        "vol_mult": float(cfg["vol_spike_min_mult"]),
        "cond_ema": bool(cond_ema),
        "ema_s": float(last["ema_s"]),
        "ema_l": float(last["ema_l"]),
        "slope_s": float(slope),
        "cond_rsi": bool(cond_rsi),
        "rsi": float(last["rsi"]),
        "rsi_min": float(cfg["rsi_min_long"]),
        "cond_body": bool(cond_body),
        "body_frac": float(body),
        "upper_frac": float(upw),
        "lower_frac": float(loww),
        "atr": float(atrv),
        "entry": float(entry),
        "sl": float(sl),
        "tps": tps,
        "dt": dt_local,
    }


def explain_breakout_short_at(df, cfg, idx: int = -2):
    df = add_indicators(df, cfg)
    last = df.iloc[idx]
    lb = int(cfg["breakout_lookback"]) 
    end = df.index.get_loc(last.name)
    start = max(0, end - lb)
    window = df.iloc[start:end]
    support = float(window["low"].min())

    o, h, l, c = map(float, (last["open"], last["high"], last["low"], last["close"]))
    atrv = float(last["atr"]) 
    _, body, upw, loww = _body_wicks(o, h, l, c)

    buf = float(cfg["breakout_buffer_atr"]) * atrv
    cond_break = c < (support - buf)
    cond_vol = float(last["volume"]) >= float(last["vol_ma"] * cfg["vol_spike_min_mult"]) 
    slope = float(df["ema_s"].iloc[end] - df["ema_s"].iloc[end - 1]) if end - 1 >= 0 else 0.0
    cond_ema = (last["ema_s"] < last["ema_l"]) and (slope < 0)
    cond_rsi = float(last["rsi"]) <= float(cfg["rsi_max_short"]) 
    body_req = float(cfg.get("body_min_frac", 0.6))
    wick_req = float(cfg.get("wick_max_frac", 0.2))
    cond_body = (c < o) and (body >= body_req) and (upw <= wick_req) and (loww <= wick_req)

    ok = bool(cond_break and cond_vol and cond_ema and cond_rsi and cond_body)
    entry = c
    sl = float(entry + float(cfg["atr_stop_mult"]) * atrv)
    R = abs(sl - entry)
    tps = [round(entry - m * R, 8) for m in cfg["tp_multiples"]]
    dt_local = to_local_str(df["dt"].iloc[end], cfg)

    return {
        "side": "SHORT",
        "ok": ok,
        "cond_break": bool(cond_break),
        "support": support,
        "buf": float(buf),
        "close": c,
        "cond_vol": bool(cond_vol),
        "vol": float(last["volume"]),
        "vol_ma": float(last["vol_ma"]),
        "vol_mult": float(cfg["vol_spike_min_mult"]),
        "cond_ema": bool(cond_ema),
        "ema_s": float(last["ema_s"]),
        "ema_l": float(last["ema_l"]),
        "slope_s": float(slope),
        "cond_rsi": bool(cond_rsi),
        "rsi": float(last["rsi"]),
        "rsi_max": float(cfg["rsi_max_short"]),
        "cond_body": bool(cond_body),
        "body_frac": float(body),
        "upper_frac": float(upw),
        "lower_frac": float(loww),
        "atr": float(atrv),
        "entry": float(entry),
        "sl": float(sl),
        "tps": tps,
        "dt": dt_local,
    }


# ==============================
# Filtros & mensagens
# ==============================

def passes_liquidity(symbol, cfg, ticker_map=None):
    if not cfg.get("liquidity_filter", False):
        return True
    t = ticker_map.get(symbol) if ticker_map else None
    if not t:
        t = fetch_ticker(symbol, category=cfg.get("category", "linear"))
    if not t:
        return False
    try:
        turnover = float(t.get("turnover24h", "0"))
    except Exception:
        turnover = 0.0
    return turnover >= float(cfg.get("min_24h_turnover_usd", 0))


def fmt_signal_msg(symbol, tf, sig, prefix, meta_map, cfg):
    dir_emoji = "🟢" if sig["side"] == "LONG" else "🔴"
    fp = fmt_pair_prices(symbol, sig, meta_map, cfg)
    return (
        f"{prefix}\n"
        f"📊 Pair: {symbol}\n"
        f"🕒 TF: {tf}m | Candle closed: {sig['dt']}\n"
        f"{dir_emoji} Direction: {sig['side']}\n"
        f"🎯 Entry Zone: {fp['ez_lo']} – {fp['ez_hi']}\n"
        f"🛑 Stop Loss: {fp['sl']}\n"
        f"🥅 Take Profits: {fp['tps'][0]} | {fp['tps'][1]} | {fp['tps'][2]}\n"
        f"🧠 Confidence: {sig['confidence']}%\n"
        f"Notes: {'Breakout' if sig['side']=='LONG' else 'Breakdown'} + vol spike; ATR={round(sig['atr'],6)}"
    )


def fmt_pre_signal_msg(symbol, tf, side, dt_str, trigger, atrv, ex, cfg, meta_map):
    zone_w = float(cfg.get("pre_signal_zone_atr", 0.15)) * atrv
    if side == "LONG":
        ez_lo = fmt_px(symbol, trigger, meta_map, cfg)
        ez_hi = fmt_px(symbol, trigger + zone_w, meta_map, cfg)
        sl = fmt_px(symbol, trigger - float(cfg["atr_stop_mult"]) * atrv, meta_map, cfg)
    else:
        ez_lo = fmt_px(symbol, trigger - zone_w, meta_map, cfg)
        ez_hi = fmt_px(symbol, trigger, meta_map, cfg)
        sl = fmt_px(symbol, trigger + float(cfg["atr_stop_mult"]) * atrv, meta_map, cfg)
    conf = float(cfg.get("pre_signal_confidence", 80.0))
    dir_emoji = "🟢" if side == "LONG" else "🔴"
    return (
        "⏳ PRE-SIGNAL (watchlist)\n"
        f"📊 Pair: {symbol}\n"
        f"🕒 TF: {tf}m | Last closed: {dt_str}\n"
        f"{dir_emoji} Bias: {side}\n"
        f"📈 Trigger ~ {fmt_px(symbol, trigger, meta_map, cfg)} (HH/LL ± buffer)\n"
        f"🎯 Entry Zone (após gatilho): {ez_lo} – {ez_hi}\n"
        f"🛑 Stop Sugerido: {sl}\n"
        f"📊 RSI={round(ex['rsi'],2)}  EMA={'OK' if ex['cond_ema'] else 'NO'}  BODY={'OK' if ex['cond_body'] else 'NO'}\n"
        f"🧠 Confidence: {conf}%\n"
        "Obs.: ainda não rompeu — alerta antecipado (gap em ATR baixo)."
    )


def send_telegram(cfg, text):
    tg = cfg.get("telegram", {})
    if not tg.get("enabled", False):
        print(text)
        return True
    data = safe_post_json(
        f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
        {"chat_id": tg["chat_id"], "text": text},
    )
    if not data:
        print("[net] Telegram send failed")
    return bool(data)


def send_telegram_animation(cfg, caption, gif_path=None, gif_url=None):
    tg = cfg.get("telegram", {})
    if not tg.get("enabled", False):
        print("[GIF][preview] ", caption[:120].replace("\n", " ") + " ...")
        return True

    if caption and len(caption) > 1000:
        caption = caption[:1000] + "…"

    url = f"https://api.telegram.org/bot{tg['bot_token']}/sendAnimation"
    try:
        if gif_url:
            print("[GIF] usando URL:", gif_url)
            payload = {"chat_id": tg["chat_id"], "animation": gif_url, "caption": caption}
            r = SESSION.post(url, json=payload, timeout=20)
            r.raise_for_status()
            return True

        if gif_path:
            ap = os.path.abspath(gif_path)
            if os.path.exists(ap):
                print("[GIF] usando arquivo:", ap)
                with open(ap, "rb") as f:
                    files = {"animation": f}
                    data = {"chat_id": tg["chat_id"], "caption": caption}
                    r = requests.post(url, data=data, files=files, timeout=30)
                    r.raise_for_status()
                    return True
            else:
                print("[GIF] arquivo não encontrado:", ap)

        print("[GIF] sem GIF válido; fallback para texto")
        return send_telegram(cfg, caption)

    except requests.exceptions.RequestException as e:
        print(f"[net] Telegram sendAnimation failed — {e}")
        return send_telegram(cfg, caption)
    except Exception as e:
        print(f"[gif] unexpected: {e}")
        return send_telegram(cfg, caption)


# ==============================
# Estado & sizing
# ==============================

def load_cache(path: str) -> set:
    try:
        return set(load_json(path, []))
    except Exception:
        return set()


def save_cache(path: str, keys: set):
    save_json(path, sorted(list(keys)))


def load_trades(path: str) -> dict:
    try:
        return load_json(path, {})
    except Exception:
        return {}


def save_trades(path: str, data: dict):
    save_json(path, data)


def size_position_usdt(cfg, entry: float, sl: float, lev_used: float | None = None) -> float:
    equity = float(cfg.get("account_equity_usdt", 1000))
    risk = float(cfg.get("risk_per_trade", 0.008))
    r = abs(entry - sl)
    if r <= 0:
        return 0.0
    notional_risk = (equity * risk * entry) / r
    margin_pct = float(cfg.get("margin_per_trade_pct", 0.02))
    margin_budget = equity * margin_pct
    if lev_used is None:
        lev_used = float(cfg.get("default_leverage", 10))
    notional_margin_cap = margin_budget * float(lev_used)
    min_notional = float(cfg.get("min_notional_usdt", 0))
    max_notional = float(cfg.get("max_notional_usdt", 1e12))
    notional = min(notional_risk, notional_margin_cap, max_notional)
    return max(min_notional, round(notional, 2))


def roi_pct(entry, exit_price, lev, side="LONG"):
    dir_ = 1.0 if side == "LONG" else -1.0
    return round(dir_ * ((exit_price - entry) / entry) * lev * 100, 4)


def send_update(cfg, title, body):
    return send_telegram(cfg, f"{title}\n{body}")



# ==============================
# Diagnósticos auxiliares
# ==============================

def _reason(ex):
    if not ex["cond_break"]:
        return "no_break"
    if not ex["cond_vol"]:
        return "no_vol"
    if not ex["cond_ema"]:
        return "no_ema"
    if not ex["cond_rsi"]:
        return "no_rsi"
    if not ex["cond_body"]:
        return "no_body"
    return "ok"


def _gap_long_atr(ex):
    atrv = ex["atr"] or 0.0
    if atrv <= 0:
        return float("inf")
    trig = ex["resistance"] + ex["buf"]
    return (trig - ex["close"]) / atrv


def _gap_short_atr(ex):
    atrv = ex["atr"] or 0.0
    if atrv <= 0:
        return float("inf")
    trig = ex["support"] - ex["buf"]
    return (ex["close"] - trig) / atrv


# ==============================
# Loop principal
# ==============================


def normalize_cfg(cfg: dict) -> dict:
    """Torna cfg tolerante a bool/dict em adx_filter e htf_confirm, preenchendo defaults."""
    # ADX
    adx = cfg.get("adx_filter", False)
    if isinstance(adx, bool):
        cfg["adx_filter"] = {"enabled": adx, "len": 14, "min_adx": 18.0}
    elif isinstance(adx, dict):
        cfg["adx_filter"] = {
            "enabled": bool(adx.get("enabled", False)),
            "len": int(adx.get("len", 14) or 14),
            "min_adx": float(adx.get("min_adx", 18.0) or 18.0),
        }
    else:
        cfg["adx_filter"] = {"enabled": False, "len": 14, "min_adx": 18.0}

    # HTF confirm
    htf = cfg.get("htf_confirm", False)
    if isinstance(htf, bool):
        cfg["htf_confirm"] = {
            "enabled": htf,
            "tf": str(cfg.get("default_htf_tf", "60")),
            "ema_short": int(cfg.get("ema_short", 21) or 21),
            "ema_long": int(cfg.get("ema_long", 50) or 50),
            "allow_neutral": True,
        }
    elif isinstance(htf, dict):
        cfg["htf_confirm"] = {
            "enabled": bool(htf.get("enabled", False)),
            "tf": str(htf.get("tf", "60")),
            "ema_short": int(htf.get("ema_short", 21) or 21),
            "ema_long": int(htf.get("ema_long", 50) or 50),
            "allow_neutral": bool(htf.get("allow_neutral", True)),
        }
    else:
        cfg["htf_confirm"] = {
            "enabled": False,
            "tf": "60",
            "ema_short": 21,
            "ema_long": 50,
            "allow_neutral": True,
        }

    # timeframes sempre como lista de strings
    tfs = cfg.get("timeframes", ["15"])
    if isinstance(tfs, (int, float, str)):
        cfg["timeframes"] = [str(tfs)]
    else:
        cfg["timeframes"] = [str(x) for x in tfs]

    return cfg


def main():
    cfg = normalize_cfg(load_cfg())
    BG_CARD = cfg.get("card_bg_path", "assets/moonshot/bg.jpg")  # opcional no YAML
    cache = load_cache(cfg["cache_file"])
    pre_cache = load_cache(cfg.get("pre_cache_file", "moonshot_pre_cache.json"))
    trades = load_trades(cfg["trades_file"])

    # AutoBlacklist
    bl_cfg = (cfg.get("blacklist") or {})
    abl = AutoBlacklist(
        path=bl_cfg.get("file", cfg.get("blacklist_file", "moonshot_blacklist.json")),
        rules=bl_cfg.get("rules", {}),
        hard_denylist=(bl_cfg.get("hard_denylist") or cfg.get("denylist") or []),
        enabled=bl_cfg.get("enabled", True),
    )
    abl.cleanup()

    # Símbolos
    if cfg.get("symbols_auto", False):
        cache_file = cfg.get("symbols_cache_file", "moonshot_symbols.json")
        symbols = load_json(cache_file, [])
        if not symbols:
            symbols = discover_perp_symbols(cfg)
            save_json(cache_file, symbols)
    else:
        symbols = list(cfg.get("symbols", []))
    if "BTCUSDT" not in symbols:
        symbols.append("BTCUSDT")

    # Filtro de blacklist no conjunto final (garantia extra)
    symbols = [s for s in symbols if not abl.is_blocked(s)[0]]

    # Metadados de preço (tickSize/decimais)
    symbol_meta = build_symbol_meta_map(cfg)

    batch_size = int(cfg.get("max_symbols_per_cycle", 160))
    scan_idx = 0
    tfs = [str(x) for x in cfg.get("timeframes", ["5", "15"])]

    # Logs de candidatos
    show_cands = bool(cfg.get("log_show_candidates", True))
    cands_top_n = int(cfg.get("log_candidates_top_n", 12))
    cands_gap_max = float(cfg.get("log_candidates_gap_max_atr", 0.5))
    log_each = bool(cfg.get("log_each_eval", False))

    # Pré-sinal
    pre_enabled = bool(cfg.get("pre_signal_enabled", True))
    pre_gap = float(cfg.get("pre_signal_gap_atr", 0.10))
    pre_need_vol = bool(cfg.get("pre_signal_require_vol", False))

    # Backscan
    back_enabled = bool(cfg.get("backscan_enabled", True))
    back_k = max(1, int(cfg.get("backscan_k", 3)))

    print("Moonshot running…")
    print(f"[symbols] total={len(symbols)} | auto={cfg.get('symbols_auto', False)}")

    # Cache de DF para reaproveitar
    df_cache: dict[tuple[str, str], pd.DataFrame | None] = {}

    def get_df(sym: str, tf: str):
        key = (sym, tf)
        if key not in df_cache:
            df_cache[key] = fetch_klines(sym, interval=tf, limit=200, category=cfg.get("category", "linear"))
        return df_cache[key]

    while True:
        try:
            tick_map = fetch_tickers_map(category=cfg.get("category", "linear"))

            start = scan_idx
            end = min(scan_idx + batch_size, len(symbols))
            batch = symbols[start:end]
            scan_idx = 0 if end >= len(symbols) else end

            if cfg.get("log_batch_size", True):
                print(f"[scan] batch {start}-{end} ({len(batch)} símbolos) TF={tfs}")

            signals_this_cycle = 0
            rej: dict[str, Counter] = {"LONG": Counter(), "SHORT": Counter()}
            batch_candidates: list[dict] = []

            for sym in batch:
                # Blacklist: checagem rápida
                blocked, why = abl.is_blocked(sym)
                if blocked:
                    if cfg.get("debug", False):
                        print(f"[skip] {sym} (blacklisted: {why})")
                    continue

                # Auto-ban por candles (usa 15m e 60m)
                df15 = get_df(sym, "15")
                df60 = get_df(sym, "60")
                bl_reason = abl.auto_from_candles(sym, df_15m=df15, df_1h=df60, ticker=tick_map.get(sym))
                if bl_reason:
                    if cfg.get("debug", False):
                        print(f"[auto-blacklist] {sym} -> {bl_reason}")
                    continue

                fired = False

                for tf in tfs:
                    df = get_df(sym, tf)

                    # [QUALITY_PATCH] regime filters (ATR%, ADX, HTF)
                    # 0) DF suficiente?
                    if df is None or len(df) < (int(cfg.get("breakout_lookback", 20)) + 5):
                        if log_each:
                            print(f"[rej] {sym:12} {tf}m (DF insuficiente)")
                        continue

                    # 1) ATR% mínimo no TF
                    try:
                        atr_len = int(cfg.get("atr_len", 14))
                        pc = df["close"].shift(1)
                        tr = (
                            (df["high"] - df["low"]).combine((df["high"] - pc).abs(), max).combine((df["low"] - pc).abs(), max)
                        )
                        atr_series = tr.ewm(alpha=1 / atr_len, adjust=False).mean()
                        atr_abs = float(atr_series.iloc[-2])
                        price = float(df["close"].iloc[-2])
                        atr_pct = (atr_abs / max(price, 1e-12)) * 100.0
                        min_atr_pct = float(cfg.get("min_atr_pct_trade_15m", 0.0)) if str(tf) == "15" else 0.0
                        if atr_pct < min_atr_pct:
                            if log_each:
                                print(f"[rej] {sym:12} {tf}m (atr% {atr_pct:.2f} < {min_atr_pct})")
                            continue
                    except Exception:
                        pass

                    # 2) ADX (força de tendência)
                    bias = "NEUTRAL"
                    pdi = mdi = adxv = None
                    if cfg.get("adx_filter", {}).get("enabled", False):
                        try:
                            pdi, mdi, adxv = dmi_adx(df, int(cfg.get("adx_filter", {}).get("len", 14)))
                            adx_last = float(adxv.iloc[-2])
                            if adx_last < float(cfg["adx_filter"]["min_adx"]):
                                if log_each:
                                    print(f"[rej] {sym:12} {tf}m (ADX {adx_last:.1f} < {cfg['adx_filter']['min_adx']})")
                                continue
                        except Exception:
                            continue

                    # 3) Confirmação pela TF maior
                    if cfg.get("htf_confirm", {}).get("enabled", False):
                        try:
                            htf_tf = str(cfg["htf_confirm"]["tf"])
                            df_htf = get_df(sym, htf_tf)
                            bias = htf_direction(
                                df_htf,
                                int(cfg["htf_confirm"]["ema_short"]),
                                int(cfg["htf_confirm"]["ema_long"]),
                            )
                            if not cfg["htf_confirm"].get("allow_neutral", False) and bias == "NEUTRAL":
                                if log_each:
                                    print(f"[rej] {sym:12} {tf}m (HTF {htf_tf} bias NEUTRAL)")
                                continue
                        except Exception:
                            if log_each:
                                print(f"[rej] {sym:12} {tf}m (HTF erro)")
                            continue

                    # Índices a avaliar: backscan + vela fechada mais recente
                    indices = list(range(-2, -2 - back_k, -1)) if back_enabled else [-2]

                    for idx in indices:
                        # Calcula explicações Long/Short
                        exL = explain_breakout_long_at(df, cfg, idx=idx)
                        exS = explain_breakout_short_at(df, cfg, idx=idx) if cfg.get("enable_shorts", True) else None
                        dt_last = exL["dt"]

                        gapL = _gap_long_atr(exL)
                        gapS = _gap_short_atr(exS) if exS else float("inf")
                        if abs(gapL) <= abs(gapS):
                            side = "LONG"
                            ex = exL
                            gap = gapL
                            trigger = ex["resistance"] + ex["buf"]
                        else:
                            side = "SHORT"
                            ex = exS  # type: ignore
                            gap = gapS
                            trigger = ex["support"] - ex["buf"]  # type: ignore

                        if idx == -2 and show_cands and abs(gap) <= cands_gap_max:
                            row = {
                                "sym": sym,
                                "tf": tf,
                                "side": side,
                                "gap": round(gap, 3),
                                "reason": _reason(ex),
                                "rsi": round(ex["rsi"], 2),
                                "ema": ex["cond_ema"],
                                "vol": ex["cond_vol"],
                                "body": ex["cond_body"],
                            }
                            batch_candidates.append(row)
                            if log_each:
                                print(
                                    f"[eval] {sym:12} {tf:>2}m "
                                    f"{'🟢' if side=='LONG' else '🔴'} gap={row['gap']:>5} ATR  "
                                    f"reason={row['reason']:>8}  RSI={row['rsi']:>5}  "
                                    f"EMA={bmark(row['ema'])} VOL={bmark(row['vol'])} BODY={bmark(row['body'])}"
                                )

                        # Melhor lado, se houver
                        best = None
                        if exL["ok"]:
                            best = exL
                        if exS and exS["ok"]:
                            distL = (
                                (exL["close"] - (exL["resistance"] + exL["buf"])) / (exL["atr"] or 1e-12)
                                if exL["ok"]
                                else -1e9
                            )
                            distS = (
                                ((exS["support"] - exS["buf"]) - exS["close"]) / (exS["atr"] or 1e-12)
                                if exS["ok"]
                                else -1e9
                            )
                            best = exS if distS > distL else (exL if exL["ok"] else None)

                        # [QUALITY_PATCH] alinhar direção do sinal com filtros de regime
                        ok_dir = True
                        try:
                            if cfg.get("adx_filter", {}).get("enabled", False) and pdi is not None and mdi is not None:
                                desired = "LONG" if float(pdi.iloc[-2]) > float(mdi.iloc[-2]) else "SHORT"
                                ok_dir &= (best and best.get("side") == desired)
                            if cfg.get("htf_confirm", {}).get("enabled", False):
                                ok_dir &= (best and (bias == "NEUTRAL" or best.get("side") == bias))
                        except Exception:
                            pass

                        if best is None or not ok_dir:
                            # Pré-sinal (somente vela fechada mais recente)
                            if idx == -2 and pre_enabled and abs(gap) <= pre_gap:
                                conf_ok = (
                                    ex["cond_ema"]
                                    and ex["cond_rsi"]
                                    and ex["cond_body"]
                                    and (ex["cond_vol"] if pre_need_vol else True)
                                )
                                if conf_ok and not ex["cond_break"]:
                                    pre_key = f"PRE:{sym}:{tf}:{dt_last}:{side}"
                                    if pre_key not in pre_cache:
                                        entry_center = trigger
                                        atrv = ex["atr"]
                                        if side == "LONG":
                                            sl = entry_center - float(cfg["atr_stop_mult"]) * atrv
                                        else:
                                            sl = entry_center + float(cfg["atr_stop_mult"]) * atrv

                                        lev_default = float(cfg.get("default_leverage", 10))
                                        lev_safe = recommend_leverage(
                                            entry_center, sl, lev_default, cfg.get("leverage_safety_mult", 0.85)
                                        )
                                        lev_instr = symbol_meta.get(sym, {}).get("maxLev", 25.0)
                                        lev_cap = float(cfg.get("lev_cap", 25.0))
                                        lev_used = min(lev_default, lev_safe, lev_instr, lev_cap)

                                        notional = size_position_usdt(cfg, entry_center, sl, lev_used)
                                        margin_est = round(notional / max(lev_used, 1e-12), 2)

                                        pre_msg = fmt_pre_signal_msg(
                                            sym, tf, side, dt_last, trigger, atrv, ex, cfg, symbol_meta
                                        )
                                        pre_msg += (
                                            f"\n💰 Notional sugerido: ~${notional} | Lev.: {lev_used}x | Margem≈${margin_est}"
                                        )
                                        send_telegram(cfg, pre_msg)

                                        pre_cache.add(pre_key)
                                        save_cache(cfg.get("pre_cache_file", "moonshot_pre_cache.json"), pre_cache)

                            # Contabiliza rejeição
                            if idx == -2:
                                (rej["LONG"] if side == "LONG" else rej["SHORT"])[_reason(exL if side == "LONG" else exS)] += 1
                            continue  # próximo idx

                        # Monta sinal
                        atrv = best["atr"]
                        entry = best["entry"]
                        sig = {
                            "side": best["side"],
                            "entry_zone": (round(entry - 0.15 * atrv, 8), round(entry + 0.15 * atrv, 8)),
                            "entry_price": round(entry, 8),
                            "sl": round(best["sl"], 8),
                            "tps": [round(x, 8) for x in best["tps"]],
                            "atr": round(atrv, 8),
                            "confidence": 100.0,
                            "dt": best["dt"],
                        }
                        key = f"{sym}:{tf}:{sig['dt']}:{sig['side']}"
                        if key in cache:
                            fired = True
                            break

                        # Tamanho/Alavancagem
                        lev_default = float(cfg.get("default_leverage", 10))
                        lev_safe = recommend_leverage(
                            sig["entry_price"], sig["sl"], lev_default, cfg.get("leverage_safety_mult", 0.85)
                        )
                        lev_instr = symbol_meta.get(sym, {}).get("maxLev", 25.0)
                        lev_cap = float(cfg.get("lev_cap", 25.0))
                        lev_used = min(lev_default, lev_safe, lev_instr, lev_cap)
                        notional = size_position_usdt(cfg, sig["entry_price"], sig["sl"], lev_used)
                        margin_est = round(notional / max(lev_used, 1e-12), 2)

                        prefix = "🚀 AI SIGNAL IS READY" if idx == -2 else "⏪ BACKSCAN — AI SIGNAL"
                        msg = (
                            fmt_signal_msg(sym, tf, sig, prefix, symbol_meta, cfg)
                            + f"\n💰 Notional sugerido: ~${notional} | Lev.: {lev_used}x | Margem≈${margin_est}"
                        )
                        gif_path = cfg.get("signal_ready_gif_path")
                        gif_url = cfg.get("signal_ready_gif_url")
                        if idx == -2 and (gif_path or gif_url):
                            send_telegram_animation(cfg, msg, gif_path=gif_path, gif_url=gif_url)
                        else:
                            send_telegram(cfg, msg)

                        if idx == -2:
                            trades[key] = {
                                "symbol": sym,
                                "tf": tf,
                                "side": sig["side"],
                                "status": "OPEN",
                                "entry": sig["entry_price"],
                                "sl": sig["sl"],
                                "tp1": sig["tps"][0],
                                "tp2": sig["tps"][1],
                                "tp3": sig["tps"][2],
                                "lev": lev_used,
                                "notional": notional,
                                "created_at": sig["dt"],
                                "updates": [],
                            }
                            save_trades(cfg["trades_file"], trades)

                        cache.add(key)
                        save_cache(cfg["cache_file"], cache)
                        signals_this_cycle += 1
                        fired = True
                        break  # sai do loop de idx

                    if fired:
                        break  # sai do loop de TFs para este símbolo

                if fired:
                    continue  # próximo símbolo

            # Vitrine de candidatos
            if show_cands and not log_each:
                if batch_candidates:
                    batch_candidates.sort(key=lambda r: abs(r["gap"]))
                    print(" [cands] Top analisados (mais perto do gatilho):")
                    for r in batch_candidates[:cands_top_n]:
                        print(
                            f"   {r['sym']:12} {r['tf']:>2}m "
                            f"{'🟢' if r['side']=='LONG' else '🔴'} gap={r['gap']:>5} ATR  "
                            f"reason={r['reason']:>8}  RSI={r['rsi']:>5}  "
                            f"EMA={bmark(r['ema'])} VOL={bmark(r['vol'])} BODY={bmark(r['body'])}"
                        )
                else:
                    print(" [cands] Nenhum candidato próximo ao gatilho neste batch.")

            # Resumo
            if cfg.get("debug", True):
                open_trades = sum(1 for t in trades.values() if t.get("status") not in ("CLOSED_TP3", "STOP"))
                rej_long = {k: v for k, v in rej["LONG"].items() if v}
                rej_short = {k: v for k, v in rej["SHORT"].items() if v}
                dbg(
                    cfg,
                    f"ciclo ok | sinais:{signals_this_cycle} | abertos:{open_trades} | "
                    f"rejLONG={rej_long or {'-': 0}} | rejSHORT={rej_short or {'-': 0}}",
                )

            # Monitoramento de trades (tempo real)
            for key, tr in list(trades.items()):
                if tr["status"] in ("CLOSED_TP3", "STOP"):
                    continue
                price = last_price(tr["symbol"], category=cfg.get("category", "linear"))
                if price is None:
                    continue
                side = tr.get("side", "LONG")

                if side == "LONG":
                    if tr["status"] == "OPEN" and price >= tr["tp1"]:
                        tr["status"] = "TP1"
                        tr["sl"] = tr["entry"]
                        tr["updates"].append({
                            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "event": "TP1",
                            "price": price,
                        })
                        send_update(
                            cfg,
                            "AI Signals Bot | Trade Update",
                            f"✅ TP1 hit | {tr['symbol']} {side} on {tr['tf']}m\n"
                            f"Entry: {tr['entry']}  •  TP1: {tr['tp1']}\n"
                            f"➡️ Stop movido para BE ({tr['sl']})",
                        )
                        try:
                            send_tp_card(
                                cfg["telegram"]["bot_token"],
                                cfg["telegram"]["chat_id"],
                                {
                                    "symbol": tr["symbol"],
                                    "side": side,
                                    "leverage": f"{tr['lev']}x",
                                    "tp_label": "TP1",
                                    "roi_pct": roi_pct(tr["entry"], price, tr["lev"], side),
                                    "entry": tr["entry"],
                                    "last": price,
                                    "stop_text": f"{tr['sl']}",
                                    "caption": f"{tr['symbol']} | TP1 atingido ✅",
                                },
                                bg_path=BG_CARD,
                            )
                        except Exception as e:
                            dbg(cfg, f"card tp1 erro: {e}")

                    elif tr["status"] in ("OPEN", "TP1") and price <= tr["sl"]:
                        tr["status"] = "STOP"
                        roi = roi_pct(tr["entry"], price, tr["lev"], side)
                        tr.update({
                            "exit_price": price,
                            "exit_reason": "STOP" if price < tr["entry"] else "BE",
                            "roi_pct": roi,
                            "closed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        })
                        tr["updates"].append({
                            "ts": tr["closed_at"],
                            "event": "STOP",
                            "price": price,
                            "roi_pct": roi,
                        })
                        abl.register_stop(tr["symbol"])  # cooldown
                        send_update(
                            cfg,
                            "Trade Closed",
                            f"🛑 Stop Loss | {tr['symbol']} {side} on {tr['tf']}m\n"
                            f"Fill: {price}\nROI (est.): {roi}%",
                        )
                    elif tr["status"] in ("OPEN", "TP1") and price >= tr["tp2"]:
                        if tr["status"] != "TP2":
                            tr["status"] = "TP2"
                            tr["updates"].append({
                                "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                                "event": "TP2",
                                "price": price,
                            })
                            send_update(
                                cfg,
                                "AI Signals Bot | Trade Update",
                                f"✅ TP2 hit | {tr['symbol']} {side} on {tr['tf']}m\n"
                                f"TP2: {tr['tp2']}  •  Stop permanece em BE ({tr['sl']})",
                            )
                            try:
                                send_tp_card(
                                    cfg["telegram"]["bot_token"],
                                    cfg["telegram"]["chat_id"],
                                    {
                                        "symbol": tr["symbol"],
                                        "side": side,
                                        "leverage": f"{tr['lev']}x",
                                        "tp_label": "TP2",
                                        "roi_pct": roi_pct(tr["entry"], price, tr["lev"], side),
                                        "entry": tr["entry"],
                                        "last": price,
                                        "stop_text": f"{tr['sl']}",
                                        "caption": f"{tr['symbol']} | TP2 atingido ✅",
                                    },
                                    bg_path=BG_CARD,
                                )
                            except Exception as e:
                                dbg(cfg, f"card tp2 erro: {e}")

                    elif tr["status"] in ("TP2", "TP1", "OPEN") and price >= tr["tp3"]:
                        tr["status"] = "CLOSED_TP3"
                        roi = roi_pct(tr["entry"], price, tr["lev"], side)
                        tr.update({
                            "exit_price": price,
                            "exit_reason": "TP3",
                            "roi_pct": roi,
                            "closed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        })
                        tr["updates"].append({
                            "ts": tr["closed_at"],
                            "event": "TP3",
                            "price": price,
                            "roi_pct": roi,
                        })
                        send_update(
                            cfg,
                            "Trade Closed",
                            f"🏁 3TP hit — encerrando | {tr['symbol']} {tr['tf']}m\n"
                            f"Filled: {price}\nROI (est.): {roi}%",
                        )
                        try:
                            send_tp_card(
                                cfg["telegram"]["bot_token"],
                                cfg["telegram"]["chat_id"],
                                {
                                    "symbol": tr["symbol"],
                                    "side": side,
                                    "leverage": f"{tr['lev']}x",
                                    "tp_label": "TP3",
                                    "roi_pct": roi_pct(tr["entry"], price, tr["lev"], side),
                                    "entry": tr["entry"],
                                    "last": price,
                                    "stop_text": f"{tr['sl']}",
                                    "caption": f"{tr['symbol']} | TP3 atingido 🏁",
                                },
                                bg_path=BG_CARD,
                            )
                        except Exception as e:
                            dbg(cfg, f"card tp3 erro: {e}")

                else:
                    # SHORT
                    if tr["status"] == "OPEN" and price <= tr["tp1"]:
                        tr["status"] = "TP1"
                        tr["sl"] = tr["entry"]
                        tr["updates"].append({
                            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "event": "TP1",
                            "price": price,
                        })
                        send_update(
                            cfg,
                            "AI Signals Bot | Trade Update",
                            f"✅ TP1 hit | {tr['symbol']} {side} on {tr['tf']}m\n"
                            f"Entry: {tr['entry']}  •  TP1: {tr['tp1']}\n"
                            f"➡️ Stop movido para BE ({tr['sl']})",
                        )
                    elif tr["status"] in ("OPEN", "TP1") and price >= tr["sl"]:
                        tr["status"] = "STOP"
                        roi = roi_pct(tr["entry"], price, tr["lev"], side)
                        tr.update({
                            "exit_price": price,
                            "exit_reason": "STOP" if price > tr["entry"] else "BE",
                            "roi_pct": roi,
                            "closed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        })
                        tr["updates"].append({
                            "ts": tr["closed_at"],
                            "event": "STOP",
                            "price": price,
                            "roi_pct": roi,
                        })
                        abl.register_stop(tr["symbol"])  # cooldown
                        send_update(
                            cfg,
                            "Trade Closed",
                            f"🛑 Stop Loss | {tr['symbol']} {side} on {tr['tf']}m\n"
                            f"Fill: {price}\nROI (est.): {roi}%",
                        )
                    elif tr["status"] in ("OPEN", "TP1") and price <= tr["tp2"]:
                        if tr["status"] != "TP2":
                            tr["status"] = "TP2"
                            tr["updates"].append({
                                "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                                "event": "TP2",
                                "price": price,
                            })
                            send_update(
                                cfg,
                                "AI Signals Bot | Trade Update",
                                f"✅ TP2 hit | {tr['symbol']} {side} on {tr['tf']}m\n"
                                f"TP2: {tr['tp2']}  •  Stop permanece em BE ({tr['sl']})",
                            )
                    elif tr["status"] in ("TP2", "TP1", "OPEN") and price <= tr["tp3"]:
                        tr["status"] = "CLOSED_TP3"
                        roi = roi_pct(tr["entry"], price, tr["lev"], side)
                        tr.update({
                            "exit_price": price,
                            "exit_reason": "TP3",
                            "roi_pct": roi,
                            "closed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        })
                        tr["updates"].append({
                            "ts": tr["closed_at"],
                            "event": "TP3",
                            "price": price,
                            "roi_pct": roi,
                        })
                        send_update(
                            cfg,
                            "Trade Closed",
                            f"🏁 3TP hit — encerrando | {tr['symbol']} {tr['tf']}m\n"
                            f"Filled: {price}\nROI (est.): {roi}%",
                        )

                save_trades(cfg["trades_file"], trades)

            time.sleep(float(cfg.get("poll_seconds", 30)))

        except KeyboardInterrupt:
            print("Stopped by user.")
            break
        except Exception as e:
            print("Loop error:", e)
            traceback.print_exc()
            time.sleep(5)


# ==============================
# Helpers de regime (canon)
# ==============================

def dmi_adx(df, n: int = 14):
    import pandas as pd
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)).astype(float) * up
    minus_dm = ((dn > up) & (dn > 0)).astype(float) * dn
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdm = plus_dm.ewm(alpha=1 / n, adjust=False).mean()
    mdm = minus_dm.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * (pdm / atr)
    minus_di = 100 * (mdm / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return plus_di, minus_di, adx


def htf_direction(df, ema_s_len: int, ema_l_len: int) -> str:
    es = df["close"].ewm(span=ema_s_len, adjust=False).mean()
    el = df["close"].ewm(span=ema_l_len, adjust=False).mean()
    if len(df) < max(ema_s_len, ema_l_len) + 2:
        return "NEUTRAL"
    up = (es.iloc[-1] > el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] > 0)
    down = (es.iloc[-1] < el.iloc[-1]) and (es.iloc[-1] - es.iloc[-2] < 0)
    return "LONG" if up else ("SHORT" if down else "NEUTRAL")


if __name__ == "__main__":
    main()
