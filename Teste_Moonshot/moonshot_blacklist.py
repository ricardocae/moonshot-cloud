# moonshot_blacklist.py
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List

import numpy as np
import pandas as pd


@dataclass
class Entry:
    symbol: str
    reason: str
    until: Optional[float]           # epoch seconds; None => permaban
    strikes: int = 0
    first_seen: float = None
    last_updated: float = None


class AutoBlacklist:
    """
    Blacklist automática para o projeto Moonshot.

    Recursos:
      - denylist permanente (vindas do YAML original; 'hard_denylist' opcional na seção blacklist).
      - blacklist dinâmica com TTL e escalonamento por strikes (cooldown).
      - avaliação automática a partir de candles (15m/1h) + ticker (turnover24h).
      - robusta para formatos legados do JSON:
          * lista: ["ABCUSDT", ...]
          * dict direto: { "ABCUSDT": {entry...}, ... }
          * dict com entries: { "entries": { "ABCUSDT": {entry...} } }
          * dict com 'symbols': { "symbols": ["ABCUSDT", ...] }

    Regras (em cfg['blacklist']['rules']):
      - exempt_symbols: lista de símbolos isentos do filtro WICKY.
      - exempt_from_illq_symbols: isentos do filtro de ILLIQUIDEZ.
      - min_candles_15m / 1h
      - min_quote_vol_24h (USDT) — limiar para liquidez (~24h)
      - max_atr_pct_15m / 1h
      - wick_lookback_15, max_wick_pct_avg_15m (em %), min_body_frac_15m (0..1)
      - cooldown_hours_* (new_listing, iliq, volatility, wick)
      - stop_strikes_for_cooldown, cooldown_hours_on_strikes
    """

    def __init__(
        self,
        path: str,
        rules: dict,
        hard_denylist: List[str] | None = None,
        enabled: bool = True,
    ):
        self.path = path or "moonshot_blacklist.json"
        self.rules = rules or {}
        self.enabled = bool(enabled)
        self.hard_denylist = set(s.upper().strip() for s in (hard_denylist or []))
        self.db: Dict[str, Entry] = {}
        self._load()

    # ---------- Persistência ----------
    def _normalize_payload(self, raw):
        """
        Normaliza os diversos formatos legados para:
            { "entries": {SYM: {Entry-like}, ...} }
        """
        now = self._now()

        # Lista simples
        if isinstance(raw, list):
            entries = {}
            for s in raw:
                if isinstance(s, str) and s.strip():
                    sym = s.upper().strip()
                    entries[sym] = {
                        "symbol": sym, "reason": "legacy_list",
                        "until": None, "strikes": 0,
                        "first_seen": now, "last_updated": now
                    }
            return {"entries": entries}

        # Dicionário
        if isinstance(raw, dict):
            # Já padronizado
            if "entries" in raw and isinstance(raw["entries"], dict):
                return {"entries": raw["entries"]}

            # Chave "symbols" (lista)
            if "symbols" in raw and isinstance(raw["symbols"], list):
                return self._normalize_payload(raw["symbols"])

            # Dict direto mapeando SYM -> Entry-like (ou flags)
            if raw and all(isinstance(k, str) for k in raw.keys()):
                # Parece Entry-like?
                if all(isinstance(v, dict) and ("symbol" in v or "until" in v or "reason" in v)
                       for v in raw.values()):
                    return {"entries": raw}

                # Caso misto: {SYM: qualquer_coisa_truthy}
                entries = {}
                for k, v in raw.items():
                    if not isinstance(k, str):
                        continue
                    sym = k.upper().strip()
                    if isinstance(v, dict):
                        e = {
                            "symbol": sym,
                            "reason": str(v.get("reason", "legacy_dict")),
                            "until": v.get("until", None),
                            "strikes": int(v.get("strikes", 0)),
                            "first_seen": float(v.get("first_seen", now)),
                            "last_updated": float(v.get("last_updated", now)),
                        }
                    else:
                        e = {
                            "symbol": sym, "reason": "legacy_dict_flag",
                            "until": None, "strikes": 0,
                            "first_seen": now, "last_updated": now
                        }
                    entries[sym] = e
                return {"entries": entries}

        # Desconhecido → vazio
        return {"entries": {}}

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)

            payload = self._normalize_payload(raw)
            self.db = {}
            for s, e in (payload.get("entries") or {}).items():
                # saneamento mínimo
                e = {
                    "symbol": (e.get("symbol") or s).upper(),
                    "reason": str(e.get("reason", "unspecified")),
                    "until": e.get("until", None),
                    "strikes": int(e.get("strikes", 0)),
                    "first_seen": float(e.get("first_seen", self._now())),
                    "last_updated": float(e.get("last_updated", self._now())),
                }
                self.db[s] = Entry(**e)

            # Regrava já no formato novo se veio legado
            self._save()

        except FileNotFoundError:
            self.db = {}
        except Exception as ex:
            # cria backup se o arquivo estiver de fato corrompido
            try:
                if os.path.exists(self.path):
                    os.replace(self.path, self.path + ".corrupted")
            finally:
                self.db = {}
                print(f"[blacklist] arquivo corrompido; reiniciando. Detalhe: {ex}")

    def _save(self):
        tmp = self.path + ".tmp"
        dname = os.path.dirname(self.path)
        if dname:
            os.makedirs(dname, exist_ok=True)
        payload = {"entries": {s: asdict(e) for s, e in self.db.items()}}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, self.path)

    # ---------- Utilidades ----------
    @staticmethod
    def _now() -> float:
        return time.time()

    def cleanup(self, now: Optional[float] = None) -> List[str]:
        """Remove bans expirados."""
        now = now or self._now()
        removed = []
        for s, e in list(self.db.items()):
            if e.until is not None and now >= e.until:
                removed.append(s)
                self.db.pop(s, None)
        if removed:
            self._save()
        return removed

    # ---------- API principal ----------
    def is_blocked(self, symbol: str, now: Optional[float] = None) -> tuple[bool, str]:
        s = symbol.upper()
        if s in self.hard_denylist:
            return True, "hard_denylist"
        e = self.db.get(s)
        if not e:
            return False, ""
        if e.until is None:
            return True, e.reason  # permaban
        now = now or self._now()
        if now < e.until:
            return True, e.reason
        return False, ""

    def ban_temp(self, symbol: str, hours: float, reason: str, strikes_inc: int = 0):
        if not self.enabled:
            return
        s = symbol.upper()
        now = self._now()
        until = now + float(hours) * 3600.0
        old = self.db.get(s)
        strikes = (old.strikes if old else 0) + int(strikes_inc)
        entry = Entry(
            symbol=s,
            reason=reason,
            until=until,
            strikes=strikes,
            first_seen=(old.first_seen if old and old.first_seen else now),
            last_updated=now,
        )
        self.db[s] = entry
        self._save()

    def ban_perm(self, symbol: str, reason: str = "permanent"):
        if not self.enabled:
            return
        s = symbol.upper()
        now = self._now()
        old = self.db.get(s)
        entry = Entry(
            symbol=s,
            reason=reason,
            until=None,   # permaban
            strikes=(old.strikes if old else 0),
            first_seen=(old.first_seen if old and old.first_seen else now),
            last_updated=now,
        )
        self.db[s] = entry
        self._save()

    def unban(self, symbol: str):
        s = symbol.upper()
        if s in self.db:
            self.db.pop(s, None)
            self._save()

    def register_stop(self, symbol: str, now: Optional[float] = None):
        """
        Registra um SL no símbolo. Ao atingir o limiar, aplica cooldown automático.
        """
        now = now or self._now()
        s = symbol.upper()
        e = self.db.get(s)
        strikes = (e.strikes if e else 0) + 1
        self.db[s] = Entry(
            symbol=s,
            reason="strike",
            until=(e.until if e else now),
            strikes=strikes,
            first_seen=(e.first_seen if e and e.first_seen else now),
            last_updated=now,
        )
        self._save()

        thr = int(self.rules.get("stop_strikes_for_cooldown", 2))
        cd_hours = float(self.rules.get("cooldown_hours_on_strikes", 6))
        if strikes >= thr:
            self.ban_temp(s, cd_hours, f"{strikes} SL strikes (cooldown)")

    # ---------- Regras automáticas por candles ----------
    def auto_from_candles(
        self,
        symbol: str,
        df_15m: Optional[pd.DataFrame] = None,
        df_1h: Optional[pd.DataFrame] = None,
        ticker: Optional[dict] = None,   # passar tick_map.get(symbol)
    ) -> Optional[str]:
        """
        Analisa candles e aplica ban temporário conforme regras.
        Retorna o motivo caso aplique ban; caso contrário, None.
        Espera colunas: open, high, low, close, volume, turnover (floats).
        """
        if not self.enabled:
            return None

        try:
            s = symbol.upper()
            exempt_wicky = set(x.upper() for x in self.rules.get("exempt_symbols", []))
            exempt_illq = set(x.upper() for x in self.rules.get("exempt_from_illq_symbols", []))

            # ========== 15m ==========
            if df_15m is not None and len(df_15m) > 0:
                min15 = int(self.rules.get("min_candles_15m", 120))
                if len(df_15m) < min15:
                    self.ban_temp(
                        symbol,
                        float(self.rules.get("cooldown_hours_new_listing", 24)),
                        f"NEW_LISTING <{min15}x15m",
                    )
                    return "NEW_LISTING_15m"

                atr15 = _atr_percent(df_15m, n=14)
                if atr15 > float(self.rules.get("max_atr_pct_15m", 6.0)):
                    self.ban_temp(
                        symbol,
                        float(self.rules.get("cooldown_hours_volatility", 12)),
                        f"HIGH_VOL_15m ATR%={atr15:.1f}",
                    )
                    return "HIGH_VOL_15m"

                # --- Wickiness + filtro de corpo médio ---
                wick_look = int(self.rules.get("wick_lookback_15", 48))
                tail15 = df_15m.tail(wick_look)
                if s not in exempt_wicky and len(tail15) >= max(12, int(wick_look * 0.5)):
                    wavg15 = _wickiness_pct(tail15)          # em %
                    body_avg15 = _body_frac_avg(tail15)      # fração [0..1]
                    if (wavg15 > float(self.rules.get("max_wick_pct_avg_15m", 70.0)) and
                        body_avg15 < float(self.rules.get("min_body_frac_15m", 0.30))):
                        self.ban_temp(
                            symbol,
                            float(self.rules.get("cooldown_hours_wick", 12)),
                            f"WICKY_15m {wavg15:.0f}% | body_avg={body_avg15:.2f}",
                        )
                        return "WICKY_15m"

                # --- Liquidez (~24h) preferindo ticker.turnover24h ---
                look = 96
                vq = None

                # 1) Ticker (melhor fonte)
                if ticker:
                    try:
                        vq = float(ticker.get("turnover24h") or 0.0)
                    except Exception:
                        vq = None

                # 2) Fallback: somatório das últimas 96 velas (15m)
                if (vq is None or vq <= 0.0) and len(df_15m) >= look:
                    if "turnover" in df_15m.columns and df_15m["turnover"].notna().any():
                        vq = float(df_15m.tail(look)["turnover"].sum())
                    else:
                        vq = float((df_15m.tail(look)["volume"] * df_15m.tail(look)["close"]).sum())

                if vq is not None and vq >= 0:
                    min_vq = float(self.rules.get("min_quote_vol_24h", 1_500_000))  # 1.5M por padrão
                    if s not in exempt_illq and vq < min_vq:
                        self.ban_temp(
                            symbol,
                            float(self.rules.get("cooldown_hours_iliquid", 24)),
                            f"ILLQ v24h≈{vq:,.0f}",
                        )
                        return "ILLQ_24h"

            # ========== 1h ==========
            if df_1h is not None and len(df_1h) > 0:
                min1h = int(self.rules.get("min_candles_1h", 60))
                if len(df_1h) < min1h:
                    self.ban_temp(
                        symbol,
                        float(self.rules.get("cooldown_hours_new_listing", 24)),
                        f"NEW_LISTING <{min1h}x1h",
                    )
                    return "NEW_LISTING_1h"

                atr1h = _atr_percent(df_1h, n=14)
                if atr1h > float(self.rules.get("max_atr_pct_1h", 12.0)):
                    self.ban_temp(
                        symbol,
                        float(self.rules.get("cooldown_hours_volatility", 12)),
                        f"HIGH_VOL_1h ATR%={atr1h:.1f}",
                    )
                    return "HIGH_VOL_1h"

        except Exception as ex:
            # Nunca travar o pipeline
            print(f"[blacklist] auto_from_candles error {symbol}: {ex}")

        return None


# --------- Helpers técnicos ---------
def _atr_percent(df: pd.DataFrame, n: int = 14) -> float:
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (pc - l).abs()))
    atr = tr.rolling(n, min_periods=n).mean()
    avg_price = c.rolling(n, min_periods=n).mean()
    val = float((atr.iloc[-1] / avg_price.iloc[-1]) * 100.0)
    return val


def _wickiness_pct(df: pd.DataFrame) -> float:
    d = df.copy()
    o = d["open"].astype(float)
    h = d["high"].astype(float)
    l = d["low"].astype(float)
    c = d["close"].astype(float)
    rng = (h - l).replace(0, np.nan)
    upper = (h - np.maximum(o, c)) / rng
    lower = (np.minimum(o, c) - l) / rng
    frac = ((upper + lower).clip(0, 1)).mean()
    return float(frac * 100.0)


def _body_frac_avg(df: pd.DataFrame) -> float:
    d = df.copy()
    o = d["open"].astype(float)
    h = d["high"].astype(float)
    l = d["low"].astype(float)
    c = d["close"].astype(float)
    rng = (h - l).replace(0, np.nan)
    body = (c - o).abs()
    body_frac = (body / rng).clip(0, 1).mean()  # fração [0..1]
    return float(body_frac)
