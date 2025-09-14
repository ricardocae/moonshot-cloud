FROM python:3.11-slim

# deps de sistema + git (por segurança) + fontes/TZ
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata fonts-dejavu-core git \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    TZ=America/Sao_Paulo

WORKDIR /app
COPY . /app

# libs fixadas + pandas-ta com 3 fallbacks (PyPI -> tag ZIP -> master ZIP)
RUN python -m pip install --upgrade pip setuptools wheel && \
    ( [ -f requirements.txt ] && pip install -r requirements.txt || true ) && \
    pip install --no-cache-dir \
      Flask==3.0.3 gunicorn==21.2.0 \
      python-telegram-bot==20.6 pyTelegramBotAPI==4.14.1 \
      ccxt==4.3.74 \
      python-dotenv==1.0.1 pyyaml==6.0.2 requests==2.32.3 pillow==10.4.0 \
      numpy==2.1.1 pandas==2.2.2 ta==0.10.2 plotly==5.22.0 && \
    ( pip install --no-cache-dir pandas-ta==0.3.14b0 \
      || pip install --no-cache-dir \
           "pandas_ta @ https://codeload.github.com/twopirllc/pandas-ta/zip/refs/tags/0.3.14b0" \
      || pip install --no-cache-dir \
           "pandas_ta @ https://codeload.github.com/twopirllc/pandas-ta/zip/refs/heads/master" )

# (o Render usa dockerCommand do render.yaml; CMD é só default)
CMD ["python","-u","Teste_Moonshot/moonshot_agent.py"]
