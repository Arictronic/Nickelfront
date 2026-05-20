@echo off
setlocal
cd /d %~dp0

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)

set "WORKER_SLOT=%~1"
if "%WORKER_SLOT%"=="" set "WORKER_SLOT=%RANDOM%"

set "WORKER_CONCURRENCY=%~2"
if "%WORKER_CONCURRENCY%"=="" set "WORKER_CONCURRENCY=1"

set "WORKER_POOL=%~3"
if "%WORKER_POOL%"=="" set "WORKER_POOL=solo"

cd backend
set "WORKER_NAME=worker-%WORKER_SLOT%@%COMPUTERNAME%"
celery -A app.tasks.celery_app worker --loglevel=info -n %WORKER_NAME% -E --pool=%WORKER_POOL% --concurrency=%WORKER_CONCURRENCY%
endlocal
