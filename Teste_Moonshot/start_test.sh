#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"
PY="$SCRIPT_DIR/.venv/bin/python"
PIP="$SCRIPT_DIR/.venv/bin/pip"

# Carrega APENAS o .env.test
if [[ -f ".env.test" ]]; then
  set -a; source ./.env.test; set +a
else
  echo "[ERRO] .env.test não encontrado em $SCRIPT_DIR"
  exit 1
fi

# Normaliza nomes
export TELEGRAM_TOKEN="${TELEGRAM_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_TOKEN:-}}"

# Venv / Pillow check
if [[ ! -x "$PY" ]]; then
  echo "[ERRO] venv do TESTE não encontrado."
  echo "Rode: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
"$PY" - <<'PY'
try:
    import PIL
    print("[CHECK][DEV] Pillow OK:", PIL.__version__)
except Exception as e:
    import sys
    print("[CHECK][DEV] Pillow faltando:", e)
    sys.exit(2)
PY

# Lock e log exclusivos do TESTE
LOCK="/tmp/teste_moonshot_agent.lock"
if [[ -e "$LOCK" ]]; then
  echo "[AVISO][DEV] lockfile existe ($LOCK). Verificando..."
  if ps -p "$(cat "$LOCK")" > /dev/null 2>&1; then
    echo "[ERRO][DEV] Já existe Teste_Moonshot rodando (PID $(cat "$LOCK"))."
    exit 1
  else
    echo "[INFO][DEV] Lock antigo; removendo."
    rm -f "$LOCK"
  fi
fi

LOGFILE="$SCRIPT_DIR/moonshot_test.out"
echo "[INFO][DEV] Iniciando Teste_Moonshot..."
"$PY" moonshot_agent.py >> "$LOGFILE" 2>&1 &
PID=$!
echo "$PID" > "$LOCK"
echo "[OK][DEV] Rodando. PID=$PID | Log: $LOGFILE"
