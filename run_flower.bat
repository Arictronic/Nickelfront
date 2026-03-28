@echo off
setlocal
cd /d %~dp0

if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)

rem Load FLOWER_UNAUTHENTICATED_API from root .env
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"FLOWER_UNAUTHENTICATED_API=" ".env"`) do set "FLOWER_UNAUTHENTICATED_API=%%B"
)

cd backend
set "FLOWER_API_FLAG="
if /I "%FLOWER_UNAUTHENTICATED_API%"=="true" set "FLOWER_API_FLAG=--unauthenticated_api=true"
if /I "%FLOWER_UNAUTHENTICATED_API%"=="1" set "FLOWER_API_FLAG=--unauthenticated_api=true"

celery -A app.tasks.celery_app flower --port=5555 %FLOWER_API_FLAG%
endlocal
