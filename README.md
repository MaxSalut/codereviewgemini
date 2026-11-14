# Рецензент — автоматичне рев'ю коду лабораторних на основі Google Gemini API

Лабораторна робота №2 з дисципліни «Хмарні обчислення».
КНУ імені Тараса Шевченка, факультет комп'ютерних наук та кібернетики, кафедра теоретичної кібернетики.
Виконав: Безверхий Максим Вікторович, група ТК-42. Викладач: Деревянченко Олександр Валерійович.

Користувач вставляє код або завантажує файл, обирає мову — сервіс надсилає код у **Google Gemini API** і отримує
**структурований JSON**: список проблем (рядок, тип, опис, як виправити), загальну оцінку 0–100 і виправлену
версію коду. Результат показується як звіт із зауваженнями «на полях» коду. Історія перевірок зберігається в
**Supabase**, сервіс розгорнуто на **Render**.

## Хмарні моделі в проєкті

| Модель | Сервіс | Що робить у проєкті |
|---|---|---|
| AIaaS | Google Gemini API (`gemini-3.8-flash`, `gemini-3.5-flash-lite`) | аналіз коду, structured output за JSON-схемою |
| DBaaS | Supabase (PostgreSQL) | таблиця `reviews` з історією перевірок |
| PaaS | Render (Free web service) | запуск Flask + Gunicorn, публічне HTTPS-посилання |
| SaaS | GitHub, Google AI Studio | зберігання коду, автодеплой; керування ключами |
| IaaS | — (не використовується: ми не орендуємо віртуальні машини і GPU) | |

## Архітектура

```
Браузер (HTML/CSS/JS)  ──HTTPS──▶  Flask на Render (PaaS)  ──▶  Google Gemini API (AIaaS)
                                         │
                                         └──REST──▶  Supabase PostgreSQL (DBaaS)
```

* Ключі API — тільки в змінних середовища (`.env` локально, **Environment** на Render), у браузер вони не потрапляють.
* Відповідь Gemini отримується через `response_mime_type="application/json"` + `response_schema` (Pydantic-модель `ReviewResult`).
* Надійність: таймаут кожної спроби (55 с), до 2 повторів при 429/5xx/таймауті, перевірка вводу, ліміт 8 перевірок/хв з однієї IP.
* Резервна модель: якщо Flash перевантажена на боці Google (503/504/429), звіт автоматично робить Flash-Lite, а інтерфейс про це попереджає. Після збою Flash 2 хв не викликається, щоб не змушувати користувача чекати. У режимі «Порівняти дві моделі» та в `benchmark.py` резерв вимкнено.
* Якщо Supabase не налаштовано — історія пишеться в локальний SQLite (`data/history.db`). Це резервний режим для запуску на ноутбуці.
* Вартість запиту рахується з `usage_metadata` (вхідні, вихідні та thinking-токени) за тарифами платного рівня.

## Структура

```
app.py                 Flask: сторінки та API (/api/review, /api/compare, /api/history, /api/health)
reviewer/config.py     налаштування, моделі та ціни
reviewer/gemini_client.py  виклик Gemini, structured output, повтори, оцінка вартості
reviewer/schemas.py    JSON-схема відповіді (Pydantic)
reviewer/storage.py    Supabase REST або SQLite, статистика
reviewer/validation.py перевірка коду і файлів
reviewer/examples.py   4 демо-приклади
templates/, static/    інтерфейс українською (адаптивний)
supabase/schema.sql    SQL для створення таблиці
scripts/benchmark.py   заміри часу і вартості (Flash vs Flash-Lite)
tests/                 автотести (pytest, без реального API)
render.yaml            налаштування деплою на Render
run_local.bat          запуск на Windows одним кліком
```

## Запуск локально (Windows)

1. Встановіть Python 3.12+ з https://www.python.org/downloads/ (галочка **Add python.exe to PATH**).
2. Двічі клацніть `run_local.bat`. Перший запуск створить `.env` і відкриє його в Блокноті.
3. Вставте `GEMINI_API_KEY` (і за бажанням `SUPABASE_URL`, `SUPABASE_SECRET_KEY`), збережіть, запустіть `run_local.bat` ще раз.
4. Відкриється http://127.0.0.1:5000

Вручну (будь-яка ОС):

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env  — і заповніть ключі
python app.py
```

Тести: `pip install pytest` → `python -m pytest -q`.
Заміри: `python scripts/benchmark.py --runs 2` → таблиця в консолі та `benchmark_results.csv`.

## База даних Supabase

Supabase → **SQL Editor** → вставити `supabase/schema.sql` → **Run**. У `.env` / Render додати:

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
```

RLS увімкнено без політик: публічний ключ таблицю не бачить, сервер працює із секретним ключем.

## Деплой на Render

1. Завантажте проєкт у репозиторій GitHub (без файлу `.env`).
2. Render → **New** → **Web Service** → підключіть репозиторій.
3. Runtime **Python 3**, Build `pip install -r requirements.txt`,
   Start `gunicorn app:app --workers 2 --threads 4 --timeout 150 --bind 0.0.0.0:$PORT`, Instance type **Free**.
4. **Environment**: `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PYTHON_VERSION=3.12.8`.
5. Після кожного `git push` / завантаження файлів Render перезбирає сервіс автоматично.

Альтернатива — **New → Blueprint**: Render прочитає `render.yaml` і попросить лише значення ключів.

Обмеження безкоштовного Render: сервіс «засинає» після 15 хв без запитів, перше відкриття — до хвилини.

## Змінні середовища

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `GEMINI_API_KEY` | — | ключ з https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-3.8-flash` | модель за замовчуванням |
| `GEMINI_THINKING_LEVEL` | `low` | рівень «роздумів»: `low`, `medium`, `high` |
| `GEMINI_TIMEOUT_SECONDS` | `55` | таймаут однієї спроби |
| `GEMINI_MAX_RETRIES` | `2` | кількість повторів |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | резервна модель при перевантаженні основної (порожнє значення вимикає) |
| `GEMINI_PRIMARY_BUDGET_SECONDS` | `60` | скільки чекати основну модель, перш ніж перейти на резервну |
| `GEMINI_MODEL_COOLDOWN_SECONDS` | `120` | скільки не викликати перевантажену модель |
| `ENABLE_PRO_MODEL` | `false` | показати `gemini-3.1-pro-preview` (лише платний рівень) |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | — | доступ до бази; без них — SQLite |

## Вартість (платний рівень, листопад 2026)

| Модель | Вхід, $/1 млн токенів | Вихід, $/1 млн | Безкоштовний рівень |
|---|---|---|---|
| gemini-3.8-flash | 0.75 (з 2027 — 1.50) | 3.75 (з 2027 — 7.50) | так |
| gemini-3.5-flash-lite | 0.30 | 2.50 | так |
| gemini-3.1-pro-preview | 2.00 | 12.00 | ні |

Типова перевірка (~1 200 вхідних і ~1 800 вихідних токенів) на Flash коштувала б близько $0.008, тобто ≈ $8 за 1000 перевірок.
У проєкті використовується лише безкоштовний рівень, тому фактично — $0.
