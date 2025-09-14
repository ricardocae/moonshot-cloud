import os
# get_telegram_chat_id.py
# Usos:
#   1) Somente token, listando updates:
#      python3 get_telegram_chat_id.py --token 123:ABC
#      (mande uma msg pro bot antes; ele listará chats e IDs)
#
#   2) Resolver @handle de canal/grupo:
#      python3 get_telegram_chat_id.py --token 123:ABC --handle @MeuCanal
#
# OBS: Para canais/grupos privados, o bot precisa estar adicionado.

import argparse, os, sys
import requests

def get_updates(token: str):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def get_chat(token: str, chat_id_or_handle: str):
    url = f"https://api.telegram.org/bot{token}/getChat"
    params = {"chat_id": chat_id_or_handle}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def main():
    p = argparse.ArgumentParser(description="Descobrir chat_id de Telegram")
    p.add_argument("--token", required=False, default=os.getenv("TG_BOT_TOKEN"), help="Bot token do Telegram")
    p.add_argument("--handle", required=False, help="Opcional: @handle do canal/grupo para resolver via getChat")
    args = p.parse_args()

    token = args.token
    if not token:
        print("❌ Forneça --token ou exporte TG_BOT_TOKEN no ambiente.")
        sys.exit(1)

    if args.handle:
        try:
            data = get_chat(token, args.handle)
            print("[getChat] Resposta:", data)
            if data.get("ok"):
                chat = data.get("result", {})
                print("\n✅ Resolvido:")
                print("  title:", chat.get("title"))
                print("  type:", chat.get("type"))
                print("  chat_id:", chat.get("id"))
            else:
                print("⚠️ getChat não retornou ok.")
        except requests.exceptions.RequestException as e:
            print("[ERRO] getChat:", e)
            sys.exit(2)
    else:
        try:
            data = get_updates(token)
            print("[getUpdates] Resposta breve (mostrando chats únicos):")
            seen = {}
            for upd in data.get("result", []):
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat") or {}
                cid = chat.get("id")
                if cid and cid not in seen:
                    seen[cid] = chat
            if not seen:
                print("Nenhum chat encontrado. Envie uma mensagem ao seu bot e rode de novo.")
            else:
                for cid, chat in seen.items():
                    print(f"- chat_id={cid}  title={chat.get('title')}  username={chat.get('username')}  type={chat.get('type')}")
        except requests.exceptions.RequestException as e:
            print("[ERRO] getUpdates:", e)
            sys.exit(2)

if __name__ == "__main__":
    main()
