@echo off
rem Load simple KEY=VALUE pairs from .env into the current cmd process.
rem Usage: call scripts\load_env.bat "path\to\.env"
rem Notes:
rem - Lines starting with # are ignored.
rem - Existing variables are overwritten by .env values.
rem - Secret values are not printed.

set "ENV_FILE=%~1"
if "%ENV_FILE%"=="" set "ENV_FILE=%CD%\.env"
if not exist "%ENV_FILE%" exit /b 0

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
  if not "%%~A"=="" (
    set "%%~A=%%~B"
  )
)
exit /b 0
