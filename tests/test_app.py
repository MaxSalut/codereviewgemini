"""Автотести без реального Gemini: перевіряють валідацію, обробку помилок, збереження історії.
Запуск: python -m pytest -q"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SUPABASE_URL"] = ""
os.environ["GEMINI_API_KEY"] = "test-key"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from reviewer import config, storage as storage_mod
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    import app as app_module
    monkeypatch.setattr(app_module, "storage", storage_mod.SQLiteStorage(str(tmp_path / "h.db")))
    app_module._hits.clear()
    return app_module.app.test_client()


def fake_outcome(model="gemini-3.8-flash"):
    from reviewer.gemini_client import ReviewOutcome
    return ReviewOutcome(
        result={
            "detected_language": "Python", "score": 62, "summary": "Є помилки.", "strengths": ["Зрозумілі назви"],
            "issues": [
                {"line": 3, "type": "error", "severity": "high", "title": "Ділення на нуль", "description": "len=0", "fix": "Перевірте `if not grades`"},
                {"line": 1, "type": "style", "severity": "low", "title": "Назва", "description": "x", "fix": "y"},
            ],
            "corrected_code": "print(1)",
        },
        model=model, duration_ms=4321, attempts=1, input_tokens=900, output_tokens=700, thinking_tokens=100,
        cost_usd=0.003675,
    )


def test_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/history").status_code == 200
    assert client.get("/nope").status_code == 404
    assert client.get("/api/nope").get_json()["error"]["code"] == "http_404"


def test_health_and_config(client):
    h = client.get("/api/health").get_json()
    assert h["ok"] and h["gemini_configured"]
    c = client.get("/api/config").get_json()
    assert len(c["examples"]) == 4 and c["models"]


@pytest.mark.parametrize("payload,code", [
    ({"code": ""}, "empty"),
    ({"code": "   \n  "}, "empty"),
    ({"code": "x=1"}, "too_short"),
    ({"code": "a = 1\n" * 900}, "too_long"),
    ({"code": 123}, "empty"),
])
def test_bad_input(client, payload, code):
    r = client.post("/api/review", json=payload)
    assert r.status_code in (400, 413)
    assert r.get_json()["error"]["code"] == code


def test_bad_json(client):
    r = client.post("/api/review", data="не json", content_type="application/json")
    assert r.get_json()["error"]["code"] == "bad_json"


def test_bad_file(client):
    import io
    r = client.post("/api/review", data={"file": (io.BytesIO(b"\x00\x01PNG"), "photo.png")}, content_type="multipart/form-data")
    assert r.get_json()["error"]["code"] == "bad_file"
    r = client.post("/api/review", data={"file": (io.BytesIO(b"\x00\x01\x02" * 10), "a.py")}, content_type="multipart/form-data")
    assert r.get_json()["error"]["code"] == "bad_file"


def test_review_ok_and_history(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "review_code", lambda code, lang, model, **kw: fake_outcome(model))
    r = client.post("/api/review", json={"code": "def f(g):\n    return sum(g)/len(g)\n", "language": "python"})
    data = r.get_json()
    assert r.status_code == 200 and data["ok"] and data["history_saved"]
    assert data["meta"]["cost_usd"] > 0
    h = client.get("/api/history").get_json()
    assert h["stats"]["total"] == 1 and h["stats"]["by_type"][0]["count"] == 1
    item = client.get(f"/api/history/{data['id']}").get_json()["item"]
    assert item["result"]["score"] == 62


def test_upload_cp1251(client, monkeypatch):
    import io
    import app as app_module
    monkeypatch.setattr(app_module, "review_code", lambda code, lang, model, **kw: fake_outcome(model))
    src = "# Лабораторна\nprint('привіт')\n".encode("cp1251")
    r = client.post("/api/review", data={"file": (io.BytesIO(src), "lab.py")}, content_type="multipart/form-data")
    assert r.get_json()["ok"]


def test_gemini_errors_are_friendly(client, monkeypatch):
    import app as app_module
    from reviewer.gemini_client import ReviewError

    def boom(*a, **k):
        raise ReviewError("rate_limit", "Перевищено ліміт", 429)
    monkeypatch.setattr(app_module, "review_code", boom)
    r = client.post("/api/review", json={"code": "print('hello world')"})
    assert r.status_code == 429 and r.get_json()["error"]["code"] == "rate_limit"


def test_compare(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "review_code", lambda code, lang, model, **kw: fake_outcome(model))
    r = client.post("/api/compare", json={"code": "print('hello world')", "models": ["gemini-3.8-flash", "gemini-3.5-flash-lite"]})
    d = r.get_json()
    assert d["ok"] and len(d["results"]) == 2


def test_local_rate_limit(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "review_code", lambda code, lang, model, **kw: fake_outcome(model))
    codes = [client.post("/api/review", json={"code": "print('hello world')"}).status_code for _ in range(10)]
    assert 429 in codes


def test_classify_and_retry(monkeypatch):
    """Перевіряє повторну спробу після збою 503 і класифікацію помилок SDK."""
    import httpx2 as httpx
    from google.genai import errors
    from reviewer import gemini_client as gc

    calls = {"n": 0}

    class Resp:
        parsed = None
        text = '{"detected_language":"Python","score":120,"summary":"ok","strengths":[],"issues":[],"corrected_code":"x"}'
        usage_metadata = type("U", (), {"prompt_token_count": 10, "candidates_token_count": 5, "thoughts_token_count": 0})()

    class Models:
        def generate_content(self, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
            return Resp()

    monkeypatch.setattr(gc, "get_client", lambda: type("C", (), {"models": Models()})())
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    out = gc.review_code("print(1)\nprint(2)", "Python", "gemini-3.8-flash")
    assert out.attempts == 2 and out.result["score"] == 100
    assert gc._classify(httpx.ReadTimeout("t")).code == "timeout"
    assert gc._classify(errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})).code == "rate_limit"


def _fake_gemini(monkeypatch, fail_models, error_code=503):
    """Підміняє клієнт Gemini: моделі з fail_models завжди падають з error_code, інші відповідають."""
    from google.genai import errors
    from reviewer import gemini_client as gc

    calls = []

    class Resp:
        parsed = None
        text = '{"detected_language":"Python","score":80,"summary":"ok","strengths":[],"issues":[],"corrected_code":"x"}'
        usage_metadata = type("U", (), {"prompt_token_count": 10, "candidates_token_count": 5, "thoughts_token_count": 0})()

    class Models:
        def generate_content(self, model, **kw):
            calls.append(model)
            if model in fail_models:
                cls = errors.ServerError if error_code >= 500 else errors.ClientError
                raise cls(error_code, {"error": {"code": error_code, "message": "high demand", "status": "X"}})
            return Resp()

    monkeypatch.setattr(gc, "get_client", lambda: type("C", (), {"models": Models()})())
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    gc._cooldown_until.clear()
    return gc, calls


def test_fallback_when_primary_overloaded(monkeypatch):
    gc, calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash"})
    out = gc.review_code("print(1)", "Python", "gemini-3.8-flash", fallback="gemini-3.5-flash-lite")
    assert out.model == "gemini-3.5-flash-lite" and out.fallback_from == "gemini-3.8-flash"
    assert calls.count("gemini-3.8-flash") == 3 and calls[-1] == "gemini-3.5-flash-lite"
    # Наступний запит одразу йде на резервну модель (основна «відпочиває»).
    calls.clear()
    out = gc.review_code("print(1)", "Python", "gemini-3.8-flash", fallback="gemini-3.5-flash-lite")
    assert calls == ["gemini-3.5-flash-lite"] and out.fallback_from == "gemini-3.8-flash"


def test_no_fallback_for_bad_key_or_without_fallback(monkeypatch):
    gc, calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash"}, error_code=403)
    with pytest.raises(gc.ReviewError) as e:
        gc.review_code("print(1)", "Python", "gemini-3.8-flash", fallback="gemini-3.5-flash-lite")
    assert e.value.code == "bad_key" and calls == ["gemini-3.8-flash"]
    gc, calls = _fake_gemini(monkeypatch, {"gemini-3.8-flash"})
    with pytest.raises(gc.ReviewError):
        gc.review_code("print(1)", "Python", "gemini-3.8-flash")
    assert set(calls) == {"gemini-3.8-flash"}


def test_api_review_reports_fallback(client, monkeypatch):
    _fake_gemini(monkeypatch, {"gemini-3.8-flash"})
    r = client.post("/api/review", json={"code": "print('hello world')", "model": "gemini-3.8-flash"})
    meta = r.get_json()["meta"]
    assert r.status_code == 200 and meta["model"] == "gemini-3.5-flash-lite"
    assert meta["fallback_from"] == "gemini-3.8-flash" and meta["fallback_from_label"] == "Gemini 3.8 Flash"
    # У режимі порівняння резерв не вмикається: Flash показує помилку, Flash-Lite — результат.
    r = client.post("/api/compare", json={"code": "print('hello world')"})
    res = r.get_json()["results"]
    assert [x["ok"] for x in res] == [False, True]


def test_publishable_key_falls_back_to_sqlite(monkeypatch, tmp_path):
    from reviewer import config, storage as storage_mod
    monkeypatch.setattr(config, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_publishable_abc")
    monkeypatch.setattr(config, "SQLITE_PATH", str(tmp_path / "h.db"))
    assert isinstance(storage_mod.make_storage(), storage_mod.SQLiteStorage)
    monkeypatch.setattr(config, "SUPABASE_KEY", "sb_secret_abc")
    assert isinstance(storage_mod.make_storage(), storage_mod.SupabaseStorage)


def test_daily_quota_no_retry_and_fast_fail(monkeypatch):
    """Денний ліміт: без повторів, перехід на резерв, а без резерву миттєва відповідь із кешу."""
    from google.genai import errors
    from reviewer import gemini_client as gc

    calls = []
    daily = {"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED",
                       "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}

    class Resp:
        parsed = None
        text = '{"detected_language":"Python","score":80,"summary":"ok","strengths":[],"issues":[],"corrected_code":"x"}'
        usage_metadata = type("U", (), {"prompt_token_count": 10, "candidates_token_count": 5, "thoughts_token_count": 0})()

    class Models:
        def generate_content(self, model, **kw):
            calls.append(model)
            if model == "gemini-3.8-flash":
                raise errors.ClientError(429, daily)
            return Resp()

    monkeypatch.setattr(gc, "get_client", lambda: type("C", (), {"models": Models()})())
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    gc._cooldown_until.clear()
    assert gc._classify(errors.ClientError(429, daily)).code == "daily_quota"
    out = gc.review_code("print(1)", "Python", "gemini-3.8-flash", fallback="gemini-3.5-flash-lite")
    assert calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite"] and out.fallback_from == "gemini-3.8-flash"
    assert out.fallback_reason == "daily_quota"
    calls.clear()
    with pytest.raises(gc.ReviewError) as e:
        gc.review_code("print(1)", "Python", "gemini-3.8-flash")
    assert e.value.code == "daily_quota" and calls == []
