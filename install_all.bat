@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "scripts\nickelfront_doctor_setup_FIXED_v18.bat" (
  echo [ERROR] scripts\nickelfront_doctor_setup_FIXED_v18.bat was not found.
  exit /b 1
)

call "scripts\nickelfront_doctor_setup_FIXED_v18.bat" %*
exit /b %ERRORLEVEL%
