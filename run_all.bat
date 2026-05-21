@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"

rem ==============================================================================
rem Nickelfront run_all.bat
rem
rem Запускаются следующие сервисы:
rem 1) Redis
rem 2) Qwen Service
rem 3) Backend
rem 4) Qwen gateway workers: очередь Qwen-запросов
rem 5) Обычные Celery Worker в отдельных процессах
rem 6) Flower
rem 7) Frontend
rem
rem PostgreSQL должен быть запущен отдельно.
rem
rem RAG НЕ запускается отдельным сервисом.
rem RAG работает через backend:
rem   backend -> /api/v1/rag/* -> backend/app/services/rag_*.py
rem
rem Количество workers берётся из .env:
rem   CELERY_WORKERS=3
rem   QWEN_QUEUE_WORKERS=5
rem
rem На Windows для Celery обычно используется pool=solo.
rem Параллельность достигается несколькими отдельными worker-процессами.
rem ==============================================================================

if exist "%ROOT%scripts\load_env.bat" (
  call "%ROOT%scripts\load_env.bat" "%ROOT%.env"
)

rem ------------------------------------------------------------------------------
rem Defaults, если переменные не заданы в .env
rem ------------------------------------------------------------------------------

if not defined CELERY_WORKERS set "CELERY_WORKERS=3"
if not defined WORKER_CONCURRENCY set "WORKER_CONCURRENCY=1"
if not defined WORKER_POOL set "WORKER_POOL=solo"
if not defined WORKER_QUEUES set "WORKER_QUEUES=celery"

if not defined QWEN_QUEUE_WORKERS set "QWEN_QUEUE_WORKERS=5"
if not defined QWEN_QUEUE_NAME set "QWEN_QUEUE_NAME=qwen"
if not defined QWEN_WORKER_CONCURRENCY set "QWEN_WORKER_CONCURRENCY=1"
if not defined QWEN_WORKER_POOL set "QWEN_WORKER_POOL=%WORKER_POOL%"

if not defined START_REDIS set "START_REDIS=1"
if not defined START_QWEN_SERVICE set "START_QWEN_SERVICE=1"
if not defined START_BACKEND set "START_BACKEND=1"
if not defined START_QWEN_WORKERS set "START_QWEN_WORKERS=1"
if not defined START_WORKERS set "START_WORKERS=1"
if not defined START_FLOWER set "START_FLOWER=1"
if not defined START_FRONTEND set "START_FRONTEND=1"

rem ------------------------------------------------------------------------------
rem Info
rem ------------------------------------------------------------------------------

echo.
echo ==============================================================================
echo Nickelfront startup configuration from .env
echo ==============================================================================
echo   CELERY_WORKERS=%CELERY_WORKERS%
echo   WORKER_CONCURRENCY=%WORKER_CONCURRENCY%
echo   WORKER_POOL=%WORKER_POOL%
echo   WORKER_QUEUES=%WORKER_QUEUES%
echo.
echo   QWEN_QUEUE_WORKERS=%QWEN_QUEUE_WORKERS%
echo   QWEN_QUEUE_NAME=%QWEN_QUEUE_NAME%
echo   QWEN_WORKER_CONCURRENCY=%QWEN_WORKER_CONCURRENCY%
echo   QWEN_WORKER_POOL=%QWEN_WORKER_POOL%
echo.
echo   START_REDIS=%START_REDIS%
echo   START_QWEN_SERVICE=%START_QWEN_SERVICE%
echo   START_BACKEND=%START_BACKEND%
echo   START_QWEN_WORKERS=%START_QWEN_WORKERS%
echo   START_WORKERS=%START_WORKERS%
echo   START_FLOWER=%START_FLOWER%
echo   START_FRONTEND=%START_FRONTEND%
echo.
echo   RAG mode: backend only, standalone run_rag.bat is not started.
echo ==============================================================================

rem ------------------------------------------------------------------------------
rem Start base services
rem ------------------------------------------------------------------------------

if "%START_REDIS%"=="1" (
  if exist "%ROOT%run_redis.bat" (
    start "Redis" cmd /k ""%ROOT%run_redis.bat""
  ) else (
    echo [WARN] run_redis.bat not found, Redis was not started.
  )
)

rem Даём Redis немного времени на старт
if "%START_REDIS%"=="1" timeout /t 3 /nobreak >nul

if "%START_QWEN_SERVICE%"=="1" (
  if exist "%ROOT%run_qwen_service.bat" (
    start "Qwen Service" cmd /k ""%ROOT%run_qwen_service.bat""
  ) else (
    echo [WARN] run_qwen_service.bat not found, Qwen Service was not started.
  )
)

if "%START_BACKEND%"=="1" (
  if exist "%ROOT%run_backend.bat" (
    start "Backend" cmd /k ""%ROOT%run_backend.bat""
  ) else (
    echo [WARN] run_backend.bat not found, Backend was not started.
  )
)

rem Даём backend/qwen service время подняться перед воркерами и фронтом
timeout /t 5 /nobreak >nul

rem ------------------------------------------------------------------------------
rem Start Qwen gateway workers
rem ------------------------------------------------------------------------------

if "%START_QWEN_WORKERS%"=="1" (
  if exist "%ROOT%run_qwen_worker.bat" (
    for /L %%I in (1,1,%QWEN_QUEUE_WORKERS%) do (
      start "Qwen Gateway %%I" cmd /k ""%ROOT%run_qwen_worker.bat" "%%I" "%QWEN_QUEUE_NAME%" "%QWEN_WORKER_POOL%" "%QWEN_WORKER_CONCURRENCY%""
    )
  ) else (
    echo [WARN] run_qwen_worker.bat not found, Qwen gateway workers were not started.
  )
)

rem ------------------------------------------------------------------------------
rem Start regular Celery workers
rem ------------------------------------------------------------------------------

if "%START_WORKERS%"=="1" (
  if exist "%ROOT%run_worker.bat" (
    for /L %%I in (1,1,%CELERY_WORKERS%) do (
      start "Worker %%I" cmd /k ""%ROOT%run_worker.bat" "%%I" "%WORKER_CONCURRENCY%" "%WORKER_POOL%" "%WORKER_QUEUES%""
    )
  ) else (
    echo [WARN] run_worker.bat not found, Celery workers were not started.
  )
)

rem ------------------------------------------------------------------------------
rem Start Flower
rem ------------------------------------------------------------------------------

if "%START_FLOWER%"=="1" (
  if exist "%ROOT%run_flower.bat" (
    start "Flower" cmd /k ""%ROOT%run_flower.bat""
  ) else (
    echo [WARN] run_flower.bat not found, Flower was not started.
  )
)

rem ------------------------------------------------------------------------------
rem Start Frontend
rem ------------------------------------------------------------------------------

if "%START_FRONTEND%"=="1" (
  timeout /t 20 /nobreak >nul

  if exist "%ROOT%run_frontend.bat" (
    start "Frontend" cmd /k ""%ROOT%run_frontend.bat""
  ) else (
    echo [WARN] run_frontend.bat not found, Frontend was not started.
  )
)

echo.
echo ==============================================================================
echo All enabled services started.
echo RAG is served by backend. Standalone RAG was not started.
echo ==============================================================================
echo.

endlocal