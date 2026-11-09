import os
import json
import time
from dotenv import load_dotenv
from flask import Flask, request, Response, stream_with_context
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import RequestException, SSLError, ConnectionError

load_dotenv()

app = Flask(__name__)

UPSTREAM = os.getenv("UPSTREAM_URL", "https://litellm.ishosting.com")
API_KEY = os.getenv("LITELLM_API_KEY")
PORT = int(os.getenv("PROXY_PORT", 8081))

if not API_KEY:
    raise ValueError("Ошибка: LITELLM_API_KEY не задан в .env файле!")

# Профили для fallback: если Cloudflare сбрасывает safari — пробуем следующий
IMPERSONATE_PROFILES = ["safari", "safari17_2_ios", "chrome124", "chrome"]

# ── АВТОМАТИЧЕСКОЕ ОПРЕДЕЛЕНИЕ МОДЕЛЕЙ ──
_available_models = None


def get_available_models():
    """Запрашивает у LiteLLM список моделей с ретраями и fallback профилей."""
    global _available_models
    if _available_models is not None:
        return _available_models

    print("[PROXY] Запрос списка моделей у LiteLLM...")
    for profile in IMPERSONATE_PROFILES:
        for attempt in range(2):
            try:
                resp = cffi_requests.get(
                    f"{UPSTREAM}/v1/models",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    impersonate=profile,
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    _available_models = [m["id"] for m in data.get("data", [])]
                    print(f"[PROXY] Доступные модели ({profile}): {_available_models}")
                    return _available_models
                else:
                    print(f"[PROXY] /v1/models вернул {resp.status_code} (профиль {profile})")
            except (RequestException, SSLError, ConnectionError) as e:
                print(f"[PROXY] Ошибка /v1/models (профиль {profile}, попытка {attempt+1}): {e}")
                time.sleep(1)

    print("[PROXY] Не удалось получить список моделей. Буду работать без авто-маппинга.")
    _available_models = []
    return _available_models


def resolve_model_id(requested_id: str) -> str:
    """Находит полный ID модели в списке LiteLLM по упрощённому имени."""
    models = get_available_models()
    if not models:
        return requested_id

    if requested_id in models:
        return requested_id

    for model in models:
        if model.endswith(requested_id):
            print(f"[PROXY] Авто-маппинг: {requested_id} -> {model}")
            return model

    for model in models:
        if requested_id in model:
            print(f"[PROXY] Авто-маппинг (частичное): {requested_id} -> {model}")
            return model

    print(f"[PROXY] Модель '{requested_id}' не найдена в списке LiteLLM. Отправляем как есть.")
    return requested_id
# ────────────────────────────────────────────


def make_upstream_request(method, url, headers, data, max_retries=3):
    """Отправляет запрос с ретраями и fallback профилей Safari/Chrome."""
    last_exception = None
    for profile in IMPERSONATE_PROFILES:
        for attempt in range(max_retries):
            try:
                return cffi_requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=data,
                    impersonate=profile,
                    timeout=300,
                    stream=True,
                )
            except (RequestException, SSLError, ConnectionError) as e:
                last_exception = e
                error_str = str(e).lower()
                retriable = (
                    "reset by peer" in error_str
                    or "recv failure" in error_str
                    or "ssl" in error_str
                    or "timed out" in error_str
                )
                if retriable:
                    print(f"[PROXY] Ошибка соединения (профиль {profile}, попытка {attempt+1}/{max_retries}): {e}")
                    time.sleep(1)
                    continue
                raise
    raise last_exception


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

    # ── АВТОМАТИЧЕСКАЯ ПОДМЕНА ID МОДЕЛИ ──
    if body and request.is_json:
        try:
            payload = json.loads(body)
            original_model = payload.get("model")
            if original_model:
                mapped_model = resolve_model_id(original_model)
                if mapped_model != original_model:
                    payload["model"] = mapped_model
                    body = json.dumps(payload).encode("utf-8")
                    headers["Content-Type"] = "application/json"
        except Exception as e:
            print(f"[PROXY] Ошибка при обработке ID модели: {e}")
    # ───────────────────────────────────────

    is_stream = False
    if request.is_json:
        try:
            is_stream = bool(request.get_json().get("stream", False))
        except Exception:
            pass

    resp = make_upstream_request(
        method=request.method,
        url=url,
        headers=headers,
        data=body if body else None,
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


if __name__ == "__main__":
    print(f"🚀 LiteLLM proxy запущен на http://127.0.0.1:{PORT}/v1")
    print(f"🔗 Апстрим: {UPSTREAM}")
    get_available_models()
    app.run(host="127.0.0.1", port=PORT, threaded=True)