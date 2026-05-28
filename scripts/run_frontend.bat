@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
cd /d "%ROOT%"
set "NF_CONSOLE_STARTED_AT=%DATE% %TIME%"
title Nickelfront Frontend

echo ============================================================
echo Nickelfront Frontend console
echo Console started at: %NF_CONSOLE_STARTED_AT%
echo Project root: %ROOT%
echo ============================================================

if exist "%ROOT%\scripts\load_env.bat" (
  call "%ROOT%\scripts\load_env.bat" "%ROOT%\.env"
  if errorlevel 1 exit /b 1
)

if not defined API_PORT set "API_PORT=8001"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined VITE_PROXY_TARGET set "VITE_PROXY_TARGET=http://127.0.0.1:%API_PORT%"

set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "NODE_OPTIONS=--dns-result-order=ipv4first"

echo Frontend proxy target: %VITE_PROXY_TARGET%
echo Frontend port: %FRONTEND_PORT%
echo Frontend command started at: %DATE% %TIME%
echo ============================================================
cd frontend
npm run dev -- --host 0.0.0.0 --port %FRONTEND_PORT% --strictPort
endlocal
