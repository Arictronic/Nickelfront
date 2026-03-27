@echo off
chcp 65001 >nul
REM =============================================================================
REM Nickelfront - Скрипт запуска проекта
REM =============================================================================
REM Запускает:
REM   1. Redis (если не запущен)
REM   2. Backend (FastAPI, порт 8000)
REM   3. Frontend (Vite, порт 5173)
REM   4. Celery Worker (если есть Redis)
REM
REM Использование:
REM   start.bat [--install] [--backend-only] [--no-flower]
REM =============================================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   NICKELFRONT - Запуск проекта
echo   Платформа для анализа научных статей
echo ============================================================
echo.

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python не найден. Установите Python 3.9+
    pause
    exit /b 1
)

REM Проверка Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js не найден. Установите Node.js 18+
    pause
    exit /b 1
)

echo [INFO] Запуск через Python скрипт...
echo.

REM Запуск Python скрипта с переданными аргументами
python run_all.py %*

endlocal
