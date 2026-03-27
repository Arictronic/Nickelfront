@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Start Backend (FastAPI)
echo ============================================================
echo.
echo Port: 8001
echo Swagger: http://localhost:8001/docs
echo.

REM Check virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Run: python -m venv venv
    echo Then: venv\Scripts\activate ^&^& pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo [INFO] Starting FastAPI server...
echo.

cd backend
..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001

pause
