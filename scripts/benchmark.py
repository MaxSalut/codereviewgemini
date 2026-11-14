"""Заміри для презентації: час відповіді, токени і вартість запиту для кожної моделі на демо-прикладах.

Запуск (з кореня проєкту, з активованим .venv і заповненим .env):
    python scripts/benchmark.py              # Flash і Flash-Lite, по 1 разу на приклад
    python scripts/benchmark.py --runs 3     # по 3 рази — середнє точніше
Результати друкуються таблицею і зберігаються в benchmark_results.csv.
Безкоштовний рівень має ліміт запитів за хвилину, тому між запитами є пауза.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reviewer import config  # noqa: E402
from reviewer.examples import EXAMPLES  # noqa: E402
from reviewer.gemini_client import ReviewError, review_code  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["gemini-3.8-flash", "gemini-3.5-flash-lite"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--pause", type=float, default=7.0, help="пауза між запитами, с")
    parser.add_argument("--out", default="benchmark_results.csv", help="файл для результатів (CSV)")
    args = parser.parse_args()

    if not config.GEMINI_API_KEY:
        sys.exit("Немає GEMINI_API_KEY у .env")

    rows = []
    for model in args.models:
        for ex in EXAMPLES:
            for run in range(1, args.runs + 1):
                label = config.LANGUAGES.get(ex["language"], "auto")
                print(f"{model:<24} {ex['id']:<16} спроба {run} …", end=" ", flush=True)
                try:
                    o = review_code(ex["code"].strip("\n"), label, model)
                    rows.append({
                        "model": model, "example": ex["id"], "run": run, "ok": 1,
                        "duration_ms": o.duration_ms, "score": o.result["score"], "issues": len(o.result["issues"]),
                        "errors": sum(i["type"] == "error" for i in o.result["issues"]),
                        "input_tokens": o.input_tokens, "output_tokens": o.output_tokens + o.thinking_tokens,
                        "cost_usd": o.cost_usd,
                    })
                    print(f"{o.duration_ms / 1000:.1f} с, оцінка {o.result['score']}, зауважень {len(o.result['issues'])}, ${o.cost_usd:.5f}")
                except ReviewError as e:
                    rows.append({"model": model, "example": ex["id"], "run": run, "ok": 0, "error": e.message})
                    print("ПОМИЛКА:", e.message)
                time.sleep(args.pause)

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.out)
    fields = ["model", "example", "run", "ok", "duration_ms", "score", "issues", "errors", "input_tokens", "output_tokens", "cost_usd", "error"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    print("\nПідсумок по моделях:")
    print(f"{'Модель':<24}{'сер. час, с':>12}{'сер. зауважень':>16}{'сер. токенів (вх/вих)':>24}{'ціна запиту':>14}{'за 1000':>10}")
    for model in args.models:
        ok = [r for r in rows if r["model"] == model and r["ok"]]
        if not ok:
            print(f"{model:<24} немає успішних запитів")
            continue
        t = statistics.mean(r["duration_ms"] for r in ok) / 1000
        iss = statistics.mean(r["issues"] for r in ok)
        ti = statistics.mean(r["input_tokens"] for r in ok)
        to = statistics.mean(r["output_tokens"] for r in ok)
        c = statistics.mean(r["cost_usd"] for r in ok)
        print(f"{model:<24}{t:>12.1f}{iss:>16.1f}{f'{ti:.0f} / {to:.0f}':>24}{f'${c:.5f}':>14}{f'${c * 1000:.2f}':>10}")
    print(f"\nДеталі збережено у {out}")


if __name__ == "__main__":
    main()
