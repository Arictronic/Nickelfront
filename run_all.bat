@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Запуск всех компонентов
echo ============================================================
echo.

REM Проверка Redis (Docker)
echo [1/3] Проверка Redis...
docker ps | findstr redis >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Redis не запущен! Запустите Docker или: docker run -d -p 6379:6379 redis
    pause
    exit /b 1
)
echo [OK] Redis работает
echo.

REM Запуск Celery worker
echo [2/3] Запуск Celery worker...
start "Celery Worker" cmd /k "cd backend && run_worker.bat"
echo [OK] Worker запущен
timeout /t 3 >nul
echo.

REM Запуск сервера
echo [3/3] Запуск FastAPI сервера...
start "FastAPI Server" cmd /k "run_backend.bat"
echo [OK] Сервер запущен
echo.

echo ============================================================
echo Готово!
echo ============================================================
echo.
echo Сервисы:
echo   - Redis: localhost:6379 (Docker)
echo   - Worker: отдельное окно
echo   - API: http://localhost:8000
echo   - Swagger: http://localhost:8000/docs
echo.
echo Для остановки закройте окна "FastAPI Server" и "Celery Worker"
echo.
pause >nul
