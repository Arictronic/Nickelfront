@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"

if exist "%ROOT%\scripts\load_env.bat" call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
if not defined FLOWER_PORT set "FLOWER_PORT=5555"

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  exit /b 1
)

cd backend
set "FLOWER_API_FLAG="
if /I "%FLOWER_UNAUTHENTICATED_API%"=="true" set "FLOWER_API_FLAG=--unauthenticated_api=true"
if /I "%FLOWER_UNAUTHENTICATED_API%"=="1" set "FLOWER_API_FLAG=--unauthenticated_api=true"
if /I "%FLOWER_UNAUTHENTICATED_API%"=="yes" set "FLOWER_API_FLAG=--unauthenticated_api=true"
python -m celery -A app.tasks.celery_app flower --port=%FLOWER_PORT% %FLOWER_API_FLAG%
endlocal
