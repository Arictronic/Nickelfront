@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Start All Services
echo ============================================================
echo.
echo Ports:
echo   - PostgreSQL: 5433
echo   - Redis: 6380
echo   - Backend API: 8001
echo   - Frontend: 5173
echo.
echo ============================================================
echo.

REM Step 1: Check Redis
echo [1/5] Checking Redis...
c:\Redis\redis-cli.exe -p 6380 PING >nul 2>&1
if not errorlevel 1 (
    echo [OK] Redis running on port 6380
) else (
    echo [INFO] Starting Redis...
    start /B c:\Redis\redis-server.exe --port 6380
    timeout /t 2 >nul
    c:\Redis\redis-cli.exe -p 6380 PING >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Redis started on port 6380
    ) else (
        echo [ERROR] Failed to start Redis!
        goto :error
    )
)
echo.

REM Step 2: Check PostgreSQL
echo [2/5] Checking PostgreSQL...
venv\Scripts\python.exe -c "import psycopg2; psycopg2.connect(host='localhost', port=5433, user='postgres', password='postgres', dbname='nickelfront')" >nul 2>&1
if not errorlevel 1 (
    echo [OK] PostgreSQL running on port 5433
) else (
    echo [ERROR] PostgreSQL not available on port 5433!
    goto :error
)
echo.

REM Step 3: Start Backend
echo [3/5] Starting Backend (FastAPI, port 8001)...
start "Nickelfront Backend" cmd /k "cd /d %~dp0backend && ..\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001"
timeout /t 5 >nul
echo.

REM Step 4: Start Celery Worker
echo [4/5] Starting Celery Worker...
start "Nickelfront Celery Worker" cmd /k "cd /d %~dp0backend && ..\venv\Scripts\celery -A app.tasks.celery_app worker --loglevel=info --pool=solo"
timeout /t 3 >nul
echo.

REM Step 5: Start Frontend
echo [5/5] Starting Frontend (Vite, port 5173)...
start "Nickelfront Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 3 >nul
echo.

echo ============================================================
echo Startup complete. Checking services...
echo ============================================================
echo.
timeout /t 8 >nul

REM Check Backend
curl -s http://localhost:8001/health >nul 2>&1 && echo [OK] Backend: http://localhost:8001 || echo [FAIL] Backend

REM Check Frontend
curl -s http://localhost:5173 -m 2 >nul 2>&1 && echo [OK] Frontend: http://localhost:5173 || echo [FAIL] Frontend

REM Check Redis
c:\Redis\redis-cli.exe -p 6380 PING >nul 2>&1 && echo [OK] Redis: localhost:6380 || echo [FAIL] Redis

echo.
echo ============================================================
echo Done!
echo ============================================================
echo.
echo Services running:
echo   - PostgreSQL: localhost:5433
echo   - Redis: localhost:6380
echo   - Backend API: http://localhost:8001
echo   - Swagger UI: http://localhost:8001/docs
echo   - Frontend: http://localhost:5173
echo   - Celery Worker: separate window
echo.
echo To stop, close windows:
echo   1. Nickelfront Frontend
echo   2. Nickelfront Backend
echo   3. Nickelfront Celery Worker
echo.
echo Open browser? (Y/N)
set /p OPEN_BROWSER=
if /i "%OPEN_BROWSER%"=="Y" (
    start http://localhost:5173
)
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo STARTUP ERROR
echo ============================================================
echo.
echo Check:
echo   1. PostgreSQL running on port 5433
echo   2. c:\Redis folder exists
echo   3. All dependencies installed
echo.
pause
exit /b 1
