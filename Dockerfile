FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 TZ=America/Sao_Paulo

# Web deps
RUN pip install --no-cache-dir Flask gunicorn
WORKDIR /app
COPY . /app
RUN python -m pip install --upgrade pip setuptools wheel &&     ( [ -f requirements.txt ] && pip install -r requirements.txt || true ) &&     pip install --no-cache-dir python-dotenv pyyaml requests pillow pandas numpy ta pandas_ta plotly
CMD ["python","-u","moonshot_agent.py"]
