@echo off
rem Load KEY=VALUE pairs from .env into the current cmd process.
rem Usage: call scripts\load_env.bat "path\to\.env"
rem
rem Why a temporary .cmd is used:
rem PowerShell parses .env safely and writes plain SET commands, then this script
rem CALLs that .cmd so variables are imported into the current cmd process.
rem The temp name must be process-unique: when several workers start at the same
rem time, %RANDOM% can collide and one worker may delete another worker's temp
rem batch, producing "The batch file cannot be found" / "Не удается найти пакетный файл".

set "ENV_FILE=%~1"
if "%ENV_FILE%"=="" set "ENV_FILE=%CD%\.env"
if not exist "%ENV_FILE%" exit /b 0

set "TMP_ENV_CMD="
for /f %%G in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "[guid]::NewGuid().ToString('N')"') do set "TMP_ENV_CMD=%TEMP%\nickelfront_load_env_%%G.cmd"
if not defined TMP_ENV_CMD set "TMP_ENV_CMD=%TEMP%\nickelfront_load_env_%RANDOM%_%RANDOM%_%RANDOM%.cmd"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0load_env.ps1" "%ENV_FILE%" "%TMP_ENV_CMD%"
if errorlevel 1 (
  if exist "%TMP_ENV_CMD%" del "%TMP_ENV_CMD%" >nul 2>nul
  exit /b 1
)

if not exist "%TMP_ENV_CMD%" (
  echo [WARN] Failed to create temporary env loader: "%TMP_ENV_CMD%"
  exit /b 1
)

call "%TMP_ENV_CMD%"
set "LOAD_ENV_RC=%ERRORLEVEL%"
del "%TMP_ENV_CMD%" >nul 2>nul
exit /b %LOAD_ENV_RC%
