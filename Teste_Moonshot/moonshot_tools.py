# moonshot_tools.py
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# deps stdlib
try:
    from zoneinfo import ZoneInfo  # py>=3.9
except Exception:  # pragma: no cover
    ZoneInfo = None  # fallback p/ UTC se não houver

import yaml

# componentes do projeto
from moonshot_blacklist import AutoBlacklist
from moonshot_agent import fetch_instruments_page, load_json, save_json


# ==========================
# Config helpers
# ==========================
def load_cfg(path: str = "moonshot_config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_abl(cfg: dict) -> AutoBlacklist:
    bl = (cfg.get("blacklist") or {})
    return AutoBlacklist(
        path=bl.get("file", cfg.get("blacklist_file", "moonshot_blacklist.json")),
        rules=bl.get("rules", {}),
        hard_denylist=(bl.get("hard_denylist") or cfg.get("denylist") or []),
        enabled=bl.get("enabled", True),
    )


def get_tz(cfg: dict):
    tzname = cfg.get("display_timezone", "America/Sao_Paulo")
    if ZoneInfo:
        try:
            return ZoneInfo(tzname)
        except Exception:
            return ZoneInfo("UTC")
    return None  # sinaliza UTC puro


# ==========================
# Universo de símbolos elegíveis
# ==========================
def discover_symbols(cfg: dict, quote_override: Optional[str] = None,
                     use_cache: bool = False) -> List[str]:
    """
    Descobre Perpetuals em status Trading na Bybit, filtrando por quote/allowlist/etc.
    Se use_cache=True, tenta ler 'symbols_cache_file' antes.
    """
    if use_cache:
        syms = load_json(cfg.get("symbols_cache_file", "moonshot_symbols.json"), [])
        if syms:
            return sorted(set(s.upper().strip() for s in syms))

    cat = cfg.get("category", "linear")
    want_q = (quote_override or cfg.get("quote_coin") or "").upper().strip()
    allow = set(s.upper().strip() for s in (cfg.get("allowlist") or []))
    exclude_100000 = bool(cfg.get("exclude_100000", True))

    syms: List[str] = []
    cursor = None
    while True:
        page, cursor = fetch_instruments_page(cat, cursor)
        if not page:
            break
        for it in page:
            sym = (it.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if it.get("status") != "Trading":
                continue
            if "Perpetual" not in (it.get("contractType") or ""):
                continue
            q = (it.get("quoteCoin") or it.get("quoteCurrency") or "").upper()
            if want_q and q != want_q:
                continue
            if allow and sym not in allow:
                continue
            if exclude_100000 and sym.startswith("100000"):
                continue
            syms.append(sym)
        if not cursor:
            break
    return sorted(set(syms))


# ==========================
# Impressão / tabelas
# ==========================
def fmt_until_local(unix_ts: Optional[float], tz) -> str:
    if unix_ts is None:
        return "PERM"
    dt = datetime.utcfromtimestamp(float(unix_ts))
    if tz:
        try:
            return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def print_table(rows: List[List[str]], headers: List[str], max_rows: Optional[int] = None) -> None:
    # largura por coluna
    cols = list(zip(*([headers] + rows))) if rows else [headers]
    widths = [max(len(str(x)) for x in col) for col in cols]
    fmt = " | ".join("{:<" + str(w) + "}" for w in widths)

    print(fmt.format(*headers))
    print("-+-".join("-" * w for w in widths))
    count = 0
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))
        count += 1
        if max_rows and count >= max_rows:
            print(f"... ({len(rows)-count} mais)")
            break


# ==========================
# Operações
# ==========================
def op_list_blacklist(cfg: dict, limit: Optional[int] = None) -> None:
    abl = make_abl(cfg)
    removed = abl.cleanup()
    if removed:
        print(f"[cleanup] bans expirados removidos: {len(removed)}")

    tz = get_tz(cfg)
    rows: List[List[str]] = []

    # hard denylist (yaml)
    hard = set(s.upper().strip() for s in (cfg.get("denylist") or []))
    hard |= set(getattr(abl, "hard_denylist", set()))

    # dinâmico (json)
    for sym, e in sorted(abl.db.items()):
        rows.append([sym, "dynamic", e.reason, e.strikes, fmt_until_local(e.until, tz)])

    # itens hard (que não estão no dinâmico)
    for sym in sorted(hard - set(abl.db.keys())):
        rows.append([sym, "hard", "hard_denylist", 0, "PERM"])

    if not rows:
        print("Nenhum símbolo na blacklist.")
        return

    print_table(rows, headers=["symbol", "type", "reason", "strikes", "until_local"], max_rows=limit)


def op_list_free(cfg: dict, quote: Optional[str], limit: Optional[int], use_cache: bool) -> None:
    abl = make_abl(cfg)
    abl.cleanup()
    syms = discover_symbols(cfg, quote_override=quote, use_cache=use_cache)
    free = []
    for s in syms:
        blocked, why = abl.is_blocked(s)
        if not blocked:
            free.append(s)
    print(f"Total elegíveis: {len(syms)} | Não-blacklisted: {len(free)}")
    rows = [[s] for s in free]
    if rows:
        print_table(rows, headers=["symbol"], max_rows=limit)
    else:
        print("Nenhum símbolo livre dentro dos filtros atuais.")


def op_export(cfg: dict, quote: Optional[str], use_cache: bool) -> None:
    abl = make_abl(cfg)
    abl.cleanup()
    tz = get_tz(cfg)

    syms = discover_symbols(cfg, quote_override=quote, use_cache=use_cache)
    blocked: List[Tuple[str, str]] = []
    free: List[str] = []
    for s in syms:
        b, why = abl.is_blocked(s)
        if b:
            blocked.append((s, why))
        else:
            free.append(s)

    # arquivos
    with open("blacklist_current.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "type", "reason", "strikes", "until_local"])
        hard = set(s.upper().strip() for s in (cfg.get("denylist") or []))
        hard |= set(getattr(abl, "hard_denylist", set()))
        # dinâmico
        for s, e in sorted(abl.db.items()):
            w.writerow([s, "dynamic", e.reason, e.strikes, fmt_until_local(e.until, tz)])
        # hard-only
        for s in sorted(hard - set(abl.db.keys())):
            w.writerow([s, "hard", "hard_denylist", 0, "PERM"])

    with open("blacklist_dynamic.txt", "w", encoding="utf-8") as f:
        for s, e in sorted(abl.db.items()):
            f.write(f"{s},{e.reason},{e.strikes},{fmt_until_local(e.until, tz)}\n")

    with open("blacklist_hard.txt", "w", encoding="utf-8") as f:
        hard = set(s.upper().strip() for s in (cfg.get("denylist") or []))
        hard |= set(getattr(abl, "hard_denylist", set()))
        for s in sorted(hard):
            f.write(s + "\n")

    with open("not_blacklisted.txt", "w", encoding="utf-8") as f:
        for s in sorted(free):
            f.write(s + "\n")

    print("Arquivos gerados:")
    print(" - blacklist_current.csv")
    print(" - blacklist_dynamic.txt")
    print(" - blacklist_hard.txt")
    print(" - not_blacklisted.txt")
    print(f"(universo filtrado por quote={'ANY' if not quote else quote})")


def op_cleanup(cfg: dict) -> None:
    abl = make_abl(cfg)
    removed = abl.cleanup()
    if removed:
        print("Removidos:", ", ".join(sorted(removed)))
    else:
        print("Nada para limpar (nenhum ban expirado).")


def op_ban_temp(cfg: dict, symbol: str, hours: float, reason: str) -> None:
    abl = make_abl(cfg)
    abl.ban_temp(symbol, hours, reason or "manual")
    print(f"OK: ban_temp {symbol.upper()} por {hours}h — reason='{reason or 'manual'}'")


def op_ban_perm(cfg: dict, symbol: str, reason: str) -> None:
    abl = make_abl(cfg)
    abl.ban_perm(symbol, reason or "permanent")
    print(f"OK: ban_perm {symbol.upper()} — reason='{reason or 'permanent'}'")


def op_unban(cfg: dict, symbol: str) -> None:
    abl = make_abl(cfg)
    abl.unban(symbol)
    print(f"OK: unban {symbol.upper()}")


def op_stats(cfg: dict, quote: Optional[str], use_cache: bool) -> None:
    abl = make_abl(cfg)
    abl.cleanup()
    syms = discover_symbols(cfg, quote_override=quote, use_cache=use_cache)
    hard = set(s.upper().strip() for s in (cfg.get("denylist") or []))
    hard |= set(getattr(abl, "hard_denylist", set()))
    dyn = set(abl.db.keys())
    blocked = [s for s in syms if abl.is_blocked(s)[0]]

    print("=== Stats ===")
    print(f"Universo (Perp/Trading, quote={quote or cfg.get('quote_coin','ANY')}): {len(syms)}")
    print(f"Blacklisted (no universo): {len(blocked)}")
    print(f" - Dinâmicos (arquivo): {len(dyn & set(syms))}")
    print(f" - Hard (YAML):         {len((hard & set(syms)) - dyn)}")
    print(f"Não-blacklisted:         {len(syms) - len(blocked)}")


# ==========================
# CLI
# ==========================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="moonshot_tools",
        description="Ferramentas auxiliares do projeto Moonshot (blacklist e universo de símbolos).",
    )
    p.add_argument("--cfg", default="moonshot_config.yaml", help="Caminho do YAML de config (padrão: moonshot_config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("list-blacklist", help="Lista tudo que está na blacklist (dinâmica + hard).")
    s1.add_argument("--limit", type=int, default=None, help="Limite de linhas no print")

    s2 = sub.add_parser("list-free", help="Lista universo de símbolos elegíveis que NÃO estão na blacklist.")
    s2.add_argument("--quote", default=None, help="Filtrar por quote (ex.: USDT). Se omitido, usa do YAML.")
    s2.add_argument("--limit", type=int, default=None, help="Limite de linhas no print")
    s2.add_argument("--use-cache", action="store_true", help="Tentar usar symbols_cache_file em vez de varrer a Bybit")

    s3 = sub.add_parser("export", help="Gera arquivos: blacklist_current.csv, blacklist_dynamic.txt, blacklist_hard.txt, not_blacklisted.txt.")
    s3.add_argument("--quote", default=None, help="Filtrar por quote (ex.: USDT).")
    s3.add_argument("--use-cache", action="store_true", help="Tentar usar symbols_cache_file")

    s4 = sub.add_parser("cleanup", help="Remove bans expirados do arquivo de blacklist dinâmica.")

    s5 = sub.add_parser("ban-temp", help="Banir temporariamente um símbolo.")
    s5.add_argument("symbol")
    s5.add_argument("--hours", type=float, required=True, help="Horas de ban")
    s5.add_argument("--reason", default="manual", help="Motivo")

    s6 = sub.add_parser("ban-perm", help="Banir permanentemente um símbolo.")
    s6.add_argument("symbol")
    s6.add_argument("--reason", default="permanent", help="Motivo")

    s7 = sub.add_parser("unban", help="Remover um símbolo da blacklist dinâmica.")
    s7.add_argument("symbol")

    s8 = sub.add_parser("stats", help="Resumo estatístico do universo e da blacklist.")
    s8.add_argument("--quote", default=None, help="Filtrar por quote (ex.: USDT).")
    s8.add_argument("--use-cache", action="store_true", help="Tentar usar symbols_cache_file")

    return p


def main():
    args = build_parser().parse_args()
    cfg = load_cfg(args.cfg)

    if args.cmd == "list-blacklist":
        op_list_blacklist(cfg, limit=args.limit)
    elif args.cmd == "list-free":
        op_list_free(cfg, quote=args.quote, limit=args.limit, use_cache=args.use_cache)
    elif args.cmd == "export":
        op_export(cfg, quote=args.quote, use_cache=args.use_cache)
    elif args.cmd == "cleanup":
        op_cleanup(cfg)
    elif args.cmd == "ban-temp":
        op_ban_temp(cfg, symbol=args.symbol, hours=args.hours, reason=args.reason)
    elif args.cmd == "ban-perm":
        op_ban_perm(cfg, symbol=args.symbol, reason=args.reason)
    elif args.cmd == "unban":
        op_unban(cfg, symbol=args.symbol)
    elif args.cmd == "stats":
        op_stats(cfg, quote=args.quote, use_cache=args.use_cache)
    else:
        raise SystemExit("comando desconhecido")


if __name__ == "__main__":
    main()
