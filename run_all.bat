@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "NF_RUN_ALL_KEEP_OPEN=1"
set "NF_RUN_ALL_ARGS=%*"

:parse_args
if "%~1"=="" goto start_run_all
if /I "%~1"=="--no-pause" set "NF_RUN_ALL_KEEP_OPEN=0"
shift
goto parse_args

:start_run_all
echo ============================================================
echo Nickelfront run_all launcher
echo Console started at: %DATE% %TIME%
echo Script: %~f0
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_all.ps1" %NF_RUN_ALL_ARGS%
set "NF_RUN_ALL_RC=%ERRORLEVEL%"

echo.
echo ============================================================
echo Nickelfront run_all finished with exit code: %NF_RUN_ALL_RC%
echo Console finished at: %DATE% %TIME%
echo ============================================================
echo.

if not "%NF_RUN_ALL_KEEP_OPEN%"=="0" pause
exit /b %NF_RUN_ALL_RC%
