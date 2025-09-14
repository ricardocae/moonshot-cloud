#!/usr/bin/env python3
from pathlib import Path
import re, textwrap, py_compile, sys, os

P = Path("moonshot_agent.py")
if not P.exists():
    print("❌ Arquivo moonshot_agent.py não encontrado no diretório atual.")
    sys.exit(1)

orig = P.read_text(encoding="utf-8")
Path("moonshot_agent.py.bak_pre_fix").write_text(orig, encoding="utf-8")

s = orig

# 1) Cabeçalho "BOOT NOTIFY FILTER" seguro + imports opcionais
fixed_header = textwrap.dedent("""\
# --- BOOT NOTIFY FILTER ---
try:
    import os, requests
    if not getattr(requests, "_moonshot_boot_filter_local", False):
        _orig_req = requests.sessions.Session.request
        def _req(self, method, url, *a, **kw):
            try:
                u = str(url)
                if "api.telegram.org" in u and ("sendMessage" in u or "sendPhoto" in u or "sendAnimation" in u):
                    payload = kw.get("data") or kw.get("json") or {}
                    txt = ""
                    if isinstance(payload, dict):
                        txt = str(payload.get("text") or payload.get("caption") or "")
                    if not txt:
                        from urllib.parse import urlparse, parse_qs
                        q = parse_qs(urlparse(u).query)
                        txt = q.get("text", [""])[0] or q.get("caption", [""])[0]
                    low = (txt or "").lower()
                    # Kill-switch contra spam de boot quando DISABLE_BOOT_NOTIFY=1
                    if ("reiniciad" in low or "restarted" in low) and os.getenv("DISABLE_BOOT_NOTIFY","1")=="1":
                        class _Resp:
                            status_code = 200
                            text = "{}"
                            def json(self): return {"ok": True}
                        return _Resp()
            except Exception:
                pass
            return _orig_req(self, method, url, *a, **kw)
        requests.sessions.Session.request = _req
        requests._moonshot_boot_filter_local = True
except Exception:
    pass
# --- end BOOT NOTIFY FILTER ---

# Imports opcionais (não quebram se ausentes)
try:
    import sitecustomize  # opcional
except Exception:
    pass
try:
    import http_patch  # opcional
except Exception:
    pass
""")

# se já existir algo parecido no topo, substitui, senão prefixa
s = fixed_header + re.sub(r'^(# --- BOOT NOTIFY FILTER ---.*?# --- end BOOT NOTIFY FILTER ---\s*)?', '', s, flags=re.S)

# 2) Reescreve send_telegram_animation para evitar problemas de indent e de SESSION ausente
def repl_send_anim(match):
    indent = match.group(1)
    body = textwrap.indent(textwrap.dedent("""\
    def send_telegram_animation(cfg, caption, gif_path=None, gif_url=None):
        import requests, os
        tg = cfg.get("telegram", {})
        if not tg.get("enabled", False):
            print("[GIF][preview] ", (caption or "")[:120].replace("\\n", " ") + " ...")
            return True

        if caption and len(caption) > 1000:
            caption = caption[:1000] + "…"

        url = f"https://api.telegram.org/bot{tg['bot_token']}/sendAnimation"
        try:
            if gif_url:
                payload = {"chat_id": tg["chat_id"], "animation": gif_url, "caption": caption}
                r = requests.post(url, json=payload, timeout=20)
                r.raise_for_status()
                return True

            if gif_path:
                ap = os.path.abspath(gif_path)
                if os.path.exists(ap):
                    with open(ap, "rb") as f:
                        files = {"animation": f}
                        data = {"chat_id": tg["chat_id"], "caption": caption}
                        r = requests.post(url, data=data, files=files, timeout=30)
                        r.raise_for_status()
                        return True
                else:
                    print("[GIF] arquivo não encontrado:", ap)

            # fallback para texto
            print("[GIF] sem GIF válido; fallback para texto")
            return send_telegram(cfg, caption)

        except Exception as e:
            print(f"[gif] erro ao enviar animação — {e}")
            return send_telegram(cfg, caption)
    """), indent)
    return indent + body

s = re.sub(
    r'(^[ \t]*)def send_telegram_animation\([^\n]*\):.*?(?=^[ \t]*# [= -]*\n|^[ \t]*def |\Z)',
    repl_send_anim, s, flags=re.S|re.M
)

# 3) Limpezas: linhas com aspas soltas e casos ')   elif' colados
s = re.sub(r'(?m)^[ \t]*["\'][ \t]*\n', '', s)
s = re.sub(r'(?m)\)\s+elif\s+', ')\n            elif ', s)

# 4) Normaliza o bloco de STOP/TP (eliminação de strings quebradas)
s = re.sub(
    r'caption\s*=\s*\([\s\S]*?STOP[\s\S]*?\)',
    'caption = (f"🛑 Stop Loss | {tr[\'symbol\']} {side} on {tr[\'tf\']}m\\n" '
    'f"Fill: {price}\\n" f"ROI (est.): {roi}%")',
    s
)

# 5) Tenta consertar elif colado após except: (faltava newline)
s = re.sub(r'(?m)^(?P<i>\s*except [^\n]+:\n)(\s*)(elif\s+)', r'\g<i>\2#\n\2\3', s)

# 6) Salva e compila; se falhar, mostra trecho
P.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(P), doraise=True)
    print("✅ Syntax OK — moonshot_agent.py compilou limpo.")
except py_compile.PyCompileError as e:
    print("❌ Ainda com erro de sintaxe:", e)
    import re as _re
    m = _re.search(r'line (\d+)', str(e))
    if m:
        ln = int(m.group(1))
        lines = s.splitlines()
        a = max(1, ln-12); b = min(len(lines), ln+12)
        print(f"--- Trecho {a}..{b} ---")
        for k in range(a, b+1):
            print(f"{k:5d} {lines[k-1]}")
    sys.exit(2)
