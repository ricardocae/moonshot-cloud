import os, time
from flask import Flask, jsonify, Response

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "service": "moonshot-web",
        "time": int(time.time()),
        "tz": os.getenv("TZ", "UTC")
    })

@app.get("/")
def index():
    has_token = bool(os.getenv("TELEGRAM_TOKEN"))
    has_chat  = bool(os.getenv("TELEGRAM_CHAT_ID"))
    html = f"""
    <!doctype html>
    <html lang="pt-br">
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <title>Moonshot • Status</title>
    <style>
      body {{ font-family: -apple-system, Inter, Arial; margin: 40px; }}
      .card {{ max-width: 680px; padding: 24px; border-radius: 16px; box-shadow: 0 6px 24px rgba(0,0,0,.08); }}
      h1 {{ margin: 0 0 8px; }}
      .ok {{ color: #10b981; font-weight: 600; }}
      .bad {{ color: #ef4444; font-weight: 600; }}
      code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 6px; }}
      .hint {{ color: #6b7280; font-size: 14px; }}
      a.btn {{ display:inline-block; padding:10px 14px; border:1px solid #111; border-radius:12px; text-decoration:none; margin-top:12px }}
    </style>
    <div class="card">
      <h1>Moonshot • Status Web</h1>
      <p>Este serviço está online e pronto. Use o endpoint <code>/healthz</code> para checagens.</p>
      <ul>
        <li>Timezone (TZ): <strong>{os.getenv("TZ","America/Sao_Paulo")}</strong></li>
        <li>TELEGRAM_TOKEN: <span class="{ 'ok' if has_token else 'bad' }">{ 'definido' if has_token else 'não definido' }</span></li>
        <li>TELEGRAM_CHAT_ID: <span class="{ 'ok' if has_chat else 'bad' }">{ 'definido' if has_chat else 'não definido' }</span></li>
      </ul>
      <p class="hint">Observação: este painel é simples e não expõe segredos. Depois podemos evoluir para listar sinais, trades, etc.</p>
    </div>
    </html>
    """
    return Response(html, mimetype="text/html")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
