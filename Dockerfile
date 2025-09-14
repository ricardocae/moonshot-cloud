FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo

WORKDIR /app
COPY . /app

RUN python -m pip install --upgrade pip setuptools wheel && \
    ( [ -f requirements.txt ] && pip install -r requirements.txt || true ) && \
    pip install --no-cache-dir \
      Flask==3.0.3 gunicorn==21.2.0 \
      python-telegram-bot==20.6 pyTelegramBotAPI==4.14.1 \
      ccxt==4.3.74 \
      python-dotenv==1.0.1 pyyaml==6.0.2 requests==2.32.3 pillow==10.4.0 \
      numpy==2.1.1 pandas==2.2.2 ta==0.10.2 plotly==5.22.0 \
      pandas-ta-openbb==0.4.22 && \
    python -c "import pandas_ta as ta; print('pandas_ta OK', getattr(ta,'__version__','unknown'))"

# O Render usa dockerCommand do render.yaml; CMD é só um default
CMD ["python","-u","Teste_Moonshot/moonshot_agent.py"]
