"""Рецензент — вебсервіс автоматичного рев'ю коду лабораторних робіт на основі Google Gemini API.

Хмарні моделі в проєкті:
  AIaaS  — Google Gemini API (аналіз коду, структурований JSON)
  DBaaS  — Supabase (PostgreSQL) для історії перевірок
  PaaS   — Render (хостинг Flask-сервера, публічне посилання)
  SaaS   — GitHub (код), Google AI Studio (ключі)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from reviewer import config
from reviewer.examples import EXAMPLES
from reviewer.gemini_client import ReviewError, review_code
from reviewer.storage import build_record, compute_stats, make_storage
from reviewer.validation import (InputError, decode_upload, language_from_filename,
                                 validate_code, validate_language, validate_model)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1 МБ на запит
app.json.ensure_ascii = False

storage = make_storage()
log.info("Storage: %s | Gemini configured: %s | model: %s", storage.name, bool(config.GEMINI_API_KEY), config.DEFAULT_MODEL)

# --- Простий захист квоти: не більше N перевірок на хвилину з однієї IP-адреси ---
RATE_LIMIT_PER_MIN = 8
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "?")


def _check_rate(cost: int = 1) -> None:
    now = time.time()
    with _hits_lock:
        q = _hits[_client_ip()]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + cost > RATE_LIMIT_PER_MIN:
            raise InputError("local_rate", "Забагато перевірок за хвилину. Зачекайте трохи і спробуйте знову.", 429)
        for _ in range(cost):
            q.append(now)


def api_error(code: str, message: str, status: int):
    return jsonify({"ok": False, "error": {"code": code, "message": message}}), status


@app.errorhandler(InputError)
def _input_error(e: InputError):
    return api_error(e.code, e.message, e.status)


@app.errorhandler(ReviewError)
def _review_error(e: ReviewError):
    return api_error(e.code, e.message, e.status)


@app.errorhandler(HTTPException)
def _http_error(e: HTTPException):
    if request.path.startswith("/api/"):
        messages = {
            404: "Такого API-методу немає.",
            405: "Неправильний метод запиту.",
            413: "Запит завеликий. Максимум — 1 МБ.",
        }
        return api_error(f"http_{e.code}", messages.get(e.code, e.description or "Помилка запиту."), e.code)
    if e.code == 404:
        return render_template("404.html"), 404
    return e


@app.errorhandler(Exception)
def _unexpected(e: Exception):
    log.exception("Unhandled error")
    if request.path.startswith("/api/"):
        return api_error("server", "Внутрішня помилка сервера. Спробуйте ще раз.", 500)
    return "Внутрішня помилка сервера", 500


def _read_request() -> dict:
    """Приймає JSON {code, language, model, filename} або multipart з файлом."""
    if request.files.get("file"):
        f = request.files["file"]
        filename = f.filename or "code.txt"
        code = decode_upload(f.read(config.MAX_UPLOAD_BYTES + 1), filename)
        form = request.form
        language = form.get("language") or language_from_filename(filename) or "auto"
        return {"code": code, "language": language, "model": form.get("model"), "filename": filename,
                "models": form.getlist("models")}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise InputError("bad_json", "Некоректний запит: очікується JSON.")
    return data


def _run_review(code: str, language: str, model: str, filename: str | None, allow_fallback: bool = False) -> dict:
    lang_label = config.LANGUAGES.get(language, "auto") if language != "auto" else "auto"
    if allow_fallback and config.FALLBACK_MODELS:
        outcome = review_code(code, lang_label, model, fallback=config.FALLBACK_MODELS)
    else:
        outcome = review_code(code, lang_label, model)
    model = outcome.model  # якщо спрацював резерв — показуємо модель, яка реально відповіла
    saved_id, saved = None, True
    try:
        rec = storage.save(build_record(language=config.LANGUAGES.get(language, language), filename=filename,
                                        code=code, outcome=outcome))
        saved_id = rec.get("id") if rec else None
    except Exception:  # noqa: BLE001  — збій БД не повинен ламати рев'ю
        log.exception("History save failed")
        saved = False
    info = config.MODELS.get(model, {})
    return {
        "ok": True,
        "id": saved_id,
        "history_saved": saved,
        "result": outcome.result,
        "meta": {
            "model": model,
            "model_label": info.get("label", model),
            "fallback_from": outcome.fallback_from,
            "fallback_reason": outcome.fallback_reason,
            "fallback_from_label": config.MODELS.get(outcome.fallback_from or "", {}).get("label", outcome.fallback_from),
            "duration_ms": outcome.duration_ms,
            "attempts": outcome.attempts,
            "input_tokens": outcome.input_tokens,
            "output_tokens": outcome.output_tokens,
            "thinking_tokens": outcome.thinking_tokens,
            "cost_usd": outcome.cost_usd,
            "cost_per_1000_usd": round(outcome.cost_usd * 1000, 2),
            "price_note": info.get("price_note", ""),
            "code_lines": code.count("\n") + 1,
        },
    }


# ------------------------------- Сторінки -------------------------------

@app.get("/")
def index():
    return render_template("index.html", page="review")


@app.get("/history")
def history_page():
    return render_template("history.html", page="history")


# --------------------------------- API ----------------------------------

@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "gemini_configured": bool(config.GEMINI_API_KEY),
        "storage": storage.name,
        "default_model": config.DEFAULT_MODEL,
    })


@app.get("/api/config")
def api_config():
    return jsonify({
        "default_model": config.DEFAULT_MODEL,
        "models": [{"id": k, **v} for k, v in config.available_models().items()],
        "languages": [{"id": k, "label": v} for k, v in config.LANGUAGES.items()],
        "extensions": sorted(config.EXTENSIONS),
        "limits": {"chars": config.MAX_CODE_CHARS, "lines": config.MAX_CODE_LINES, "upload_bytes": config.MAX_UPLOAD_BYTES},
        "examples": EXAMPLES,
    })


@app.post("/api/review")
def api_review():
    data = _read_request()
    code = validate_code(data.get("code"))
    language = validate_language(data.get("language") or language_from_filename(data.get("filename")))
    model = validate_model(data.get("model"))
    _check_rate()
    return jsonify(_run_review(code, language, model, data.get("filename"), allow_fallback=True))


@app.post("/api/compare")
def api_compare():
    data = _read_request()
    code = validate_code(data.get("code"))
    language = validate_language(data.get("language") or language_from_filename(data.get("filename")))
    models = data.get("models") or [m for m in config.available_models()][:2]
    models = list(dict.fromkeys(validate_model(m) for m in models))[:3]
    if len(models) < 2:
        raise InputError("bad_model", "Для порівняння потрібні дві різні моделі.")
    _check_rate(len(models))

    def one(m):
        try:
            return _run_review(code, language, m, data.get("filename"))
        except ReviewError as e:
            info = config.MODELS.get(m, {})
            return {"ok": False, "error": {"code": e.code, "message": e.message},
                    "meta": {"model": m, "model_label": info.get("label", m)}}

    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        results = list(pool.map(one, models))
    if not any(r["ok"] for r in results):
        err = results[0]["error"]
        return api_error(err["code"], err["message"], 502)
    return jsonify({"ok": True, "results": results})


@app.get("/api/history")
def api_history():
    try:
        limit = max(1, min(int(request.args.get("limit", 300)), 1000))
    except ValueError:
        limit = 300
    try:
        rows = storage.list(limit=limit)
    except Exception:  # noqa: BLE001
        log.exception("History load failed")
        return api_error("db", f"Не вдалося завантажити історію ({storage.name}). Перевірте налаштування бази даних.", 503)
    return jsonify({"ok": True, "storage": storage.name, "items": rows, "stats": compute_stats(rows)})


@app.get("/api/history/<int:review_id>")
def api_history_item(review_id: int):
    try:
        row = storage.get(review_id)
    except Exception:  # noqa: BLE001
        log.exception("History item load failed")
        return api_error("db", "Не вдалося завантажити запис з бази даних.", 503)
    if not row:
        return api_error("not_found", "Запис не знайдено.", 404)
    return jsonify({"ok": True, "item": row})


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))
    print(f"\n  Рецензент запущено: http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
