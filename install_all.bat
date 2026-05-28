@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "scripts\nickelfront_doctor_setup.bat" (
  echo [ERROR] scripts\nickelfront_doctor_setup.bat was not found.
  exit /b 1
)

call "scripts\nickelfront_doctor_setup.bat" %*
exit /b %ERRORLEVEL%
