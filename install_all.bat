@echo off
if /I not "%NF_INSTALL_ALL_INNER%"=="1" (
  set "NF_INSTALL_ALL_INNER=1"
  set "NF_INSTALL_ALL_KEEP_OPEN=1"
  if not "%~1"=="" for %%A in (%*) do if /I "%%~A"=="--no-pause" set "NF_INSTALL_ALL_KEEP_OPEN=0"
  echo ==============================================================================
  echo Nickelfront install_all launcher
  echo Console started at: %DATE% %TIME%
  echo Script: %~f0
  echo ==============================================================================
  echo.
  cmd /d /c ""%~f0" %*"
  set "NF_INSTALL_ALL_RC=%ERRORLEVEL%"
  echo.
  echo ==============================================================================
  echo Nickelfront install_all finished with exit code: %NF_INSTALL_ALL_RC%
  echo Console finished at: %DATE% %TIME%
  echo ==============================================================================
  echo.
  if not "%NF_INSTALL_ALL_KEEP_OPEN%"=="0" pause
  exit /b %NF_INSTALL_ALL_RC%
)

setlocal EnableExtensions
cd /d "%~dp0"

if not exist "scripts\nickelfront_doctor_setup.bat" (
  echo [ERROR] scripts\nickelfront_doctor_setup.bat was not found.
  exit /b 1
)

call "scripts\nickelfront_doctor_setup.bat" %*
exit /b %ERRORLEVEL%
