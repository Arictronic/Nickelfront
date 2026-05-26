@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"

rem ------------------------------------------------------------------------------
rem Nickelfront: main local startup script
rem
rem Startup order:
rem 1. Redis
rem 2. Qwen service
rem 3. Backend
rem 4. Frontend
rem 5. Heavy services later: qwen workers, content workers, regular workers, Flower
rem
rem Notes:
rem - PostgreSQL must already be running separately.
rem - RAG is served through backend; no standalone RAG service is started here.
rem ------------------------------------------------------------------------------

call :load_env
call :apply_defaults
call :print_summary

call :start_base_services
call :start_frontend_early_if_needed
call :start_heavy_services_or_defer
call :start_frontend_late_if_needed
call :print_done

endlocal
exit /b 0

:load_env
if exist "%ROOT%scripts\load_env.bat" (
  call "%ROOT%scripts\load_env.bat" "%ROOT%.env"
)
goto :eof

:set_default
if not defined %~1 set "%~1=%~2"
goto :eof

:apply_defaults
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

call :set_default START_REDIS 1
call :set_default START_QWEN_SERVICE 1
call :set_default START_BACKEND 1
call :set_default START_QWEN_WORKERS 1
call :set_default START_CONTENT_WORKERS 1
call :set_default START_WORKERS 1
call :set_default START_FLOWER 1
call :set_default START_FRONTEND 1

call :set_default FAST_UI_STARTUP 1
call :set_default DEFER_HEAVY_SERVICES 1
call :set_default DEFER_HEAVY_SERVICES_SECONDS 35
call :set_default FRONTEND_START_DELAY_SECONDS 2
call :set_default REDIS_START_DELAY_SECONDS 2
goto :eof

:print_summary
echo.
echo ============================================================
echo Nickelfront local startup
echo ============================================================
echo Base services:
echo   Redis=%START_REDIS%  QwenService=%START_QWEN_SERVICE%  Backend=%START_BACKEND%  Frontend=%START_FRONTEND%
echo Workers:
echo   QwenWorkers=%START_QWEN_WORKERS% x %QWEN_QUEUE_WORKERS%
echo   ContentWorkers=%START_CONTENT_WORKERS% x %CONTENT_WORKERS%
echo   RegularWorkers=%START_WORKERS% x %CELERY_WORKERS%
echo   Flower=%START_FLOWER%
echo Mode:
echo   FastUIStartup=%FAST_UI_STARTUP%  DeferHeavy=%DEFER_HEAVY_SERVICES%  Delay=%DEFER_HEAVY_SERVICES_SECONDS%s
echo Queues:
echo   Qwen=%QWEN_QUEUE_NAME%  Content=%CONTENT_QUEUE_NAME%  Regular=%WORKER_QUEUES%
echo Note:
echo   PostgreSQL must already be running.
echo   RAG works through backend and is not started separately.
echo ============================================================
echo.
goto :eof

:start_script_window
setlocal
set "WINDOW_TITLE=%~1"
set "SCRIPT_PATH=%~2"
set "WARN_NAME=%~3"
set "SCRIPT_ARGS=%~4"

if exist "%SCRIPT_PATH%" (
  if defined SCRIPT_ARGS (
    start "%WINDOW_TITLE%" cmd /k ""%SCRIPT_PATH%" %SCRIPT_ARGS%"
  ) else (
    start "%WINDOW_TITLE%" cmd /k ""%SCRIPT_PATH%""
  )
) else (
  echo [WARN] %WARN_NAME% was not started because "%SCRIPT_PATH%" was not found.
)
endlocal
goto :eof

:start_base_services
if "%START_REDIS%"=="1" (
  echo [STEP] Starting Redis...
  call :start_script_window "Redis" "%ROOT%scripts\run_redis.bat" "Redis"
  timeout /t %REDIS_START_DELAY_SECONDS% /nobreak >nul
)

if "%START_QWEN_SERVICE%"=="1" (
  echo [STEP] Starting Qwen service...
  call :start_script_window "Qwen Service" "%ROOT%scripts\run_qwen_service.bat" "Qwen service"
)

if "%START_BACKEND%"=="1" (
  echo [STEP] Starting backend...
  call :start_script_window "Backend" "%ROOT%scripts\run_backend.bat" "Backend"
)
goto :eof

:start_frontend_early_if_needed
if not "%FAST_UI_STARTUP%"=="1" goto :eof
if not "%START_FRONTEND%"=="1" goto :eof

echo [STEP] Starting frontend early...
timeout /t %FRONTEND_START_DELAY_SECONDS% /nobreak >nul
call :start_script_window "Frontend" "%ROOT%scripts\run_frontend.bat" "Frontend"
goto :eof

:start_heavy_services_or_defer
if not "%DEFER_HEAVY_SERVICES%"=="1" goto :start_heavy_now

if exist "%ROOT%scripts\run_deferred_workers.bat" (
  echo [STEP] Scheduling heavy services with delay...
  start "Deferred Workers" cmd /c ""%ROOT%scripts\run_deferred_workers.bat" "%DEFER_HEAVY_SERVICES_SECONDS%""
  goto :eof
)

echo [WARN] Deferred workers script was not found. Heavy services will start immediately.

:start_heavy_now
call :start_qwen_workers
call :start_content_workers
call :start_regular_workers
call :start_flower
goto :eof

:start_qwen_workers
if not "%START_QWEN_WORKERS%"=="1" goto :eof
if not exist "%ROOT%scripts\run_qwen_worker.bat" (
  echo [WARN] Qwen workers were not started because "%ROOT%scripts\run_qwen_worker.bat" was not found.
  goto :eof
)

echo [STEP] Starting Qwen workers...
for /L %%I in (1,1,%QWEN_QUEUE_WORKERS%) do (
  start "Qwen Gateway %%I" cmd /k ""%ROOT%scripts\run_qwen_worker.bat" "%%I" "%QWEN_QUEUE_NAME%" "%QWEN_WORKER_POOL%" "%QWEN_WORKER_CONCURRENCY%""
)
goto :eof

:start_content_workers
if not "%START_CONTENT_WORKERS%"=="1" goto :eof
if not exist "%ROOT%scripts\run_worker.bat" (
  echo [WARN] Content workers were not started because "%ROOT%scripts\run_worker.bat" was not found.
  goto :eof
)

echo [STEP] Starting content workers...
for /L %%I in (1,1,%CONTENT_WORKERS%) do (
  start "Content Worker %%I" cmd /k ""%ROOT%scripts\run_worker.bat" "content-%%I" "%CONTENT_WORKER_CONCURRENCY%" "%CONTENT_WORKER_POOL%" "%CONTENT_QUEUE_NAME%""
)
goto :eof

:start_regular_workers
if not "%START_WORKERS%"=="1" goto :eof
if not exist "%ROOT%scripts\run_worker.bat" (
  echo [WARN] Regular workers were not started because "%ROOT%scripts\run_worker.bat" was not found.
  goto :eof
)

echo [STEP] Starting regular workers...
for /L %%I in (1,1,%CELERY_WORKERS%) do (
  start "Worker %%I" cmd /k ""%ROOT%scripts\run_worker.bat" "%%I" "%WORKER_CONCURRENCY%" "%WORKER_POOL%" "%WORKER_QUEUES%""
)
goto :eof

:start_flower
if not "%START_FLOWER%"=="1" goto :eof
echo [STEP] Starting Flower...
call :start_script_window "Flower" "%ROOT%scripts\run_flower.bat" "Flower"
goto :eof

:start_frontend_late_if_needed
if "%FAST_UI_STARTUP%"=="1" goto :eof
if not "%START_FRONTEND%"=="1" goto :eof

echo [STEP] Starting frontend after backend/workers...
timeout /t 8 /nobreak >nul
call :start_script_window "Frontend" "%ROOT%scripts\run_frontend.bat" "Frontend"
goto :eof

:print_done
echo.
echo ============================================================
echo Startup sequence has been launched.
if "%DEFER_HEAVY_SERVICES%"=="1" (
  echo Heavy services will be started later by scripts\run_deferred_workers.bat.
) else (
  echo Heavy services were started immediately in this run.
)
echo Backend serves RAG functionality directly.
echo ============================================================
echo.
goto :eof
