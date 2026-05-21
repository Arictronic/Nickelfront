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

set "WORKER_SLOT=%~1"
if "%WORKER_SLOT%"=="" set "WORKER_SLOT=%RANDOM%"

set "WORKER_CONCURRENCY=%~2"
if "%WORKER_CONCURRENCY%"=="" set "WORKER_CONCURRENCY=1"

set "WORKER_POOL=%~3"
if "%WORKER_POOL%"=="" set "WORKER_POOL=solo"

rem Regular workers should not consume the controlled Qwen gateway queue.
rem Most project tasks use Celery's default queue: celery.
set "WORKER_QUEUES=%~4"
if "%WORKER_QUEUES%"=="" set "WORKER_QUEUES=celery"

cd backend
set "WORKER_NAME=worker-%WORKER_SLOT%@%COMPUTERNAME%"
python -m celery -A app.tasks.celery_app worker --loglevel=info -n %WORKER_NAME% -Q %WORKER_QUEUES% -E --pool=%WORKER_POOL% --concurrency=%WORKER_CONCURRENCY%
endlocal
