@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "NF_CONSOLE_STARTED_AT=%DATE% %TIME%"
title Nickelfront Qwen Service

echo ============================================================
echo Nickelfront Qwen Service console
echo Console started at: %NF_CONSOLE_STARTED_AT%
echo Project root: %ROOT%
echo ============================================================

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
  if errorlevel 1 exit /b 1
)

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Python virtual environment not found.
  exit /b 1
)

if not defined QWEN_SERVICE_HOST set "QWEN_SERVICE_HOST=127.0.0.1"
if not defined QWEN_SERVICE_PORT set "QWEN_SERVICE_PORT=8767"
if not defined NICKELFRONT_SERVICE_NAME set "NICKELFRONT_SERVICE_NAME=qwen_service"
if not defined QWEN_SERVICE_LOG_FILE set "QWEN_SERVICE_LOG_FILE=logs\qwen_service.log"

echo Qwen service endpoint: http://%QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%
echo Logs: %QWEN_SERVICE_LOG_FILE%
echo Qwen command started at: %DATE% %TIME%
echo ============================================================
python qwen_service\service.py
endlocal
