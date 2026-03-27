@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Start Frontend (Vite + React)
echo ============================================================
echo.
echo Port: 5173
echo API Proxy: http://localhost:8001
echo.

REM Check Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found!
    echo Install Node.js from https://nodejs.org/
    pause
    exit /b 1
)

REM Check node_modules
if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

echo [INFO] Starting Vite dev server...
echo.

cd frontend
call npm run dev

pause
