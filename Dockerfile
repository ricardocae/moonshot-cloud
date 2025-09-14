FROM python:3.11-slim

# Sistema (timezone + fontes) — evita erro de fontes e datas
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo

WORKDIR /app
COPY . /app

# Se houver requirements.txt, instala; depois garante libs-chave
RUN python -m pip install --upgrade pip setuptools wheel && \
    ( [ -f requirements.txt ] && pip install -r requirements.txt || true ) && \
    pip install --no-cache-dir \
      Flask gunicorn \
      python-telegram-bot pyTelegramBotAPI \
      ccxt \
      python-dotenv pyyaml requests pillow \
      pandas numpy pandas_ta ta plotly

# Padrão (os serviços do Render usam dockerCommand próprio)
CMD ["python","-u","Teste_Moonshot/moonshot_agent.py"]
