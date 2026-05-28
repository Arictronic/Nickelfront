@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "NF_CONSOLE_STARTED_AT=%DATE% %TIME%"
title Nickelfront Redis

echo ============================================================
echo Nickelfront Redis console
echo Console started at: %NF_CONSOLE_STARTED_AT%
echo Project root: %ROOT%
echo ============================================================

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
  if errorlevel 1 exit /b 1
)

if not defined REDIS_HOST set "REDIS_HOST=127.0.0.1"
if not defined REDIS_PORT set "REDIS_PORT=6380"
if /I "%REDIS_HOST%"=="localhost" set "REDIS_HOST=127.0.0.1"

set "REDIS_EXE=%ROOT%\redis\redis-server.exe"
if not exist "%REDIS_EXE%" (
  echo [WARN] Redis executable was not found: %REDIS_EXE%
  echo [INFO] Trying to download portable Redis.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\download_redis.ps1" -ProjectRoot "%ROOT%"
  if errorlevel 1 (
    echo [ERROR] Redis could not be downloaded automatically.
    echo Place redis-server.exe into: %ROOT%\redis\
    pause
    exit /b 1
  )
)

echo Redis command started at: %DATE% %TIME%
echo Starting Redis: "%REDIS_EXE%" --port %REDIS_PORT%
echo ============================================================
"%REDIS_EXE%" --port %REDIS_PORT% --dir "%ROOT%\redis" --bind 127.0.0.1
endlocal
