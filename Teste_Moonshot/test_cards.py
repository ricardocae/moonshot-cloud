"""
test_cards.py — Envie cartões de TP (Long/Short) e STOP para o seu Telegram.

Uso:
  python test_cards.py --token SEU_TOKEN --chat CHAT_ID \
    --bg assets/moonshot/bg.jpg --bg-stop assets/moonshot/bg_stoploss.jpg

Ou defina variáveis de ambiente:
  export TELEGRAM_TOKEN=SEU_TOKEN
  export TELEGRAM_CHAT_ID=CHAT_ID
  python test_cards.py

Obs.: Se o BG não existir, o script gera um BG simples automaticamente.
"""

import os
import argparse
from pathlib import Path
from PIL import Image, ImageDraw

from telegram_send import send_tp_card, send_stop_card

def make_bg(path: str, kind: str = "tp"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 936, 540
    im = Image.new("RGB", (W, H), (18, 20, 24))
    dr = ImageDraw.Draw(im)

    # Barra superior sutil
    bar_h = 92 if kind == "tp" else 108
    bar_color = (28, 108, 78) if kind == "tp" else (122, 26, 26)
    dr.rectangle([0,0,W,bar_h], fill=bar_color)

    # Moldura discreta
    fr = (50, 54, 60)
    dr.rectangle([8,8,W-8,H-8], outline=fr, width=2)

    im.save(path)
    return str(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.getenv("TELEGRAM_TOKEN"), help="Bot token")
    ap.add_argument("--chat",  default=os.getenv("TELEGRAM_CHAT_ID"), help="Chat ID (user/channel)")
    ap.add_argument("--bg", default="assets/moonshot/bg.jpg", help="BG para TP")
    ap.add_argument("--bg-stop", default="assets/moonshot/bg_stoploss.jpg", help="BG para STOP")
    args = ap.parse_args()

    if not args.token or not args.chat:
        raise SystemExit("Informe --token e --chat (ou export TELEGRAM_TOKEN/TELEGRAM_CHAT_ID).")

    bg = args.bg if Path(args.bg).exists() else make_bg(args.bg, "tp")
    bg_stop = args.bg_stop if Path(args.bg_stop).exists() else make_bg(args.bg_stop, "stop")

    print("[1/3] Enviando TP1 LONG...")
    send_tp_card(
        args.token, args.chat,
        {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "leverage": "10x",
            "tp_label": "TP1",
            "roi_pct": +12.34,
            "entry": 60250.50,
            "last": 60510.30,
            "stop_text": 60250.50,
            "caption": "✅ TP1 hit | BTCUSDT LONG 15m\nEntry: 60250.50 • TP1: 60510.30\n➡️ Stop movido para BE (60250.50)",
        },
        bg_path=bg,
    )

    print("[2/3] Enviando TP2 SHORT...")
    send_tp_card(
        args.token, args.chat,
        {
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "leverage": "8x",
            "tp_label": "TP2",
            "roi_pct": -3.21,  # propositalmente negativo p/ testar cor do ROI
            "entry": 2550.00,
            "last": 2575.40,
            "stop_text": 2550.00,
            "caption": "✅ TP2 | ETHUSDT SHORT 15m\nTP2: 2575.40 • Stop permanece em BE (2550.00)",
        },
        bg_path=bg,
    )

    print("[3/3] Enviando STOP LOSS...")
    send_stop_card(
        args.token, args.chat,
        {
            "symbol": "SOLUSDT",
            "side": "LONG",
            "leverage": "10x",
            "roi_pct": -7.89,
            "entry": 143.75,
            "filled": 138.10,  # preço executado no SL
            "sl": 138.10,
            "caption": "🛑 Stop Loss | SOLUSDT LONG 15m\nFill: 138.10\nROI (est.): -7.89%",
        },
        bg_path_stop=bg_stop,
    )

    print("Feito! Verifique seu Telegram.")

if __name__ == "__main__":
    main()
