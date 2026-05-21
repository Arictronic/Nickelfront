@echo off
setlocal
cd /d %~dp0

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  echo Create it from project root and install requirements first.
  exit /b 1
)

python backend\apply_migrations.py
if errorlevel 1 (
  echo Migrations failed.
  exit /b 1
)

echo Migrations applied successfully.
endlocal
