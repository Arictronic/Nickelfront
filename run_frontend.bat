@echo off
setlocal EnableDelayedExpansion
cd /d %~dp0

rem Read API_PORT/VITE_PROXY_TARGET from root .env when variables were not already provided by the shell.
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "ENV_KEY=%%A"
        set "ENV_VALUE=%%B"
        call :trim_env_value
        if /I "%%A"=="API_PORT" if not defined API_PORT set "API_PORT=!ENV_VALUE!"
        if /I "%%A"=="VITE_PROXY_TARGET" if not defined VITE_PROXY_TARGET set "VITE_PROXY_TARGET=!ENV_VALUE!"
    )
)

rem Force local backend proxy through IPv4, but do not override a custom target.
if not defined VITE_PROXY_TARGET (
    if defined API_PORT (
        set "VITE_PROXY_TARGET=http://127.0.0.1:%API_PORT%"
    ) else (
        set "VITE_PROXY_TARGET=http://127.0.0.1:8001"
    )
)

set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "NODE_OPTIONS=--dns-result-order=ipv4first"

echo Frontend proxy target: %VITE_PROXY_TARGET%

cd frontend
npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
endlocal
exit /b

:trim_env_value
rem Strip inline comments and outer spaces from .env values used by this launcher.
for /f "tokens=1 delims=#" %%V in ("%ENV_VALUE%") do set "ENV_VALUE=%%V"
for /f "tokens=* delims= " %%V in ("%ENV_VALUE%") do set "ENV_VALUE=%%V"
exit /b
