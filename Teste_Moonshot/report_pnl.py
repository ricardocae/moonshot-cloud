import os
#!/usr/bin/env python3
# Relatório de PnL do #moonshot
# - Considera parciais TP1/TP2 (splits)
# - Calcula R POR TRADE (baseline = |TP1 - Entry| sobre o notional)
# - Aplica TAXAS (entry/exit em bps) e SLIPPAGE (entry/exit em bps)
# - Sumários por PAR (symbol) e por TIMEFRAME
# - Exporta CSV por trade e CSVs agregados
#
# Exemplo:
#   python3 report_pnl.py --tz America/Sao_Paulo \
#     --csv pnl_trades.csv --csv-group-prefix pnl_ \
#     --entry-fee-bps 6 --exit-fee-bps 6 \
#     --entry-slip-bps 1 --exit-slip-bps 1
#
# YAML opcional (valores padrão):
#   tp_splits: [0.33, 0.33, 0.34]
#   fees: { entry_bps: 6.0, exit_bps: 6.0 }
#   slippage_bps: { entry: 1.0, exit: 1.0 }

import argparse, json, os, csv, statistics
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

try:
    import yaml
except Exception as e:
    raise SystemExit("Instale pyyaml:  pip3 install pyyaml") from e


# ------------------ helpers de IO ------------------
def load_cfg(path="moonshot_config.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config não encontrado: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_trades(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Trades não encontrado: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_utc_dt(s: str):
    if not s:
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S UTC")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def pct(x):   return f"{x:.2f}%"
def money(x): return f"{'-' if x < 0 else ''}${abs(x):,.2f}"


# ------------------ preços / updates ------------------
def get_update_price(updates, event_key, fallback=None):
    """Busca preço real salvo no update (TP1/TP2/TP3); senão, usa fallback."""
    if not isinstance(updates, list):
        return fallback, False
    for u in updates:
        if str(u.get("event")).upper() == event_key.upper():
            try:
                return float(u.get("price")), True
            except Exception:
                return fallback, True
    return fallback, False


# ------------------ slippage & taxas ------------------
def adj_entry_price(side: str, entry: float, slip_bps: float) -> float:
    # slippage adverso
    fac = (slip_bps or 0.0) / 10000.0
    if side.upper() == "LONG":
        return entry * (1.0 + fac)   # entra um pouco mais caro
    else:
        return entry * (1.0 - fac)   # vende um pouco mais barato

def adj_exit_price(side: str, exit_px: float, slip_bps: float) -> float:
    fac = (slip_bps or 0.0) / 10000.0
    if side.upper() == "LONG":
        return exit_px * (1.0 - fac)  # sai um pouco mais barato
    else:
        return exit_px * (1.0 + fac)  # recompra um pouco mais caro

def fee_usdt(notional_leg: float, fee_bps: float) -> float:
    return (notional_leg or 0.0) * (fee_bps or 0.0) / 10000.0


# ------------------ PnL por componente ------------------
def pnl_component(notional, entry_eff, exit_eff, side, frac):
    """
    PnL e ROI% (sobre notional da perna) para um pedaço 'frac' da posição.
    entry_eff/exit_eff já devem vir com slippage aplicado (se desejado).
    """
    if frac <= 0: 
        return 0.0, 0.0
    direction = 1.0 if side.upper() == "LONG" else -1.0
    move = (exit_eff - entry_eff) / max(entry_eff, 1e-12)
    pnl_usdt = notional * frac * direction * move
    roi_pct_notional = 100.0 * frac * direction * move
    return pnl_usdt, roi_pct_notional


# ------------------ PnL com parciais, taxas e slippage ------------------
def compute_trade_pnl_with_partials(tr, splits, fees, slip, slip_on_updates=False):
    """
    Retorna:
      pnl_gross_usdt, fees_usdt_total, pnl_net_usdt, roi_pct_net, parts[]
    Lógica:
      - Aplica slippage no ENTRY sempre.
      - Para TP/STOP: se houver preço de update e slip_on_updates=False, usa o preço do update.
        Caso contrário, aplica slippage adverso também na saída.
      - Taxas:
         * Entry fee sobre 100% do notional.
         * Exit fee por perna (TP1/TP2/final) sobre notional*frac.
    """
    side    = tr.get("side", "LONG")
    entry   = float(tr.get("entry", 0.0))
    exit_p  = float(tr.get("exit_price", entry))
    notional= float(tr.get("notional", 0.0))
    updates = tr.get("updates", [])

    # alvos base (fallbacks)
    tp1_fb = float(tr.get("tp1", entry))
    tp2_fb = float(tr.get("tp2", entry))
    tp3_fb = float(tr.get("tp3", exit_p or entry))

    # preços de updates (se houver)
    tp1_price, tp1_seen = get_update_price(updates, "TP1", tp1_fb)
    tp2_price, tp2_seen = get_update_price(updates, "TP2", tp2_fb)
    tp3_price, tp3_seen = get_update_price(updates, "TP3", tp3_fb)

    # splits
    s1, s2, s3 = splits
    s1 = max(0.0, float(s1)); s2 = max(0.0, float(s2)); s3 = max(0.0, float(s3))
    total = s1 + s2 + s3
    if total == 0:
        s1 = 0.33; s2 = 0.33; s3 = 0.34
    elif total > 1.0:
        s1, s2, s3 = [x/total for x in (s1, s2, s3)]

    # slippage no entry (sempre adverso)
    entry_eff = adj_entry_price(side, entry, slip["entry_bps"])

    parts = []
    pnl_gross = 0.0
    roi_gross = 0.0
    realized = 0.0

    # TP1 parcial
    if tp1_seen:
        exit_eff = tp1_price if not slip_on_updates else adj_exit_price(side, tp1_price, slip["exit_bps"])
        pnl, roi = pnl_component(notional, entry_eff, exit_eff, side, s1)
        parts.append({"name":"TP1","frac":s1,"price":exit_eff,"pnl":pnl,"roi_pct":roi})
        pnl_gross += pnl; roi_gross += roi; realized += s1

    # TP2 parcial
    if tp2_seen:
        exit_eff = tp2_price if not slip_on_updates else adj_exit_price(side, tp2_price, slip["exit_bps"])
        pnl, roi = pnl_component(notional, entry_eff, exit_eff, side, s2)
        parts.append({"name":"TP2","frac":s2,"price":exit_eff,"pnl":pnl,"roi_pct":roi})
        pnl_gross += pnl; roi_gross += roi; realized += s2

    # Restante fecha no final
    remaining = max(0.0, 1.0 - realized)
    # decide preço final
    status = tr.get("status","")
    if status == "CLOSED_TP3":
        raw_exit = tp3_price if tp3_seen else tp3_fb
        name = "TP3"
    elif status == "STOP":
        raw_exit = exit_p
        name = "STOP/BE"
    else:
        raw_exit = exit_p or tp3_fb
        name = "CLOSE"

    if remaining > 0:
        exit_eff = raw_exit if (tp3_seen and not slip_on_updates) else adj_exit_price(side, raw_exit, slip["exit_bps"])
        pnl, roi = pnl_component(notional, entry_eff, exit_eff, side, remaining)
        parts.append({"name":name,"frac":remaining,"price":exit_eff,"pnl":pnl,"roi_pct":roi})
        pnl_gross += pnl; roi_gross += roi

    # Taxas: entry (100% notional) + exit por partes
    fees_total = 0.0
    fees_total += fee_usdt(notional, fees["entry_bps"])
    for p in parts:
        fees_total += fee_usdt(notional * p["frac"], fees["exit_bps"])

    pnl_net = pnl_gross - fees_total
    roi_net = 100.0 * (pnl_net / max(notional, 1e-12))
    return {
        "pnl_gross_usdt": pnl_gross,
        "fees_usdt_total": fees_total,
        "pnl_net_usdt": pnl_net,
        "roi_pct_net": roi_net,
        "parts": parts
    }


# ------------------ R por trade ------------------
def r_usdt_per_trade(tr):
    """R em USDT por trade: notional * |TP1 - Entry| / Entry."""
    entry   = float(tr.get("entry", 0.0))
    tp1     = float(tr.get("tp1", entry))
    notional= float(tr.get("notional", 0.0))
    base = abs(tp1 - entry) / max(entry, 1e-12)
    return notional * base


# ------------------ CLI ------------------
def main():
    ap = argparse.ArgumentParser(description="Relatório de PnL do Moonshot (parciais + R por trade + taxas/slippage + sumários)")
    ap.add_argument("--cfg", default="moonshot_config.yaml")
    ap.add_argument("--tz", default=None, help="ex.: America/Sao_Paulo")
    ap.add_argument("--csv", default=None, help="exporta CSV por trade (opcional)")
    ap.add_argument("--csv-group-prefix", default=None, help="prefixo para salvar pnl_symbol.csv e pnl_tf.csv")
    ap.add_argument("--days", type=int, default=None, help="considerar apenas os últimos N dias (opcional)")
    ap.add_argument("--splits", nargs=3, type=float, default=None, metavar=("S1","S2","S3"),
                    help="frações TP1/TP2/Final (ex.: 0.33 0.33 0.34)")
    ap.add_argument("--entry-fee-bps", type=float, default=None)
    ap.add_argument("--exit-fee-bps", type=float, default=None)
    ap.add_argument("--entry-slip-bps", type=float, default=None)
    ap.add_argument("--exit-slip-bps", type=float, default=None)
    ap.add_argument("--slip-on-updates", action="store_true",
                    help="aplica slippage também em preços capturados nos updates de TP/STOP")
    args = ap.parse_args()

    cfg = load_cfg(args.cfg)
    trades_path = cfg.get("trades_file", "moonshot_trades.json")

    tzname = args.tz or cfg.get("display_timezone", "UTC")
    try:
        tz = ZoneInfo(tzname)
    except Exception:
        tz = ZoneInfo("UTC"); tzname = "UTC"

    # splits: CLI > YAML > default
    splits = args.splits
    if splits is None:
        splits = cfg.get("tp_splits", [0.33, 0.33, 0.34])
    if len(splits) != 3:
        splits = [0.33, 0.33, 0.34]

    # taxas/slippage: CLI > YAML > default
    fees_cfg = cfg.get("fees", {})
    slip_cfg = cfg.get("slippage_bps", {})
    fees = {
        "entry_bps": args.entry_fee_bps if args.entry_fee_bps is not None else float(fees_cfg.get("entry_bps", 6.0)),
        "exit_bps":  args.exit_fee_bps  if args.exit_fee_bps  is not None else float(fees_cfg.get("exit_bps",  6.0)),
    }
    slip = {
        "entry_bps": args.entry_slip_bps if args.entry_slip_bps is not None else float(slip_cfg.get("entry", 1.0)),
        "exit_bps":  args.exit_slip_bps  if args.exit_slip_bps  is not None else float(slip_cfg.get("exit",  1.0)),
    }

    trades_dict = load_trades(trades_path)
    rows = []

    # -------------- processa trades --------------
    for key, tr in trades_dict.items():
        status = tr.get("status", "")
        if status not in ("CLOSED_TP3", "STOP"):
            continue  # só fechados

        sym = tr.get("symbol"); tf = tr.get("tf"); side = tr.get("side", "LONG")
        entry = float(tr.get("entry", 0.0))
        exit_price = float(tr.get("exit_price", entry))
        notional = float(tr.get("notional", 0.0))

        comp = compute_trade_pnl_with_partials(tr, splits, fees, slip, slip_on_updates=args.slip_on_updates)
        pnl_net = comp["pnl_net_usdt"]
        pnl_gross = comp["pnl_gross_usdt"]
        fees_usdt = comp["fees_usdt_total"]

        R_usdt = r_usdt_per_trade(tr)
        pnl_R  = pnl_net / R_usdt if R_usdt > 0 else 0.0

        closed_at = parse_utc_dt(tr.get("closed_at", ""))
        if closed_at:
            local_dt = closed_at.astimezone(tz)
            day_key = local_dt.strftime("%Y-%m-%d")
            closed_label = local_dt.strftime("%Y-%m-%d %H:%M %Z")
        else:
            day_key = "N/A"; closed_label = "N/A"

        rows.append({
            "day": day_key,
            "symbol": sym, "tf": tf, "side": side, "status": status, "exit_reason": tr.get("exit_reason",""),
            "created_at": tr.get("created_at",""), "closed_at": closed_label,
            "entry": entry, "exit": exit_price, "notional": notional,
            "pnl_gross": pnl_gross, "fees": fees_usdt, "pnl_net": pnl_net,
            "R_usdt": R_usdt, "pnl_R": pnl_R
        })

    if not rows:
        print("Nenhum trade fechado encontrado.")
        return

    # filtro últimos N dias
    if args.days:
        all_days = sorted({r["day"] for r in rows if r["day"] != "N/A"})
        if all_days:
            cutoff = set(all_days[-args.days:])
            rows = [r for r in rows if r["day"] in cutoff or r["day"] == "N/A"]

    # -------------- agregações globais --------------
    closed = len(rows)
    wins = sum(1 for r in rows if r["pnl_net"] > 0)
    losses = sum(1 for r in rows if r["pnl_net"] < 0)
    ties = closed - wins - losses
    winrate = (wins / closed * 100.0) if closed > 0 else 0.0

    gross_win = sum(r["pnl_gross"] for r in rows if r["pnl_gross"] > 0)
    gross_loss = sum(r["pnl_gross"] for r in rows if r["pnl_gross"] < 0)
    fees_total = sum(r["fees"] for r in rows)
    net = sum(r["pnl_net"] for r in rows)

    total_R = sum(r["pnl_R"] for r in rows)
    R_list = [r["pnl_R"] for r in rows]
    avg_R = statistics.mean(R_list) if R_list else 0.0
    med_R = statistics.median(R_list) if R_list else 0.0

    # por dia (NET)
    by_day = defaultdict(float)
    for r in rows:
        by_day[r["day"]] += r["pnl_net"]

    # por symbol e por timeframe (NET e R)
    by_symbol = defaultdict(lambda: {"net":0.0,"R":0.0,"wins":0,"losses":0,"count":0})
    by_tf = defaultdict(lambda: {"net":0.0,"R":0.0,"wins":0,"losses":0,"count":0})
    for r in rows:
        s = by_symbol[r["symbol"]]
        s["net"] += r["pnl_net"]; s["R"] += r["pnl_R"]; s["count"] += 1
        if r["pnl_net"] > 0: s["wins"] += 1
        elif r["pnl_net"] < 0: s["losses"] += 1
        t = by_tf[r["tf"]]
        t["net"] += r["pnl_net"]; t["R"] += r["pnl_R"]; t["count"] += 1
        if r["pnl_net"] > 0: t["wins"] += 1
        elif r["pnl_net"] < 0: t["losses"] += 1

    # -------------- impressão --------------
    print("\n==== Moonshot PnL Report (parciais + R por trade + taxas/slippage) ====")
    print(f"Fuso: {tzname}")
    print(f"Splits: TP1={splits[0]:.2f}  TP2={splits[1]:.2f}  Final={splits[2]:.2f}")
    print(f"Taxas (bps): entry={fees['entry_bps']}  exit={fees['exit_bps']}  |  Slippage (bps): entry={slip['entry_bps']}  exit={slip['exit_bps']}")
    print(f"Trades fechados: {closed}  |  Wins: {wins}  Losses: {losses}  Ties: {ties}  |  Win rate: {pct(winrate)}")
    print(f"Gross Win:  {money(gross_win)}")
    print(f"Gross Loss: {money(gross_loss)}")
    print(f"Taxas:      {money(-fees_total)}")
    print(f"NET:        {money(net)}")
    print(f"Total R: {total_R:.2f}R  |  Avg R/trade: {avg_R:.2f}R  |  Median R/trade: {med_R:.2f}R")

    print("\nPor dia (NET):")
    for d in sorted(by_day.keys()):
        print(f"  {d}: {money(by_day[d])}")

    # Top/bottom por símbolo
    top_sym = sorted(by_symbol.items(), key=lambda kv: kv[1]["net"], reverse=True)[:10]
    bot_sym = sorted(by_symbol.items(), key=lambda kv: kv[1]["net"])[:10]
    print("\nTop 10 pares (NET):")
    for sym, v in top_sym:
        wr = (v["wins"] / v["count"] * 100.0) if v["count"] else 0.0
        print(f"  {sym:12} NET={money(v['net']):>12} | R={v['R']:+.2f}R | WR={wr:5.1f}% | n={v['count']}")
    print("\nBottom 10 pares (NET):")
    for sym, v in bot_sym:
        wr = (v["wins"] / v["count"] * 100.0) if v["count"] else 0.0
        print(f"  {sym:12} NET={money(v['net']):>12} | R={v['R']:+.2f}R | WR={wr:5.1f}% | n={v['count']}")

    # Por timeframe
    print("\nPor timeframe (NET):")
    for tf, v in sorted(by_tf.items(), key=lambda kv: int(kv[0])):
        wr = (v["wins"] / v["count"] * 100.0) if v["count"] else 0.0
        print(f"  {tf:>3}m   NET={money(v['net']):>12} | R={v['R']:+.2f}R | WR={wr:5.1f}% | n={v['count']}")

    # -------------- CSVs --------------
    if args.csv:
        fields = [
            "day","symbol","tf","side","status","exit_reason","created_at","closed_at",
            "entry","exit","notional","pnl_gross","fees","pnl_net","R_usdt","pnl_R"
        ]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k,"") for k in fields})
        print(f"\nCSV (trades) salvo em: {os.path.abspath(args.csv)}")

    if args.csv_group_prefix:
        # por símbolo
        sym_path = f"{args.csv_group_prefix.rstrip('_')}_symbol.csv"
        with open(sym_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["symbol","net_usdt","total_R","wins","losses","count","winrate_pct"])
            for sym, v in sorted(by_symbol.items()):
                wr = (v["wins"]/v["count"]*100.0) if v["count"] else 0.0
                w.writerow([sym, round(v["net"],2), round(v["R"],4), v["wins"], v["losses"], v["count"], round(wr,2)])
        # por timeframe
        tf_path = f"{args.csv_group_prefix.rstrip('_')}_tf.csv"
        with open(tf_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timeframe_m","net_usdt","total_R","wins","losses","count","winrate_pct"])
            for tf, v in sorted(by_tf.items(), key=lambda kv: int(kv[0])):
                wr = (v["wins"]/v["count"]*100.0) if v["count"] else 0.0
                w.writerow([tf, round(v["net"],2), round(v["R"],4), v["wins"], v["losses"], v["count"], round(wr,2)])
        print(f"CSVs de grupos salvos em: {os.path.abspath(sym_path)} ; {os.path.abspath(tf_path)}")


if __name__ == "__main__":
    main()
