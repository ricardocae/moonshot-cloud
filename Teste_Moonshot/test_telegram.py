# test_telegram.py
# Uso básico:
#   python3 test_telegram.py
#   python3 test_telegram.py "Mensagem de teste"
#
# Overrides opcionais:
#   TG_BOT_TOKEN="123:ABC" TG_CHAT_ID="-1001234567890" python3 test_telegram.py "oi"
#   python3 test_telegram.py --token 123:ABC --chat-id -1001234567890 "oi"
#
# Requisitos:
#   - Defina no moonshot_config.yaml:
#       telegram:
#         enabled: true
#         bot_token: "SEU_TOKEN"
#         chat_id:   "-100XXXXXXXXXX"  # grupo/canal numérico OU @canal
#   - Se for canal/grupo: adicione o BOT e dê permissão para enviar mensagens (admin).

import os, sys, json
import argparse
import requests
import yaml

def load_cfg(path="moonshot_config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def send_msg(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=15)
        ok = r.status_code == 200
        print(f"[HTTP] {r.status_code}")
        if not ok:
            print("[ERRO] Resposta:", r.text)
        else:
            try:
                data = r.json()
                print("[OK] Mensagem enviada. message_id:", data.get("result", {}).get("message_id"))
            except Exception:
                print("[OK] Mensagem enviada.")
        return ok
    except requests.exceptions.RequestException as e:
        print("[EXCEPTION]", e)
        return False

def main():
    parser = argparse.ArgumentParser(description="Testar envio de mensagem no Telegram")
    parser.add_argument("message", nargs="?", default="Teste do Moonshot ✅", help="Texto da mensagem")
    parser.add_argument("--token", dest="token", default=os.getenv("TG_BOT_TOKEN"), help="Bot token (override)")
    parser.add_argument("--chat-id", dest="chat_id", default=os.getenv("TG_CHAT_ID"), help="Chat ID (override; numérico ou @canal)")
    parser.add_argument("--cfg", dest="cfg", default="moonshot_config.yaml", help="Caminho do YAML")
    args = parser.parse_args()

    cfg = {}
    try:
        cfg = load_cfg(args.cfg)
    except FileNotFoundError:
        print(f"[WARN] {args.cfg} não encontrado. Use --token/--chat-id ou exporte TG_BOT_TOKEN/TG_CHAT_ID.")
    tg = (cfg.get("telegram") or {}) if isinstance(cfg, dict) else {}

    token = args.token or tg.get("bot_token")
    chat_id = args.chat_id or tg.get("chat_id")

    if not token:
        print("❌ Token não definido. Use --token, variável TG_BOT_TOKEN ou preencha telegram.bot_token no YAML.")
        sys.exit(1)
    if not chat_id:
        print("❌ Chat ID não definido. Use --chat-id, variável TG_CHAT_ID ou preencha telegram.chat_id no YAML.")
        sys.exit(1)

    # Dicas úteis
    if isinstance(chat_id, str) and chat_id.startswith("@"):
        print("[INFO] Usando @handle como chat_id. Certifique-se de ter adicionado o bot ao canal e promovido a admin.")
    if isinstance(chat_id, str) and chat_id.isnumeric() and chat_id.startswith("0"):
        print("[WARN] Chat ID numérico estranho. Canais/grupos costumam ser negativos e começam com -100...")

    ok = send_msg(token, chat_id, args.message)
    if not ok:
        print("\nDICAS:")
        print("  • Confirme se o BOT foi adicionado ao grupo/canal e possui permissão p/ enviar mensagens.")
        print("  • Para canais públicos, o @handle muitas vezes funciona; para privados, prefira o ID numérico (-100...).")
        print("  • Obtenha o chat_id numérico usando o script get_telegram_chat_id.py abaixo.")
        sys.exit(2)

if __name__ == "__main__":
    main()
