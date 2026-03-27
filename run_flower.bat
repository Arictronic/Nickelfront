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
celery -A app.tasks.celery_app flower --port=5555
endlocal
