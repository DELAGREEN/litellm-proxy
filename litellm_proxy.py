import os
import json
from dotenv import load_dotenv
from flask import Flask, request, Response, stream_with_context
from curl_cffi import requests as cffi_requests

# Загружаем переменные из .env
load_dotenv()

app = Flask(__name__)

UPSTREAM = os.getenv("UPSTREAM_URL", "https://litellm.ishosting.com")
API_KEY = os.getenv("LITELLM_API_KEY")
PORT = int(os.getenv("PROXY_PORT", 8081))

if not API_KEY:
    raise ValueError("Ошибка: LITELLM_API_KEY не задан в .env файле!")

# Заголовки, которые НЕ нужно пересылать — пусть curl_cffi выставит свои под Safari
DROP_REQUEST_HEADERS = {
    "host", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding",
    "upgrade", "content-length", "accept-encoding",
    "user-agent", "accept", "accept-language",
    "referer", "origin",
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
    "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
    "authorization",
}
STRIP_RESPONSE = {
    "content-encoding", "transfer-encoding", "content-length",
    "connection", "keep-alive",
}

@app.route("/v1/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def proxy(subpath):
    url = f"{UPSTREAM}/v1/{subpath}"

    headers = {
        k: v for k, v in request.headers
        if k.lower() not in DROP_REQUEST_HEADERS
    }
    headers["Authorization"] = f"Bearer {API_KEY}"

    body = request.get_data()

    # ── Магия для VS Code: подмена ID модели без слэша на ID с слэшем ──
    if body and request.is_json:
        try:
            payload = json.loads(body)
            if payload.get("model") == "deepseek-v4-flash":
                payload["model"] = "deepseek/deepseek-v4-flash"
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
                print("[PROXY] model ID: deepseek-v4-flash -> deepseek/deepseek-v4-flash")
        except Exception as e:
            print(f"[PROXY] Ошибка преобразования ID: {e}")
    # ──────────────────────────────────────────────────────────────────

    is_stream = False
    if request.is_json:
        try:
            is_stream = bool(request.get_json().get("stream", False))
        except Exception:
            pass

    # Отправляем запрос через curl_cffi с имитацией Safari
    resp = cffi_requests.request(
        method=request.method,
        url=url,
        headers=headers,
        data=body if body else None,
        impersonate="safari", # <-- Ключ к обходу Cloudflare!
        timeout=300,
        stream=True,
    )

    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in STRIP_RESPONSE}

    if is_stream:
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            finally:
                resp.close()
        return Response(
            stream_with_context(generate()),
            status=resp.status_code,
            headers=resp_headers,
            content_type=resp.headers.get("content-type", "text/event-stream"),
        )

    content = resp.content
    resp.close()
    return Response(content, status=resp.status_code, headers=resp_headers)

@app.before_request
def log_request():
    print(f"[PROXY] {request.method} {request.path}")
    safe = {k: ("***" if k.lower() == "authorization" else v) for k, v in request.headers}
    print(f"[PROXY] headers: {safe}")

if __name__ == "__main__":
    print(f"🚀 LiteLLM proxy запущен на http://127.0.0.1:{PORT}/v1")
    print(f"🔗 Апстрим: {UPSTREAM}")
    app.run(host="127.0.0.1", port=PORT, threaded=True)