"""Історія перевірок. Основне сховище — Supabase (DBaaS, PostgreSQL через REST API).
Якщо Supabase не налаштовано, використовується локальний файл SQLite (резервний режим для запуску на ноутбуці)."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone

import requests

from . import config

log = logging.getLogger(__name__)

COLUMNS = [
    "created_at", "language", "model", "filename", "score", "issues_count", "errors_count",
    "bad_practice_count", "style_count", "code_lines", "duration_ms", "input_tokens",
    "output_tokens", "cost_usd", "summary", "result",
]


def build_record(*, language: str, filename: str | None, code: str, outcome) -> dict:
    issues = outcome.result.get("issues", [])
    count = lambda t: sum(1 for i in issues if i.get("type") == t)  # noqa: E731
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "language": outcome.result.get("detected_language") or language,
        "model": outcome.model,
        "filename": (filename or "")[:200] or None,
        "score": outcome.result.get("score"),
        "issues_count": len(issues),
        "errors_count": count("error"),
        "bad_practice_count": count("bad_practice"),
        "style_count": count("style"),
        "code_lines": code.count("\n") + 1,
        "duration_ms": outcome.duration_ms,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens + outcome.thinking_tokens,
        "cost_usd": outcome.cost_usd,
        "summary": (outcome.result.get("summary") or "")[:1000],
        "result": outcome.result,
    }


class SupabaseStorage:
    name = "Supabase"

    def __init__(self, url: str, key: str, table: str):
        self.base = f"{url}/rest/v1/{table}"
        headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):  # старі ключі service_role (JWT) також вимагають Authorization
            headers["Authorization"] = f"Bearer {key}"
        self.http = requests.Session()
        self.http.headers.update(headers)
        self.timeout = 10

    def save(self, record: dict) -> dict | None:
        r = self.http.post(self.base, json=record, headers={"Prefer": "return=representation"}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None

    def list(self, limit: int = 300, include_result: bool = False) -> list[dict]:
        cols = "id," + ",".join(c for c in COLUMNS if include_result or c != "result")
        r = self.http.get(self.base, params={"select": cols, "order": "created_at.desc", "limit": str(limit)}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get(self, review_id: int) -> dict | None:
        r = self.http.get(self.base, params={"select": "*", "id": f"eq.{int(review_id)}"}, timeout=self.timeout)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


class SQLiteStorage:
    name = "SQLite (локально)"

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, language TEXT, model TEXT,
                filename TEXT, score INTEGER, issues_count INTEGER, errors_count INTEGER,
                bad_practice_count INTEGER, style_count INTEGER, code_lines INTEGER, duration_ms INTEGER,
                input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, summary TEXT, result TEXT)"""
            )

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, record: dict) -> dict | None:
        row = dict(record)
        row["result"] = json.dumps(row["result"], ensure_ascii=False)
        with self.lock, self._conn() as c:
            cur = c.execute(
                f"INSERT INTO reviews ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                [row[k] for k in COLUMNS],
            )
            return {"id": cur.lastrowid, **record}

    def list(self, limit: int = 300, include_result: bool = False) -> list[dict]:
        cols = "id," + ",".join(c for c in COLUMNS if include_result or c != "result")
        with self._conn() as c:
            rows = c.execute(f"SELECT {cols} FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def get(self, review_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM reviews WHERE id = ?", (int(review_id),)).fetchone()
        return self._row(r) if r else None

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        if isinstance(d.get("result"), str):
            try:
                d["result"] = json.loads(d["result"])
            except json.JSONDecodeError:
                d["result"] = None
        return d


def make_storage():
    if config.SUPABASE_KEY.startswith(("sb_publishable_", "sb_anon_")):
        log.warning("SUPABASE_SECRET_KEY містить публічний ключ (sb_publishable_...). Потрібен секретний ключ "
                    "sb_secret_... (Supabase → Project Settings → API Keys → Secret keys). Історія пишеться в SQLite.")
        return SQLiteStorage(config.SQLITE_PATH)
    if config.SUPABASE_URL and config.SUPABASE_KEY:
        return SupabaseStorage(config.SUPABASE_URL, config.SUPABASE_KEY, config.SUPABASE_TABLE)
    return SQLiteStorage(config.SQLITE_PATH)


TYPE_LABELS = {"error": "Помилки", "bad_practice": "Погані практики", "style": "Стиль"}


def compute_stats(rows: list[dict]) -> dict:
    total = len(rows)
    if not total:
        return {"total": 0}
    scores = [r["score"] for r in rows if r.get("score") is not None]
    durations = [r["duration_ms"] for r in rows if r.get("duration_ms")]
    by_type = {
        "error": sum(r.get("errors_count") or 0 for r in rows),
        "bad_practice": sum(r.get("bad_practice_count") or 0 for r in rows),
        "style": sum(r.get("style_count") or 0 for r in rows),
    }
    by_lang: dict[str, dict] = {}
    for r in rows:
        lang = r.get("language") or "—"
        e = by_lang.setdefault(lang, {"count": 0, "score_sum": 0})
        e["count"] += 1
        e["score_sum"] += r.get("score") or 0
    by_model: dict[str, dict] = {}
    for r in rows:
        m = r.get("model") or "—"
        e = by_model.setdefault(m, {"count": 0, "ms": 0, "cost": 0.0, "score": 0})
        e["count"] += 1
        e["ms"] += r.get("duration_ms") or 0
        e["cost"] += float(r.get("cost_usd") or 0)
        e["score"] += r.get("score") or 0
    timeline = [
        {"created_at": r["created_at"], "score": r.get("score")}
        for r in reversed(rows[:40]) if r.get("score") is not None
    ]
    return {
        "total": total,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None,
        "total_issues": sum(r.get("issues_count") or 0 for r in rows),
        "avg_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows) / total, 6),
        "by_type": [{"type": k, "label": TYPE_LABELS[k], "count": v} for k, v in by_type.items()],
        "by_language": sorted(
            ({"language": k, "count": v["count"], "avg_score": round(v["score_sum"] / v["count"], 1)} for k, v in by_lang.items()),
            key=lambda x: -x["count"],
        )[:8],
        "by_model": [
            {"model": k, "count": v["count"], "avg_ms": int(v["ms"] / v["count"]),
             "avg_cost_usd": round(v["cost"] / v["count"], 6), "avg_score": round(v["score"] / v["count"], 1)}
            for k, v in by_model.items()
        ],
        "timeline": timeline,
    }
