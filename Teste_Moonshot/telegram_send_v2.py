import os
import requests
from pathlib import Path
from typing import Optional
from moonshot_card import generate_trade_card, generate_stop_card

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

def _truncate(s: str, limit: int = 1024) -> str:
    s = (s or "").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"

def _resolve(path_candidates):
    for p in path_candidates:
        p = Path(p)
        if p.exists():
            return str(p)
    return None

def _send_photo(token: str, chat_id: str, photo_path: str, caption: str, parse_mode: Optional[str] = None) -> None:
    with open(photo_path, "rb") as f:
        data = {"chat_id": chat_id, "caption": caption}
        if parse_mode:
            data["parse_mode"] = parse_mode
        r = requests.post(
            TELEGRAM_API.format(token=token, method="sendPhoto"),
            data=data, files={"photo": f}, timeout=30
        )
    # se a legenda tiver caracteres que quebrem o parse, reenvia sem parse_mode
    if r.status_code == 400 and "parse entities" in r.text.lower():
        with open(photo_path, "rb") as f:
            r2 = requests.post(
                TELEGRAM_API.format(token=token, method="sendPhoto"),
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": f}, timeout=30
            )
        r2.raise_for_status()
        return
    r.raise_for_status()

def _send_text(token: str, chat_id: str, text: str) -> None:
    r = requests.post(
        TELEGRAM_API.format(token=token, method="sendMessage"),
        data={"chat_id": chat_id, "text": text}, timeout=20
    )
    r.raise_for_status()

def send_tp_card(token: str, chat_id: str, data: dict, bg_path: str = None, out_dir: str = "/tmp") -> None:
    """Envia card de TP (TP1/TP2/TP3) como UMA mensagem (foto + caption)."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    label = data.get("tp_label") or data.get("event") or "TP"
    img = out / f"moonshot_{data.get('symbol','SYMBOL')}_{label}.png"

    here = Path(__file__).resolve().parent
    bg_resolved = _resolve([bg_path or "", here / "assets/moonshot/bg.jpg", here.parent / "assets/moonshot/bg.jpg"])

    # gera imagem
    generate_trade_card(
        symbol=data.get("symbol",""),
        side=data.get("side","LONG"),
        leverage=data.get("leverage",""),
        tp_label=label,
        roi_pct=float(data.get("roi_pct", 0.0)),
        entry_price=float(data.get("entry", 0.0) or 0.0),
        last_price=float(data.get("last", 0.0) or 0.0),
        stop_text=str(data.get("stop_text","") or data.get("sl","") or ""),
        out_path=str(img),
        bg_path=bg_resolved,
    )

    caption = _truncate(data.get("caption") or f"{data.get('symbol','')} | {label}", 1024)
    try:
        _send_photo(token, chat_id, str(img), caption, parse_mode="HTML")
    except requests.exceptions.RequestException:
        _send_text(token, chat_id, _truncate(caption, 4096))

def send_stop_card(token: str, chat_id: str, data: dict, bg_path_stop: str = None, out_dir: str = "/tmp") -> None:
    """Envia card de STOP como UMA mensagem (foto + caption)."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    img = out / f"moonshot_{data.get('symbol','SYMBOL')}_STOP.png"

    here = Path(__file__).resolve().parent
    bg_resolved = _resolve([
        bg_path_stop or "",
        here / "assets/moonshot/bg_stoploss.jpg",
        here.parent / "assets/moonshot/bg_stoploss.jpg",
        here / "assets/moonshot/bg.jpg",
        here.parent / "assets/moonshot/bg.jpg",
    ])

    generate_stop_card(
        symbol=data.get("symbol",""),
        side=data.get("side","LONG"),
        leverage=data.get("leverage",""),
        roi_pct=float(data.get("roi_pct", 0.0)),
        entry_price=float(data.get("entry", 0.0) or 0.0),
        filled_price=float(data.get("filled", data.get("last", 0.0)) or 0.0),
        sl_price=float(data.get("sl", 0.0) or 0.0),
        out_path=str(img),
        bg_path=bg_resolved,
    )

    caption = _truncate(data.get("caption") or f"{data.get('symbol','')} | STOP", 1024)
    try:
        _send_photo(token, chat_id, str(img), caption, parse_mode="HTML")
    except requests.exceptions.RequestException:
        _send_text(token, chat_id, _truncate(caption, 4096))
