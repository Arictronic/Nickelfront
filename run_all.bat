@echo off
setlocal
cd /d %~dp0

call "%~dp0run_open_ports.bat"

rem Запускаются следующие сервисы:
rem 1) Redis
rem 2) Qwen Service
rem 3) Backend
rem 4) Celery Worker
rem 5) Flower
rem 6) Frontend
rem PostgreSQL должен быть запущен отдельно (порт 5433).

start "Redis" cmd /k "%~dp0run_redis.bat"
timeout /t 2 /nobreak >nul

start "Qwen Service" cmd /k "%~dp0run_qwen_service.bat"
timeout /t 2 /nobreak >nul

start "Backend" cmd /k "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul

start "Worker" cmd /k "%~dp0run_worker.bat"
timeout /t 3 /nobreak >nul

start "Flower" cmd /k "%~dp0run_flower.bat"
timeout /t 20 /nobreak >nul

start "Frontend" cmd /k "%~dp0run_frontend.bat"

echo All services started.
endlocal
