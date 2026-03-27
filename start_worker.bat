@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Start Celery Worker
echo ============================================================
echo.
echo Redis Broker: localhost:6380
echo.

REM Check virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Run: python -m venv venv
    echo Then: venv\Scripts\activate ^&^& pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo [INFO] Starting Celery worker...
echo.

cd backend
..\venv\Scripts\celery -A app.tasks.celery_app worker --loglevel=info --pool=solo

pause
