@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
cd /d "%ROOT%"

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
) else if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"FLOWER_UNAUTHENTICATED_API=" /c:"FLOWER_PORT=" ".env"`) do set "%%A=%%B"
)

if not defined FLOWER_PORT set "FLOWER_PORT=5555"

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

cd backend
set "FLOWER_API_FLAG="
if /I "%FLOWER_UNAUTHENTICATED_API%"=="true" set "FLOWER_API_FLAG=--unauthenticated_api=true"
if /I "%FLOWER_UNAUTHENTICATED_API%"=="1" set "FLOWER_API_FLAG=--unauthenticated_api=true"
if /I "%FLOWER_UNAUTHENTICATED_API%"=="yes" set "FLOWER_API_FLAG=--unauthenticated_api=true"

python -m celery -A app.tasks.celery_app flower --port=%FLOWER_PORT% %FLOWER_API_FLAG%
endlocal
