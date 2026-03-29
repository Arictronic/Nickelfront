@echo off
setlocal
cd /d %~dp0

if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)

cd backend
set WORKER_NAME=worker-celery-%RANDOM%@%COMPUTERNAME%
celery -A app.tasks.celery_app worker --loglevel=info -n %WORKER_NAME% -E --pool=solo --concurrency=1
endlocal
