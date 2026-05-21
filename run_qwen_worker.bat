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

set "QWEN_SLOT=%~1"
if "%QWEN_SLOT%"=="" set "QWEN_SLOT=%RANDOM%"

set "QWEN_QUEUE=%~2"
if "%QWEN_QUEUE%"=="" set "QWEN_QUEUE=qwen"

set "QWEN_POOL=%~3"
if "%QWEN_POOL%"=="" set "QWEN_POOL=solo"

cd backend
set "QWEN_GATEWAY_WORKER=1"
set "WORKER_NAME=qwen-%QWEN_SLOT%@%COMPUTERNAME%"
python -m celery -A app.tasks.celery_app worker --loglevel=info -n %WORKER_NAME% -Q %QWEN_QUEUE% -E --pool=%QWEN_POOL% --concurrency=1
endlocal
