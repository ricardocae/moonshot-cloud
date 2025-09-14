#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moonshot Heartbeat
- Carrega credenciais automaticamente de .env (sem precisar 'source')
- Suporta CLI (--token, --chat-id, --every, --env-file, --one-shot, --msg, --boot-msg, --tag)
- Intervalos em segundos ou com sufixo (e.g., 30s, 15m, 6h, 1d)

Prioridade de configuração (da +alta p/ +baixa):
1) CLI
2) Variáveis de ambiente atuais (processo)
3) Arquivo .env (padrão: .env_moonshot, fallback .env)
"""
import argparse
import os
import time
from datetime import datetime
from typing import Dict, Tuple

import json
import requests
from pathlib import Path

def parse_duration(s: str) -> int:
    """Aceita '3600' ou '30s', '15m', '6h', '1d'."""
    s = (s or "").strip().lower()
    if not s:
        return 21600
    if s.isdigit():
        return int(s)
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    num = ''.join(ch for ch in s if ch.isdigit())
    unit = ''.join(ch for ch in s if ch.isalpha()) or 's'
    if not num or unit not in units:
        raise ValueError(f"Duração inválida: {s}")
    return int(num) * units[unit]

def load_dotenv_file(path: Path) -> Dict[str, str]:
    """
    Carrega chaves simples de um .env:
    - Suporta linhas 'export KEY=VAL' ou 'KEY=VAL'
    - Ignora comentários (#) e aspas externas
    - NÃO executa nada (seguro)
    """
    env = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        env[k] = v
    return env

def resolve_config(args) -> Tuple[str, str, int, str, str]:
    """
    Resolve TOKEN, CHAT_ID, EVERY, BOOT_MSG, MSG usando a prioridade descrita.
    """
    # 1) base: process env
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    every = os.getenv("MOONSHOT_HEARTBEAT_EVERY", "").strip()
    boot_msg = os.getenv("MOONSHOT_HEARTBEAT_BOOT_MSG", "🟢 Moonshot heartbeat iniciado.")
    msg = os.getenv("MOONSHOT_HEARTBEAT_MSG", "✅ Heartbeat — {now}")
    tag = os.getenv("MOONSHOT_HEARTBEAT_TAG", "").strip()

    # 2) .env (se existir)
    env_file = Path(args.env_file) if args.env_file else None
    if env_file is None:
        # tenta .env_moonshot, depois .env
        for candidate in (Path(".env_moonshot"), Path(".env")):
            if candidate.exists():
                env_file = candidate
                break
    if env_file and env_file.exists():
        file_env = load_dotenv_file(env_file)
        token = token or file_env.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = chat_id or file_env.get("TELEGRAM_CHAT_ID", "").strip()
        every = every or file_env.get("MOONSHOT_HEARTBEAT_EVERY", "").strip()
        boot_msg = file_env.get("MOONSHOT_HEARTBEAT_BOOT_MSG", boot_msg)
        msg = file_env.get("MOONSHOT_HEARTBEAT_MSG", msg)
        tag = file_env.get("MOONSHOT_HEARTBEAT_TAG", tag).strip()

    # 3) CLI (sobrepõe tudo)
    if args.token:
        token = args.token.strip()
    if args.chat_id:
        chat_id = args.chat_id.strip()
    if args.every:
        every = args.every.strip()
    if args.boot_msg:
        boot_msg = args.boot_msg
    if args.msg:
        msg = args.msg
    if args.tag:
        tag = args.tag.strip()

    # parse intervalo
    try:
        every_s = parse_duration(every or "21600")
    except Exception:
        every_s = 21600

    # tag prefix (opcional)
    if tag:
        boot_msg = f"{tag} {boot_msg}"
        msg = f"{tag} {msg}"

    return token, chat_id, every_s, boot_msg, msg

def send_message(token: str, chat_id: str, text: str, timeout: int = 20) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            return True
        if r.status_code == 429:
            try:
                data = r.json()
                retry = (data.get("parameters", {}) or {}).get("retry_after", 15)
            except Exception:
                retry = 15
            time.sleep(int(retry) + 1)
            r2 = requests.post(url, json=payload, timeout=timeout)
            return r2.status_code == 200
        # outras falhas: log simples em stdout (nohup captura)
        try:
            print("[TELEGRAM ERROR]", r.status_code, r.text)
        except Exception:
            pass
        return False
    except Exception as e:
        try:
            print("[TELEGRAM EXCEPTION]", repr(e))
        except Exception:
            pass
        return False

def main():
    ap = argparse.ArgumentParser(description="Moonshot Heartbeat (Telegram)")
    ap.add_argument("--token", help="Telegram bot token")
    ap.add_argument("--chat-id", help="Chat ID (ex.: -100xxxxxxxxxx ou @canal_publico)")
    ap.add_argument("--every", help="Intervalo (ex.: 6h, 15m, 30s, 86400)")
    ap.add_argument("--env-file", help="Caminho de .env (padrão: .env_moonshot, fallback .env)")
    ap.add_argument("--one-shot", action="store_true", help="Envia uma única mensagem e sai")
    ap.add_argument("--boot-msg", help="Mensagem inicial (boot)")
    ap.add_argument("--msg", help="Mensagem periódica (pode usar {now})")
    ap.add_argument("--tag", help="Prefixo opcional (ex.: '[MOONSHOT]')")
    args = ap.parse_args()

    token, chat_id, every_s, boot_msg, msg = resolve_config(args)

    if not token or not chat_id:
        print("[ERRO] Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (via .env, ambiente ou CLI).")
        raise SystemExit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if args.one_shot:
        send_message(token, chat_id, msg.format(now=now))
        return

    send_message(token, chat_id, boot_msg)
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_message(token, chat_id, msg.format(now=now))
        time.sleep(every_s)

if __name__ == "__main__":
    main()
