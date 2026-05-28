@echo off
set "NF_ENV_FILE=%~1"
if "%NF_ENV_FILE%"=="" set "NF_ENV_FILE=%CD%\.env"
if not exist "%NF_ENV_FILE%" exit /b 0

set "NF_ENV_OUT="
for /f %%G in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "[guid]::NewGuid().ToString('N')" 2^>nul') do set "NF_ENV_OUT=%TEMP%\nickelfront_env_%%G.cmd"
if not defined NF_ENV_OUT set "NF_ENV_OUT=%TEMP%\nickelfront_env_%RANDOM%_%RANDOM%_%RANDOM%.cmd"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0load_env.ps1" "%NF_ENV_FILE%" "%NF_ENV_OUT%"
if errorlevel 1 (
  if exist "%NF_ENV_OUT%" del "%NF_ENV_OUT%" >nul 2>nul
  exit /b 1
)

if not exist "%NF_ENV_OUT%" exit /b 1
call "%NF_ENV_OUT%"
set "NF_ENV_RC=%ERRORLEVEL%"
del "%NF_ENV_OUT%" >nul 2>nul
exit /b %NF_ENV_RC%
