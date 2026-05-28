@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"

if exist "%ROOT%\scripts\load_env.bat" call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  exit /b 1
)

set "QWEN_SLOT=%~1"
if "%QWEN_SLOT%"=="" set "QWEN_SLOT=%RANDOM%"
set "QWEN_NODE_SUFFIX=%RANDOM%%RANDOM%"
if not "%~2"=="" set "QWEN_QUEUE_NAME=%~2"
if not defined QWEN_QUEUE_NAME set "QWEN_QUEUE_NAME=qwen"
if not "%~3"=="" set "QWEN_WORKER_POOL=%~3"
if not defined QWEN_WORKER_POOL set "QWEN_WORKER_POOL=threads"
if not "%~4"=="" set "QWEN_WORKER_CONCURRENCY=%~4"
if not defined QWEN_WORKER_CONCURRENCY set "QWEN_WORKER_CONCURRENCY=5"

cd backend
set "QWEN_GATEWAY_WORKER=1"
set "NICKELFRONT_SERVICE_NAME=qwen_worker"
set "NICKELFRONT_WORKER_ROLE=qwen_gateway"
set "NICKELFRONT_WORKER_QUEUES=%QWEN_QUEUE_NAME%"
set "WORKER_NAME=qwen-%QWEN_SLOT%-%QWEN_NODE_SUFFIX%@%COMPUTERNAME%"
echo Qwen gateway worker %WORKER_NAME% listens queue %QWEN_QUEUE_NAME%.
echo concurrency=%QWEN_WORKER_CONCURRENCY%, pool=%QWEN_WORKER_POOL%
python -m celery -A app.tasks.celery_app worker --loglevel=info -n "%WORKER_NAME%" -Q "%QWEN_QUEUE_NAME%" -E --pool=%QWEN_WORKER_POOL% --concurrency=%QWEN_WORKER_CONCURRENCY% --without-gossip --without-mingle
endlocal
