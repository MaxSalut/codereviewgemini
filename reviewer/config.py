"""Налаштування сервісу. Усі секрети — лише зі змінних середовища (.env локально, Environment на Render)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "так"}


# --- Google Gemini API (AIaaS) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY.isascii() or GEMINI_API_KEY.lower().startswith(("your", "встав")):
    GEMINI_API_KEY = ""  # у .env залишився шаблон замість справжнього ключа
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low").strip() or None
REQUEST_TIMEOUT_S = _int("GEMINI_TIMEOUT_SECONDS", 55)      # таймаут однієї спроби
TOTAL_DEADLINE_S = _int("GEMINI_TOTAL_DEADLINE_SECONDS", 110)  # загальний ліміт з повторами
MAX_RETRIES = _int("GEMINI_MAX_RETRIES", 2)                  # повторні спроби при збоях
# Резервна модель: якщо основна перевантажена (503/504/429), звіт робить вона. Порожнє значення вимикає.
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite").strip() or None
PRIMARY_BUDGET_S = _int("GEMINI_PRIMARY_BUDGET_SECONDS", 60)  # скільки чекати основну модель, якщо є резервна
MODEL_COOLDOWN_S = _int("GEMINI_MODEL_COOLDOWN_SECONDS", 120)  # скільки не чіпати перевантажену модель
ENABLE_PRO = _bool("ENABLE_PRO_MODEL", False)               # Pro немає на безкоштовному рівні

# Ціни платного рівня (USD за 1 млн токенів), ai.google.dev/gemini-api/docs/pricing,
# перевірено в листопаді 2026. Thinking-токени тарифікуються як вихідні.
MODELS = {
    "gemini-3.8-flash": {
        "label": "Gemini 3.8 Flash",
        "short": "Flash",
        "description": "Основна модель: найкраща якість серед безкоштовних",
        "input_price": 0.75,
        "output_price": 3.75,
        "price_note": "вступна ціна до 31.12.2026, з 2027 — $1.50 / $7.50",
        "free_tier": True,
    },
    "gemini-3.5-flash-lite": {
        "label": "Gemini 3.5 Flash-Lite",
        "short": "Flash-Lite",
        "description": "Швидша і дешевша, трохи простіший аналіз",
        "input_price": 0.30,
        "output_price": 2.50,
        "price_note": "",
        "free_tier": True,
    },
    "gemini-3.1-pro-preview": {
        "label": "Gemini 3.1 Pro (preview)",
        "short": "Pro",
        "description": "Найглибший аналіз, лише платний рівень",
        "input_price": 2.00,
        "output_price": 12.00,
        "price_note": "немає безкоштовного рівня",
        "free_tier": False,
    },
}

if DEFAULT_MODEL not in MODELS:
    MODELS[DEFAULT_MODEL] = {
        "label": DEFAULT_MODEL, "short": DEFAULT_MODEL, "description": "Модель із GEMINI_MODEL",
        "input_price": 0.0, "output_price": 0.0, "price_note": "ціна невідома", "free_tier": True,
    }


def available_models() -> dict:
    return {k: v for k, v in MODELS.items() if v["free_tier"] or ENABLE_PRO or k == DEFAULT_MODEL}


# --- Supabase (DBaaS) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "reviews").strip()
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history.db"))

# --- Обмеження вводу ---
MAX_CODE_CHARS = _int("MAX_CODE_CHARS", 40_000)
MAX_CODE_LINES = _int("MAX_CODE_LINES", 800)
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 200 * 1024)

LANGUAGES = {
    "auto": "Визначити автоматично",
    "python": "Python",
    "cpp": "C++",
    "c": "C",
    "java": "Java",
    "csharp": "C#",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "kotlin": "Kotlin",
    "php": "PHP",
    "rust": "Rust",
    "pascal": "Pascal",
    "haskell": "Haskell",
    "sql": "SQL",
}

EXTENSIONS = {
    ".py": "python", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".h": "c",
    ".c": "c", ".java": "java", ".cs": "csharp", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".go": "go", ".kt": "kotlin", ".php": "php", ".rs": "rust",
    ".pas": "pascal", ".dpr": "pascal", ".hs": "haskell", ".sql": "sql", ".txt": "auto",
}
