@echo off
setlocal
cd /d %~dp0

call "%~dp0run_open_ports.bat"

rem ????????? ??????? ???????:
rem 1) Redis
rem 2) Backend
rem 3) Celery Worker
rem 4) Flower
rem 5) Frontend
rem PostgreSQL ?????? ???? ??????? ??? ?????? (???? 5433).

start "Redis" cmd /k "%~dp0run_redis.bat"
timeout /t 2 /nobreak >nul

start "Backend" cmd /k "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul

start "Worker" cmd /k "%~dp0run_worker.bat"
timeout /t 3 /nobreak >nul

start "Flower" cmd /k "%~dp0run_flower.bat"
timeout /t 2 /nobreak >nul

start "Frontend" cmd /k "%~dp0run_frontend.bat"

echo All services started.
endlocal
