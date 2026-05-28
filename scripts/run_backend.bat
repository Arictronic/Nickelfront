@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "NF_CONSOLE_STARTED_AT=%DATE% %TIME%"
title Nickelfront Backend

echo ============================================================
echo Nickelfront Backend console
echo Console started at: %NF_CONSOLE_STARTED_AT%
echo Project root: %ROOT%
echo ============================================================

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
  if errorlevel 1 exit /b 1
)

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  exit /b 1
)

if /I not "%SKIP_BACKEND_MIGRATIONS%"=="1" (
  echo Applying Alembic migrations...
  echo Migrations started at: %DATE% %TIME%
  python backend\apply_migrations.py
  if errorlevel 1 (
    echo Alembic migrations failed. Backend will not start.
    exit /b 1
  )
  echo Migrations finished at: %DATE% %TIME%
)

set "NICKELFRONT_SERVICE_NAME=backend_api"
if not defined BACKEND_API_LOG_FILE if defined LOG_FILE set "BACKEND_API_LOG_FILE=%LOG_FILE%"
if defined BACKEND_API_LOG_FILE echo Logs: %BACKEND_API_LOG_FILE%
echo Backend server command started at: %DATE% %TIME%
echo ============================================================
python backend\start_server.py
endlocal
