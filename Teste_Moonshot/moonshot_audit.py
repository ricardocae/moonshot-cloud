import os
import json, os, yaml
from datetime import datetime
import pandas as pd

CFG_FILE = "moonshot_config.yaml"

def load_cfg(path=CFG_FILE):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def parse_utc(s):
    if not s: return None
    s = s.replace(" UTC","").strip()
    fmts = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None

def main():
    cfg = load_cfg()
    trades_path = cfg.get("trades_file","moonshot_trades.json")
    stake = float(cfg.get("audit",{}).get("stake_usd", 30))
    out_csv = cfg.get("audit",{}).get("out_csv", "moonshot_audit.csv")
    out_json = cfg.get("audit",{}).get("out_json", "moonshot_audit.json")
    out_txt = cfg.get("audit",{}).get("out_txt", "moonshot_audit_summary.txt")

    if not os.path.exists(trades_path):
        print(f"Nenhum arquivo de trades encontrado: {trades_path}")
        return

    with open(trades_path,"r") as f:
        trades = json.load(f)

    rows = []
    for key, tr in trades.items():
        status = tr.get("status")
        if status not in ("CLOSED_TP3","STOP"):
            continue
        entry = float(tr.get("entry", 0))
        exit_price = float(tr.get("exit_price", entry))
        lev = float(tr.get("lev", 1))
        roi_pct = tr.get("roi_pct")
        if roi_pct is None:
            try:
                roi_pct = round(((exit_price - entry)/entry) * lev * 100, 4)
            except:
                roi_pct = 0.0
        pnl_usd = round(stake * (roi_pct/100.0), 4)

        def p(s): return s if s else None
        created_at = p(tr.get("created_at"))
        closed_at = p(tr.get("closed_at"))

        dur_min = None
        if created_at and closed_at:
            try:
                ca = parse_utc(created_at); cb = parse_utc(closed_at)
                if ca and cb:
                    dur_min = round((cb - ca).total_seconds()/60.0, 1)
            except:
                pass

        rows.append({
            "key": key, "symbol": tr.get("symbol"), "tf": tr.get("tf"),
            "created_at": created_at, "closed_at": closed_at,
            "duration_min": dur_min,
            "entry": entry, "exit": exit_price, "exit_reason": tr.get("exit_reason"),
            "lev": lev, "roi_pct": roi_pct, "stake_usd": stake, "pnl_usd": pnl_usd,
            "status": status
        })

    if not rows:
        print("Nenhum trade fechado para auditar ainda.")
        return

    df = pd.DataFrame(rows).sort_values("closed_at")
    total_trades = len(df)
    wins = int((df["pnl_usd"] > 0).sum())
    win_rate = round(100 * wins / total_trades, 2)
    avg_roi = round(df["roi_pct"].mean(), 4)
    total_pnl = round(df["pnl_usd"].sum(), 4)

    df.to_csv(out_csv, index=False)
    with open(out_json,"w") as f: json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(out_txt,"w") as f:
        f.write(
            f"Moonshot — Auditoria\n"
            f"Stake por trade: ${stake}\n"
            f"Trades fechados: {total_trades}\n"
            f"Win rate: {win_rate}%\n"
            f"ROI médio: {avg_roi}%\n"
            f"P/L total: ${total_pnl}\n"
        )
    print(f"OK: {out_csv}, {out_json}, {out_txt}")

if __name__ == "__main__":
    main()
