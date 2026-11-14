"""Схема структурованої відповіді (structured output). SDK перетворює її на JSON Schema для Gemini."""
from typing import List, Literal

from pydantic import BaseModel, Field


class Issue(BaseModel):
    line: int = Field(description="Номер рядка з проблемою (з нумерації у запиті). 0 — якщо проблема стосується всього коду.")
    type: Literal["error", "bad_practice", "style"] = Field(
        description="error — помилка (баг, некоректна поведінка, падіння); bad_practice — погана практика; style — стиль/читабельність."
    )
    severity: Literal["high", "medium", "low"] = Field(description="Наскільки це важливо виправити.")
    title: str = Field(description="Коротка назва проблеми, до 8 слів, українською.")
    description: str = Field(description="Що не так і чому, 1–3 речення українською.")
    fix: str = Field(description="Як виправити: конкретна порада або короткий фрагмент коду.")


class ReviewResult(BaseModel):
    detected_language: str = Field(description="Мова програмування коду, напр. Python, C++, Java.")
    score: int = Field(description="Загальна оцінка якості коду від 0 до 100.")
    summary: str = Field(description="Загальний висновок рецензента, 2–4 речення українською.")
    strengths: List[str] = Field(description="1–3 сильні сторони коду, коротко українською.")
    issues: List[Issue] = Field(description="Знайдені проблеми, від найважливіших до найменш важливих.")
    corrected_code: str = Field(description="Повна виправлена версія коду без нумерації рядків.")
