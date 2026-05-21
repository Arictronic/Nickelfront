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

if /I not "%SKIP_BACKEND_MIGRATIONS%"=="1" (
  echo Applying Alembic migrations...
  python backend\apply_migrations.py
  if errorlevel 1 (
    echo Alembic migrations failed. Backend will not start.
    exit /b 1
  )
)

python backend\start_server.py
endlocal
