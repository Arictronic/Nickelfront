@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "RUN_ALL_STARTED_AT=%DATE% %TIME%"

call :load_env
call :apply_defaults
call :normalize_urls
call :print_summary

call :start_core_services_parallel
if errorlevel 1 goto startup_failed

call :wait_core_services
if errorlevel 1 goto startup_failed

call :start_frontend
call :start_heavy_services
call :print_done

endlocal
exit /b 0

:load_env
if exist "%ROOT%scripts\load_env.bat" (
  call "%ROOT%scripts\load_env.bat" "%ROOT%.env"
  if errorlevel 1 (
    echo [ERROR] Failed to load .env.
    exit /b 1
  )
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
call :set_default REDIS_HOST localhost
call :set_default REDIS_PORT 6380
call :set_default API_HOST 0.0.0.0
call :set_default API_PORT 8001
call :set_default QWEN_SERVICE_HOST 127.0.0.1
call :set_default QWEN_SERVICE_PORT 8767
call :set_default FRONTEND_PORT 5173
call :set_default FLOWER_PORT 5555
call :set_default REDIS_WAIT_SECONDS 45
call :set_default BACKEND_WAIT_SECONDS 180
call :set_default QWEN_WAIT_SECONDS 90
call :set_default DEFER_HEAVY_SERVICES_SECONDS 0
call :set_default REQUIRE_QWEN_FOR_QWEN_WORKERS 0
goto :eof

:normalize_urls
set "API_HEALTH_HOST=127.0.0.1"
if defined API_HOST if /I not "%API_HOST%"=="0.0.0.0" if /I not "%API_HOST%"=="::" set "API_HEALTH_HOST=%API_HOST%"
set "API_HEALTH_URL=http://%API_HEALTH_HOST%:%API_PORT%/health"
set "QWEN_HEALTH_URL=http://%QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%/health"
goto :eof

:print_summary
echo.
echo ============================================================
echo Nickelfront local startup
echo Started at:   %RUN_ALL_STARTED_AT%
echo Mode:         parallel core startup
echo ============================================================
echo Redis:        %START_REDIS%  %REDIS_HOST%:%REDIS_PORT%
echo Qwen service: %START_QWEN_SERVICE%  %QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%
echo Backend:      %START_BACKEND%  %API_HEALTH_URL%
echo Frontend:     %START_FRONTEND%  port=%FRONTEND_PORT%
echo Workers:      qwen=%START_QWEN_WORKERS%, content=%START_CONTENT_WORKERS%, regular=%START_WORKERS%, flower=%START_FLOWER%
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
    start "%WINDOW_TITLE%" cmd /k call "%SCRIPT_PATH%" %SCRIPT_ARGS%
  ) else (
    start "%WINDOW_TITLE%" cmd /k call "%SCRIPT_PATH%"
  )
) else (
  echo [WARN] %WARN_NAME% was not started because "%SCRIPT_PATH%" was not found.
)
endlocal
goto :eof

:wait_tcp
setlocal
set "WT_HOST=%~1"
set "WT_PORT=%~2"
set "WT_NAME=%~3"
set "WT_SECONDS=%~4"
if not defined WT_SECONDS set "WT_SECONDS=60"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\wait_tcp.ps1" -HostName "%WT_HOST%" -Port %WT_PORT% -TimeoutSeconds %WT_SECONDS% -Name "%WT_NAME%"
set "WT_RC=%ERRORLEVEL%"
endlocal & exit /b %WT_RC%

:wait_http
setlocal
set "WH_URL=%~1"
set "WH_NAME=%~2"
set "WH_SECONDS=%~3"
if not defined WH_SECONDS set "WH_SECONDS=120"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\wait_http.ps1" -Url "%WH_URL%" -TimeoutSeconds %WH_SECONDS% -Name "%WH_NAME%"
set "WH_RC=%ERRORLEVEL%"
endlocal & exit /b %WH_RC%

:start_core_services_parallel
echo [STEP] Starting Redis, Qwen service and Backend in parallel...

if "%START_REDIS%"=="1" (
  call :wait_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis" 2
  if errorlevel 1 (
    call :start_script_window "Redis" "%ROOT%scripts\run_redis.bat" "Redis"
  ) else (
    echo [OK] Redis is already running.
  )
)

if "%START_QWEN_SERVICE%"=="1" (
  call :wait_tcp "%QWEN_SERVICE_HOST%" "%QWEN_SERVICE_PORT%" "Qwen service" 2
  if errorlevel 1 (
    call :start_script_window "Qwen Service" "%ROOT%scripts\run_qwen_service.bat" "Qwen service"
  ) else (
    echo [OK] Qwen service is already running.
  )
)

if "%START_BACKEND%"=="1" (
  call :wait_http "%API_HEALTH_URL%" "Backend API" 2
  if errorlevel 1 (
    call :start_script_window "Backend" "%ROOT%scripts\run_backend.bat" "Backend"
  ) else (
    echo [OK] Backend API is already healthy.
  )
)

exit /b 0

:wait_core_services
echo [STEP] Waiting for required core services...

if "%START_REDIS%"=="1" (
  call :wait_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis" "%REDIS_WAIT_SECONDS%"
  if errorlevel 1 (
    echo [ERROR] Redis did not become ready.
    exit /b 1
  )
)

if "%START_BACKEND%"=="1" (
  call :wait_http "%API_HEALTH_URL%" "Backend API" "%BACKEND_WAIT_SECONDS%"
  if errorlevel 1 (
    echo [ERROR] Backend API is not healthy. Heavy services will not be started.
    exit /b 1
  )
)

if "%START_QWEN_SERVICE%"=="1" (
  call :wait_tcp "%QWEN_SERVICE_HOST%" "%QWEN_SERVICE_PORT%" "Qwen service" "%QWEN_WAIT_SECONDS%"
  if errorlevel 1 (
    echo [WARN] Qwen service did not become ready. Backend can still work, Qwen workers may be skipped.
  )
)

exit /b 0

:start_frontend
if not "%START_FRONTEND%"=="1" goto :eof
echo [STEP] Frontend
call :start_script_window "Frontend" "%ROOT%scripts\run_frontend.bat" "Frontend"
exit /b 0

:start_heavy_services
if "%DEFER_HEAVY_SERVICES_SECONDS%"=="0" goto start_heavy_now
echo [STEP] Deferred workers after %DEFER_HEAVY_SERVICES_SECONDS%s
start "Deferred Workers" cmd /c call "%ROOT%scripts\run_deferred_workers.bat" "%DEFER_HEAVY_SERVICES_SECONDS%"
exit /b 0

:start_heavy_now
call "%ROOT%scripts\run_deferred_workers.bat" 0
exit /b %ERRORLEVEL%

:startup_failed
echo.
echo [ERROR] Nickelfront startup stopped before heavy services.
endlocal
exit /b 1

:print_done
echo.
echo ============================================================
echo Nickelfront startup commands were issued.
echo Started at:   %RUN_ALL_STARTED_AT%
echo Finished at:  %DATE% %TIME%
echo Open frontend: http://127.0.0.1:%FRONTEND_PORT%
echo Backend docs:  http://127.0.0.1:%API_PORT%/docs
echo ============================================================
echo.
goto :eof
