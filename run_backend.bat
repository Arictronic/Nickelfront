@echo off
setlocal
cd /d %~dp0

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
rem   run_backend.bat
if not defined NICKELFRONT_BACKEND_RELOAD set "NICKELFRONT_BACKEND_RELOAD=0"

if /I not "%SKIP_BACKEND_MIGRATIONS%"=="1" (
  echo Applying Alembic migrations...
  python backend\apply_migrations.py
  if errorlevel 1 (
    echo Alembic migrations failed. Backend will not start.
    exit /b 1
  )
)

set "NICKELFRONT_SERVICE_NAME=backend_api"
python backend\start_server.py
endlocal
