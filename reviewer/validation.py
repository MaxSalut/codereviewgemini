"""Перевірка вводу: сервіс не повинен падати від некоректних даних."""
from __future__ import annotations

import os

from . import config


class InputError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def decode_upload(raw: bytes, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in config.EXTENSIONS:
        allowed = ", ".join(sorted(config.EXTENSIONS))
        raise InputError("bad_file", f"Файл «{filename}» має непідтримуване розширення. Підтримуються: {allowed}.")
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise InputError("file_too_big", f"Файл завеликий. Максимум — {config.MAX_UPLOAD_BYTES // 1024} КБ.", 413)
    if b"\x00" in raw[:4096]:
        raise InputError("bad_file", "Схоже, це не текстовий файл з кодом.")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InputError("bad_file", "Не вдалося прочитати файл. Збережіть його в кодуванні UTF-8.")


def language_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    return config.EXTENSIONS.get(os.path.splitext(filename)[1].lower())


def validate_code(code: str | None) -> str:
    if code is None or not isinstance(code, str):
        raise InputError("empty", "Вставте код або завантажте файл.")
    code = code.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    code = code.strip("\n")
    if not code.strip():
        raise InputError("empty", "Вставте код або завантажте файл.")
    if len(code.strip()) < 10:
        raise InputError("too_short", "Код закороткий для рев'ю. Додайте хоча б кілька рядків.")
    if len(code) > config.MAX_CODE_CHARS:
        raise InputError("too_long", f"Код задовгий ({len(code):,} символів). Максимум — {config.MAX_CODE_CHARS:,}. Перевірте файл частинами.".replace(",", " "))
    lines = code.count("\n") + 1
    if lines > config.MAX_CODE_LINES:
        raise InputError("too_long", f"Код задовгий ({lines} рядків). Максимум — {config.MAX_CODE_LINES}. Перевірте файл частинами.")
    return code


def validate_language(lang: str | None) -> str:
    lang = (lang or "auto").strip().lower()
    return lang if lang in config.LANGUAGES else "auto"


def validate_model(model: str | None) -> str:
    models = config.available_models()
    model = (model or config.DEFAULT_MODEL).strip()
    if model not in models:
        raise InputError("bad_model", "Обрана модель недоступна.")
    return model
