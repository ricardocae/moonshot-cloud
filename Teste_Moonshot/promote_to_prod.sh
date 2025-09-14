#!/usr/bin/env bash
set -euo pipefail

SRC="$HOME/Documents/Teste_Moonshot"
DEST="$HOME/Documents/Moonshot"
BACKUP_DIR="$HOME/Documents/Backups_Moonshot"
TS=$(date +%Y%m%d_%H%M%S)
DRY=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY=1
  echo "[promote] Modo DRY-RUN (prévia). Nada será alterado."
fi

[[ -d "$SRC" ]]  || { echo "SRC não existe: $SRC"; exit 1; }
[[ -d "$DEST" ]] || { echo "DEST não existe: $DEST"; exit 1; }
mkdir -p "$BACKUP_DIR"

echo "[1/5] Parando serviços no PROD..."
pkill -f "moonshot_agent.py" || true
pkill -f "open_trades_report_daemon.py" || true
pkill -f "tp_watcher_daemon.py" || true
pkill -f "trades_guard_daemon.py" || true
pkill -f "report_trades_all_daemon.py" || true
rm -f /tmp/moonshot_agent.lock || true

echo "[2/5] Backup do PROD..."
tar -czf "$BACKUP_DIR/prod_backup_$TS.tgz" -C "$DEST" . || true
echo "   -> $BACKUP_DIR/prod_backup_$TS.tgz"

echo "[3/5] Sincronizando código DEV → PROD (rsync)..."
RSYNC_BASE=(-aHv --delete --exclude-from="$SRC/.deployignore")
if [[ $DRY -eq 1 ]]; then
  rsync -n "${RSYNC_BASE[@]}" "$SRC/" "$DEST/"
else
  rsync    "${RSYNC_BASE[@]}" "$SRC/" "$DEST/"
fi

# Garante que o .env do PROD permaneça (caso não exista, cria um exemplo)
if [[ ! -f "$DEST/.env_moonshot" ]]; then
  cat > "$DEST/.env_moonshot" <<'ENV'
# Preencha com suas credenciais do PROD
REPORT_TAG=[PROD]
REPORT_TRADES_FILE=/Users/ricardo/Documents/Moonshot/moonshot_trades.json
REPORT_EVERY_MIN=10
REPORT_ONLY_IF_CHANGED=1
TZ=America/Sao_Paulo
ENV
  echo "[warn] .env_moonshot não existia no PROD — criei um template básico."
fi

echo "[4/5] Instalando dependências no PROD..."
cd "$DEST"
python3 -m pip install -q -r requirements.txt || true

echo "[5/5] Iniciando serviços no PROD..."
chmod +x start_prod.sh || true
./start_prod.sh

echo "[OK] Deploy concluído."
