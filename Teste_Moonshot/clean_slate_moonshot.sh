#!/usr/bin/env bash
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
DIRS=("$HOME/Documents/Teste_Moonshot" "$HOME/Documents/Moonshot" "$HOME/Documents/Moonshot_agresivo")
BKDIR="$HOME/Documents/Backups_Moonshot"
mkdir -p "$BKDIR"

echo "[1/6] Matando processos e removendo locks..."
pkill -f "moonshot_agent.py" || true
pkill -f "open_trades_report_daemon.py" || true
pkill -f "report_trades_all_daemon.py" || true
pkill -f "tp_watcher_daemon.py" || true
pkill -f "trades_guard_daemon.py" || true
pkill -f "painel_signals.py" || true
pkill -f "start_moonshot.sh" || true
pkill -f "flask run" || true
rm -f /tmp/moonshot_agent.lock || true

echo "[2/6] Backup leve dos estados (antes de limpar)..."
tar -czf "$BKDIR/clean_bak_$TS.tgz" \
  $(for d in "${DIRS[@]}"; do
      [ -d "$d" ] && echo \
        "$d/moonshot_trades.json" \
        "$d/moonshot_trades_shadow.json" \
        "$d/moonshot_symbols.json" \
        "$d/blacklist.json" \
        "$d/positions.json" \
        "$d/open_trades.json" \
        "$d/recent_signals.json" \
        "$d/last_signals.json" \
        "$d/alerts_history.json" \
        "$d/nohup.out" \
        "$d/agent.out" \
        "$d/boot.out" \
        "$d/heartbeat.out" \
        "$d/logs";
    done) 2>/dev/null || true
echo "[backup] -> $BKDIR/clean_bak_$TS.tgz"

echo "[3/6] Limpando estados e logs..."
for d in "${DIRS[@]}"; do
  [ -d "$d" ] || continue
  cd "$d"
  rm -f moonshot_trades.json moonshot_trades_shadow.json \
        moonshot_symbols.json blacklist.json positions.json \
        open_trades.json recent_signals.json last_signals.json \
        alerts_history.json nohup.out agent.out boot.out heartbeat.out \
        *.lock *.pid || true
  rm -rf logs __pycache__ .cache || true
  mkdir -p logs
  echo "{}" > moonshot_trades.json
done
rm -f /tmp/moonshot_agent.lock || true

echo "[4/6] Ajustando .env_moonshot do Teste_Moonshot..."
ENV="$HOME/Documents/Teste_Moonshot/.env_moonshot"
if [ -f "$ENV" ]; then
  # usa só o arquivo local, remove agregados
  sed -i '' -E "s|^REPORT_TRADES_FILE=.*|REPORT_TRADES_FILE=$HOME/Documents/Teste_Moonshot/moonshot_trades.json|" "$ENV" || true
  sed -i '' -E "/^EXTRA_TRADES_FILES=/d" "$ENV" || true
  # TAG e frequência
  grep -q '^REPORT_TAG=' "$ENV" && sed -i '' -E "s|^REPORT_TAG=.*|REPORT_TAG=[TESTE]|" "$ENV" || echo "REPORT_TAG=[TESTE]" >> "$ENV"
  grep -q '^REPORT_EVERY_MIN=' "$ENV" && sed -i '' -E "s|^REPORT_EVERY_MIN=.*|REPORT_EVERY_MIN=10|" "$ENV" || echo "REPORT_EVERY_MIN=10" >> "$ENV"
fi

echo "[5/6] Zerando denylist/blacklist no YAML (PyYAML)..."
python3 - <<'PY'
import os, pathlib, json, sys
try:
    import yaml  # type: ignore
except Exception:
    import subprocess; subprocess.run([sys.executable,"-m","pip","install","-q","pyyaml"], check=False)
    import yaml  # type: ignore
dirs=[pathlib.Path(os.path.expanduser(p)) for p in [
    "~/Documents/Teste_Moonshot","~/Documents/Moonshot","~/Documents/Moonshot_agresivo"
]]
for d in dirs:
    y=d/"moonshot_config.yaml"
    if not y.exists(): continue
    cfg=yaml.safe_load(y.read_text()) or {}
    cfg["denylist"]= []
    blf = cfg.get("blacklist_file") or str(d/"blacklist.json")
    cfg["blacklist_file"]= blf
    (d/"blacklist.json").write_text("[]")
    y.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print(f"[yaml] limpo: {y}")
PY

echo "[6/6] Limpeza concluída."
for d in "${DIRS[@]}"; do
  [ -d "$d" ] || continue
  echo ">> $(basename "$d")"
  ls -lah "$d/moonshot_trades.json" || true
done
