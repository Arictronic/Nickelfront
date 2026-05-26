@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  echo Create it from project root:
  echo   python -m venv .venv
  echo   .venv\Scripts\activate
  echo   pip install -r requirements.txt
  exit /b 1
)

rem Fast local startup: by default do not use uvicorn --reload.
rem --reload starts an extra WatchFiles reloader process and imports backend in a
rem child process, which is slow on Windows. If you need auto-reload, run:
rem   set NICKELFRONT_BACKEND_RELOAD=1
rem   scripts\run_backend.bat
if not defined NICKELFRONT_BACKEND_RELOAD set "NICKELFRONT_BACKEND_RELOAD=0"

if /I not "%SKIP_BACKEND_MIGRATIONS%"=="1" (
  echo Applying Alembic migrations...
  python backend\apply_migrations.py
  if errorlevel 1 (
    echo Alembic migrations failed. Backend will not start.
    exit /b 1
  )
)

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
)

set "NICKELFRONT_SERVICE_NAME=backend_api"
if not defined BACKEND_API_LOG_FILE if defined LOG_FILE set "BACKEND_API_LOG_FILE=%LOG_FILE%"
if defined BACKEND_API_LOG_FILE echo Logs: %BACKEND_API_LOG_FILE%
python backend\start_server.py
endlocal
