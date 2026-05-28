@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"

set "DELAY_SECONDS=%~1"
if "%DELAY_SECONDS%"=="" set "DELAY_SECONDS=0"

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
  if errorlevel 1 exit /b 1
)

call :defaults
call :normalize_urls

if not "%DELAY_SECONDS%"=="0" timeout /t %DELAY_SECONDS% /nobreak >nul

call :wait_http "%API_HEALTH_URL%" "Backend API" "%BACKEND_WAIT_SECONDS%"
if errorlevel 1 (
  echo [ERROR] Backend is not healthy. Celery workers and Flower were not started.
  exit /b 1
)

call :wait_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis" "%REDIS_WAIT_SECONDS%"
if errorlevel 1 (
  echo [ERROR] Redis is not reachable. Celery workers and Flower were not started.
  exit /b 1
)

if "%REQUIRE_QWEN_FOR_QWEN_WORKERS%"=="1" (
  call :wait_http "%QWEN_HEALTH_URL%" "Qwen service" "%QWEN_WAIT_SECONDS%"
  if errorlevel 1 (
    echo [WARN] Qwen service is not healthy; Qwen workers will be skipped.
    set "START_QWEN_WORKERS=0"
  )
)

call :start_qwen_workers
call :start_content_workers
call :start_regular_workers
call :start_flower

endlocal
exit /b 0

:set_default
if not defined %~1 set "%~1=%~2"
goto :eof

:defaults
call :set_default CELERY_WORKERS 1
call :set_default WORKER_CONCURRENCY 5
call :set_default WORKER_POOL threads
call :set_default WORKER_QUEUES celery
call :set_default QWEN_QUEUE_WORKERS 1
call :set_default QWEN_QUEUE_NAME qwen
call :set_default QWEN_WORKER_CONCURRENCY 5
call :set_default QWEN_WORKER_POOL threads
call :set_default CONTENT_WORKERS 1
call :set_default CONTENT_QUEUE_NAME content
call :set_default CONTENT_WORKER_CONCURRENCY 5
call :set_default CONTENT_WORKER_POOL threads
call :set_default START_QWEN_WORKERS 1
call :set_default START_CONTENT_WORKERS 1
call :set_default START_WORKERS 1
call :set_default START_FLOWER 1
call :set_default REDIS_HOST localhost
call :set_default REDIS_PORT 6380
call :set_default API_HOST 0.0.0.0
call :set_default API_PORT 8001
call :set_default QWEN_SERVICE_HOST 127.0.0.1
call :set_default QWEN_SERVICE_PORT 8767
call :set_default BACKEND_WAIT_SECONDS 120
call :set_default REDIS_WAIT_SECONDS 30
call :set_default QWEN_WAIT_SECONDS 60
call :set_default REQUIRE_QWEN_FOR_QWEN_WORKERS 0
goto :eof

:normalize_urls
set "API_HEALTH_HOST=127.0.0.1"
if defined API_HOST if /I not "%API_HOST%"=="0.0.0.0" if /I not "%API_HOST%"=="::" set "API_HEALTH_HOST=%API_HOST%"
set "API_HEALTH_URL=http://%API_HEALTH_HOST%:%API_PORT%/health"
set "QWEN_HEALTH_URL=http://%QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%/health"
goto :eof

:wait_tcp
setlocal
set "WT_HOST=%~1"
set "WT_PORT=%~2"
set "WT_NAME=%~3"
set "WT_SECONDS=%~4"
if not defined WT_SECONDS set "WT_SECONDS=60"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\wait_tcp.ps1" -HostName "%WT_HOST%" -Port %WT_PORT% -TimeoutSeconds %WT_SECONDS% -Name "%WT_NAME%"
set "WT_RC=%ERRORLEVEL%"
endlocal & exit /b %WT_RC%

:wait_http
setlocal
set "WH_URL=%~1"
set "WH_NAME=%~2"
set "WH_SECONDS=%~3"
if not defined WH_SECONDS set "WH_SECONDS=120"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\wait_http.ps1" -Url "%WH_URL%" -TimeoutSeconds %WH_SECONDS% -Name "%WH_NAME%"
set "WH_RC=%ERRORLEVEL%"
endlocal & exit /b %WH_RC%

:start_qwen_workers
if not "%START_QWEN_WORKERS%"=="1" goto :eof
if not exist "%ROOT%\scripts\run_qwen_worker.bat" goto :eof
echo [STEP] Starting Qwen gateway workers...
for /L %%I in (1,1,%QWEN_QUEUE_WORKERS%) do start "Qwen Gateway %%I" cmd /k call "%ROOT%\scripts\run_qwen_worker.bat" "%%I" "%QWEN_QUEUE_NAME%" "%QWEN_WORKER_POOL%" "%QWEN_WORKER_CONCURRENCY%"
goto :eof

:start_content_workers
if not "%START_CONTENT_WORKERS%"=="1" goto :eof
if not exist "%ROOT%\scripts\run_worker.bat" goto :eof
echo [STEP] Starting content workers...
for /L %%I in (1,1,%CONTENT_WORKERS%) do start "Content Worker %%I" cmd /k call "%ROOT%\scripts\run_worker.bat" "content-%%I" "%CONTENT_WORKER_CONCURRENCY%" "%CONTENT_WORKER_POOL%" "%CONTENT_QUEUE_NAME%"
goto :eof

:start_regular_workers
if not "%START_WORKERS%"=="1" goto :eof
if not exist "%ROOT%\scripts\run_worker.bat" goto :eof
echo [STEP] Starting regular workers...
for /L %%I in (1,1,%CELERY_WORKERS%) do start "Worker %%I" cmd /k call "%ROOT%\scripts\run_worker.bat" "%%I" "%WORKER_CONCURRENCY%" "%WORKER_POOL%" "%WORKER_QUEUES%"
goto :eof

:start_flower
if not "%START_FLOWER%"=="1" goto :eof
if exist "%ROOT%\scripts\run_flower.bat" start "Flower" cmd /k call "%ROOT%\scripts\run_flower.bat"
goto :eof
