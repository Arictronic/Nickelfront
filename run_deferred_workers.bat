@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "DELAY_SECONDS=%~1"
if "%DELAY_SECONDS%"=="" set "DELAY_SECONDS=35"

if exist "%ROOT%scripts\load_env.bat" (
  call "%ROOT%scripts\load_env.bat" "%ROOT%.env"
)

if not defined CELERY_WORKERS set "CELERY_WORKERS=1"
if not defined WORKER_CONCURRENCY set "WORKER_CONCURRENCY=5"
if not defined WORKER_POOL set "WORKER_POOL=threads"
if not defined WORKER_QUEUES set "WORKER_QUEUES=celery"

if not defined QWEN_QUEUE_WORKERS set "QWEN_QUEUE_WORKERS=1"
if not defined QWEN_QUEUE_NAME set "QWEN_QUEUE_NAME=qwen"
if not defined QWEN_WORKER_CONCURRENCY set "QWEN_WORKER_CONCURRENCY=5"
if not defined QWEN_WORKER_POOL set "QWEN_WORKER_POOL=threads"

if not defined CONTENT_WORKERS set "CONTENT_WORKERS=1"
if not defined CONTENT_QUEUE_NAME set "CONTENT_QUEUE_NAME=content"
if not defined CONTENT_WORKER_CONCURRENCY set "CONTENT_WORKER_CONCURRENCY=5"
if not defined CONTENT_WORKER_POOL set "CONTENT_WORKER_POOL=threads"

if not defined START_QWEN_WORKERS set "START_QWEN_WORKERS=1"
if not defined START_CONTENT_WORKERS set "START_CONTENT_WORKERS=1"
if not defined START_WORKERS set "START_WORKERS=1"
if not defined START_FLOWER set "START_FLOWER=1"

if exist "%ROOT%scripts\deferred_services_banner.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\deferred_services_banner.ps1" -DelaySeconds "%DELAY_SECONDS%"
)

if not "%DELAY_SECONDS%"=="0" timeout /t %DELAY_SECONDS% /nobreak >nul

if "%START_QWEN_WORKERS%"=="1" (
  if exist "%ROOT%run_qwen_worker.bat" (
    for /L %%I in (1,1,%QWEN_QUEUE_WORKERS%) do (
      start "Qwen Gateway %%I" cmd /k ""%ROOT%run_qwen_worker.bat" "%%I" "%QWEN_QUEUE_NAME%" "%QWEN_WORKER_POOL%" "%QWEN_WORKER_CONCURRENCY%""
    )
  ) else (
    echo [WARN] run_qwen_worker.bat not found, Qwen gateway workers were not started.
  )
)

if "%START_CONTENT_WORKERS%"=="1" (
  if exist "%ROOT%run_worker.bat" (
    for /L %%I in (1,1,%CONTENT_WORKERS%) do (
      start "Content Worker %%I" cmd /k ""%ROOT%run_worker.bat" "content-%%I" "%CONTENT_WORKER_CONCURRENCY%" "%CONTENT_WORKER_POOL%" "%CONTENT_QUEUE_NAME%""
    )
  ) else (
    echo [WARN] run_worker.bat not found, Content workers were not started.
  )
)

if "%START_WORKERS%"=="1" (
  if exist "%ROOT%run_worker.bat" (
    for /L %%I in (1,1,%CELERY_WORKERS%) do (
      start "Worker %%I" cmd /k ""%ROOT%run_worker.bat" "%%I" "%WORKER_CONCURRENCY%" "%WORKER_POOL%" "%WORKER_QUEUES%""
    )
  ) else (
    echo [WARN] run_worker.bat not found, Celery workers were not started.
  )
)

if "%START_FLOWER%"=="1" (
  if exist "%ROOT%run_flower.bat" (
    start "Flower" cmd /k ""%ROOT%run_flower.bat""
  ) else (
    echo [WARN] run_flower.bat not found, Flower was not started.
  )
)

if exist "%ROOT%scripts\deferred_services_done.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\deferred_services_done.ps1"
)

endlocal
