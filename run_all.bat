@echo off
setlocal
cd /d %~dp0

rem Запускаются следующие сервисы:
rem 1) Redis
rem 2) Qwen Service
rem 3) Backend
rem 4) Несколько Celery Worker в отдельных процессах
rem 5) Flower
rem 6) Frontend
rem PostgreSQL должен быть запущен отдельно (порт 5433).
rem
rem На Windows для Celery используется pool=solo, поэтому параллельность
rem достигается несколькими отдельными worker-процессами.
rem Измени CELERY_WORKERS, если нужно больше/меньше воркеров.

set "CELERY_WORKERS=3"
set "WORKER_CONCURRENCY=1"
set "WORKER_POOL=solo"

start "Redis" cmd /k "%~dp0run_redis.bat"
start "Qwen Service" cmd /k "%~dp0run_qwen_service.bat"
start "Backend" cmd /k "%~dp0run_backend.bat"

timeout /t 5 /nobreak >nul

for /L %%I in (1,1,%CELERY_WORKERS%) do (
  start "Worker %%I" cmd /k "%~dp0run_worker.bat" %%I %WORKER_CONCURRENCY% %WORKER_POOL%
)

start "Flower" cmd /k "%~dp0run_flower.bat"

timeout /t 20 /nobreak >nul
start "Frontend" cmd /k "%~dp0run_frontend.bat"

echo All services started.
endlocal
