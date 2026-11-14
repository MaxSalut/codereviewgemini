@echo off
chcp 65001 >nul
title Рецензент - локальний запуск
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

if not exist ".venv\Scripts\python.exe" (
    echo Створюю віртуальне середовище .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python не знайдено. Встановіть Python з https://www.python.org/downloads/
        echo і поставте галочку "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

echo Встановлюю залежності (перший раз це займе 1-2 хвилини) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo Не вдалося встановити залежності. Перевірте інтернет.
    pause
    exit /b 1
)

if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo Створено файл .env. Відкрийте його в Блокноті, вставте GEMINI_API_KEY і запустіть цей файл ще раз.
    notepad .env
    pause
    exit /b 0
)

start "" http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py
pause
