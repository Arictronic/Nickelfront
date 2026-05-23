@echo off
setlocal
cd /d %~dp0

if exist "%~dp0scripts\load_env.bat" (
  call "%~dp0scripts\load_env.bat" "%~dp0.env"
)

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

if not "%~2"=="" set "WORKER_CONCURRENCY=%~2"
if not defined WORKER_CONCURRENCY set "WORKER_CONCURRENCY=5"

if not "%~3"=="" set "WORKER_POOL=%~3"
if not defined WORKER_POOL set "WORKER_POOL=threads"

rem Regular workers should not consume the controlled Qwen gateway queue.
rem Most project tasks use Celery's default queue: celery.
if not "%~4"=="" set "WORKER_QUEUES=%~4"
if not defined WORKER_QUEUES set "WORKER_QUEUES=celery"

cd backend
set "NICKELFRONT_SERVICE_NAME=celery_worker"
set "NICKELFRONT_WORKER_ROLE=regular"
if /I "%WORKER_QUEUES%"=="content" (
  set "NICKELFRONT_SERVICE_NAME=content_worker"
  set "NICKELFRONT_WORKER_ROLE=content"
)
set "NICKELFRONT_WORKER_QUEUES=%WORKER_QUEUES%"
set "WORKER_NAME=worker-%WORKER_SLOT%@%COMPUTERNAME%"
echo Celery worker %WORKER_NAME% listens queue(s): %WORKER_QUEUES%.
echo Service role: %NICKELFRONT_WORKER_ROLE%
echo Logs: logs\%NICKELFRONT_SERVICE_NAME%.log
echo concurrency=%WORKER_CONCURRENCY%, pool=%WORKER_POOL%
python -m celery -A app.tasks.celery_app worker --loglevel=info -n %WORKER_NAME% -Q %WORKER_QUEUES% -E --pool=%WORKER_POOL% --concurrency=%WORKER_CONCURRENCY% --without-gossip --without-mingle
endlocal
