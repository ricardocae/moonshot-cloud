import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_moonshot_patches.py
Hotfix automático para o Teste_Moonshot:
- Adiciona _normalize_trades_for_notifications() no moonshot_agent.py
- Garante uso do normalizador ao carregar trades
- Garante criação do campo "notified" em novos trades
- Adiciona fallback de texto no telegram_send.py caso o card falhe

Este script é idempotente: pode ser executado várias vezes.
Ele cria backups com extensão .bak.<timestamp>
"""

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT = ROOT / "Teste_Moonshot" / "moonshot_agent.py"
TG    = ROOT / "Teste_Moonshot" / "telegram_send.py"

TS = int(time.time())

def backup(p: Path):
    if not p.exists():
        print(f"[AVISO] Arquivo não encontrado: {p}")
        return False
    bk = p.with_suffix(p.suffix + f".bak.{TS}")
    bk.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[OK] Backup feito: {bk.name}")
    return True

def patch_agent(text: str) -> str:
    orig = text

    # 1) Inserir função _normalize_trades_for_notifications após save_trades()
    if "_normalize_trades_for_notifications" not in text:
        # Encontrar def save_trades(...)
        m = re.search(r"def\s+save_trades\s*\([^\)]*\):\s*\n\s*save_json\(.*?\)\s*\n", text, flags=re.DOTALL)
        if m:
            inject = """
def _normalize_trades_for_notifications(trades: dict) -> dict:
    \"\"\"Garante um 'notified' em cada trade para evitar KeyErrors em arquivos antigos.\"\"\"
    try:
        items = trades.values()
    except Exception:
        return trades
    for tr in items:
        if isinstance(tr, dict):
            tr.setdefault("notified", {"TP1": False, "TP2": False, "TP3": False, "STOP": False})
    return trades

"""
            pos = m.end()
            text = text[:pos] + inject + text[pos:]
            print("[OK] Inserido _normalize_trades_for_notifications() no moonshot_agent.py")
        else:
            print("[ERRO] Não encontrei a função save_trades() para injetar o normalizador.")
    else:
        print("[SKIP] Normalizador já existe no moonshot_agent.py")

    # 2) Garantir uso do normalizador ao carregar os trades
    # Procura linha tipo: trades = load_trades(cfg["trades_file"])
    pattern_load = r"(\btrades\s*=\s*)load_trades\s*\(\s*cfg\[[\"']trades_file[\"']\]\s*\)"
    if re.search(pattern_load, text):
        text, n = re.subn(pattern_load, r"\1_normalize_trades_for_notifications(load_trades(cfg[\"trades_file\"]))", text)
        if n:
            print("[OK] Uso do normalizador aplicado no carregamento de trades.")
    else:
        # Caso já esteja normalizado, tenta detectar
        if "_normalize_trades_for_notifications(load_trades(" in text:
            print("[SKIP] Carregamento de trades já usa o normalizador.")
        else:
            print("[AVISO] Não achei a atribuição de 'trades = load_trades(...)'. Verifique manualmente depois.")

    # 3) Incluir 'notified' na criação de novos trades
    # Procuramos um trecho padrão com 'updates': [],
    created_pat = r"(\{\s*[\s\S]{0,200}['\"]updates['\"]\s*:\s*\[\s*\]\s*,)"
    if re.search(created_pat, text):
        def repl_created(mo):
            block = mo.group(1)
            # Se já contém notified, não duplica
            if re.search(r"['\"]notified['\"]\s*:", text[mo.start():mo.start()+400]):
                return block
            add = " \"notified\": {\"TP1\": False, \"TP2\": False, \"TP3\": False, \"STOP\": False},"
            return block + add
        text2 = re.sub(created_pat, repl_created, text, count=1)
        if text2 != text:
            text = text2
            print("[OK] Campo 'notified' adicionado na criação de novos trades.")
        else:
            print("[SKIP] 'notified' já presente na criação de novos trades.")
    else:
        print("[AVISO] Não consegui localizar o bloco de criação de trade para inserir 'notified'.")

    return text if text != orig else text

def patch_tg(text: str) -> str:
    orig = text

    # Precisamos envolver chamadas a generate_trade_card(...) com try/except e fallback para _send_text(...)
    # Estratégia genérica: localizar chamadas a generate_trade_card( ... out_path=..., bg_path=... )
    # e envelopar com try/except se ainda não estiverem.
    def wrap_generate_blocks(code: str) -> str:
        # Apenas se não houver try: próximo a generate_trade_card
        if "generate_trade_card(" not in code:
            return code  # nada a fazer
        # Evita duplicar: se já tem 'try:' algumas linhas acima, pula
        lines = code.splitlines()
        out = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if "generate_trade_card(" in line and "try:" not in "".join(lines[max(0, i-2):i+1]):
                # abre try:
                out.append("    try:")
                out.append("        " + line.strip())
                i += 1
                # copiar até fechar a chamada (balanceando parênteses simples)
                paren = line.count("(") - line.count(")")
                while i < len(lines) and paren > 0:
                    out.append("        " + lines[i].rstrip())
                    paren += lines[i].count("(") - lines[i].count(")")
                    i += 1
                # agora except
                # tenta montar um label básico
                out.append("    except Exception:")
                out.append("        # Fallback: envia texto se a geração do card falhar")
                out.append("        try:")
                out.append("            _send_text(token, chat_id, _truncate(data.get('caption') or label if 'label' in locals() else (data.get('caption') or 'Atualização'), 4096))")
                out.append("        except Exception:")
                out.append("            pass")
                continue
            else:
                out.append(line)
                i += 1
        return "\n".join(out)

    # Checar se _send_text e _truncate existem; se não, criamos versões simples
    if "_send_text(" not in text:
        text += """

def _send_text(token: str, chat_id: str, text: str):
    import requests
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception:
        pass

"""
        print("[OK] Função _send_text adicionada ao telegram_send.py")

    if "_truncate(" not in text:
        text += """
def _truncate(s: str, limit: int = 4096) -> str:
    s = s or ""
    return s if len(s) <= limit else s[: limit - 3] + "..."
"""
        print("[OK] Função _truncate adicionada ao telegram_send.py")

    # Envelopa generate_trade_card com try/except
    before = text
    text = wrap_generate_blocks(text)
    if text != before:
        print("[OK] Fallback try/except aplicado nas chamadas a generate_trade_card().")
    else:
        print("[SKIP] Não encontrei generate_trade_card() OU já estava protegido.")

    return text

def run():
    ok_any = False

    # moonshot_agent.py
    if AGENT.exists():
        backup(AGENT)
        new = patch_agent(AGENT.read_text(encoding="utf-8"))
        if new:
            AGENT.write_text(new, encoding="utf-8")
            ok_any = True
            print(f"[OK] Patch aplicado: {AGENT}")
    else:
        print(f"[ERRO] Arquivo não encontrado: {AGENT}")

    # telegram_send.py
    if TG.exists():
        backup(TG)
        new = patch_tg(TG.read_text(encoding="utf-8"))
        if new:
            TG.write_text(new, encoding="utf-8")
            ok_any = True
            print(f"[OK] Patch aplicado: {TG}")
    else:
        print(f"[AVISO] telegram_send.py não encontrado: {TG}")

    if not ok_any:
        print("\n[NENHUMA MUDANÇA APLICADA]")
        sys.exit(1)

    print("\n[SUCESSO] Patches aplicados. Próximos passos:")
    print("1) Rode o fix_trades_json_once.py (abaixo) UMA vez para normalizar o arquivo atual.")
    print("2) Reinicie o agente (remova lock e suba novamente).")

if __name__ == "__main__":
    run()
