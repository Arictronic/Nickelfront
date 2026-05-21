@echo off
setlocal
cd /d %~dp0

rem Запускаются следующие сервисы:
rem 1) Redis
rem 2) Qwen Service
rem 3) Backend
rem 4) Qwen gateway workers: ограниченная очередь Qwen-запросов
rem 5) Несколько обычных Celery Worker в отдельных процессах
rem 6) Flower
rem 7) Frontend
rem PostgreSQL должен быть запущен отдельно (порт 5433).
rem
rem На Windows для Celery используется pool=solo, поэтому параллельность
rem достигается несколькими отдельными worker-процессами.
rem Измени CELERY_WORKERS, если нужно больше/меньше воркеров.

set "CELERY_WORKERS=3"
set "WORKER_CONCURRENCY=1"
set "WORKER_POOL=solo"
set "QWEN_WORKERS=5"
set "QWEN_QUEUE=qwen"

start "Redis" cmd /k "%~dp0run_redis.bat"
start "Qwen Service" cmd /k "%~dp0run_qwen_service.bat"
start "Backend" cmd /k "%~dp0run_backend.bat"

timeout /t 5 /nobreak >nul

for /L %%I in (1,1,%QWEN_WORKERS%) do (
  start "Qwen Gateway %%I" cmd /k "%~dp0run_qwen_worker.bat" %%I %QWEN_QUEUE% %WORKER_POOL%
)

for /L %%I in (1,1,%CELERY_WORKERS%) do (
  start "Worker %%I" cmd /k "%~dp0run_worker.bat" %%I %WORKER_CONCURRENCY% %WORKER_POOL%
)

start "Flower" cmd /k "%~dp0run_flower.bat"

timeout /t 20 /nobreak >nul
start "Frontend" cmd /k "%~dp0run_frontend.bat"

echo All services started.
endlocal
