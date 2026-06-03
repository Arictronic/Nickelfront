@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Keep the console open even when the script is launched by double-click.
if /I "%~1"=="--inner" goto :inner
cmd /k ""%~f0" --inner %*"
exit /b

:inner
shift /1
set "PROBE_ARGS="
:collect_args
if "%~1"=="" goto :args_done
set "PROBE_ARGS=%PROBE_ARGS% %~1"
shift /1
goto :collect_args
:args_done

if not defined PROBE_ARGS (
  set "PROBE_ARGS=--mode all --continue-on-error --sleep-after-upload 5"
)

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "PROBE_SCRIPT=%SCRIPT_DIR%test_qwen_file_upload.py"
set "LOG_DIR=%PROJECT_ROOT%\logs\run"
set "LOG_FILE=%LOG_DIR%\qwen_upload_probe.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
if not exist "%LOG_DIR%" (
  set "LOG_DIR=%TEMP%"
  set "LOG_FILE=%TEMP%\qwen_upload_probe.log"
)

cd /d "%PROJECT_ROOT%" || goto :fatal_cd

call :find_python
if not defined PY_EXE goto :fatal_python
if not exist "%PROBE_SCRIPT%" goto :fatal_script

call :print_header
> "%LOG_FILE%" (
  echo ==============================================================================
  echo Nickelfront Qwen service diagnostic probe
  echo ==============================================================================
  echo Project root: %PROJECT_ROOT%
  echo Launcher:     %~f0
  echo Probe script: %PROBE_SCRIPT%
  echo Log file:     %LOG_FILE%
  echo Arguments:    %PROBE_ARGS%
  echo ==============================================================================
  echo.
  echo [INFO] Python executable: %PY_EXE%
  echo [INFO] Command: "%PY_EXE%" "%PROBE_SCRIPT%" %PROBE_ARGS%
  echo.
)

call :info Python executable: %PY_EXE%
call :info Running probe through local qwen_service. Wait until the command finishes...

"%PY_EXE%" "%PROBE_SCRIPT%" %PROBE_ARGS% >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ==============================================================================
echo Probe output from log
echo ==============================================================================
type "%LOG_FILE%"
echo ==============================================================================
echo.

if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Probe finished with problems.
  echo [ERROR] Exit code: %EXIT_CODE%
  echo [ERROR] Log file: %LOG_FILE%
  echo.
  echo Useful commands:
  echo   qwen_service\scripts\run_qwen_upload_probe.bat
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode readiness
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode health
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode auth
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode text
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-and-send
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode two-step --sleep-after-upload 5
  echo   qwen_service\scripts\run_qwen_upload_probe.bat --mode all --continue-on-error --sleep-after-upload 5
) else (
  echo [OK] Probe finished successfully.
  echo [OK] Log file: %LOG_FILE%
)

echo.
echo This console will stay open.
pause
exit /b %EXIT_CODE%

:find_python
set "PY_EXE="
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" set "PY_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if not defined PY_EXE if exist "%PROJECT_ROOT%\venv\Scripts\python.exe" set "PY_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe"
if defined PY_EXE exit /b 0

where py >nul 2>nul
if "%ERRORLEVEL%"=="0" (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PY_EXE set "PY_EXE=%%P"
)
if defined PY_EXE exit /b 0

where python >nul 2>nul
if "%ERRORLEVEL%"=="0" (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do if not defined PY_EXE set "PY_EXE=%%P"
)
exit /b 0

:print_header
echo ==============================================================================
echo Nickelfront Qwen service diagnostic probe
echo ==============================================================================
echo Project root: %PROJECT_ROOT%
echo Launcher:     %~f0
echo Probe script: %PROBE_SCRIPT%
echo Log file:     %LOG_FILE%
echo Arguments:    %PROBE_ARGS%
echo ==============================================================================
echo.
exit /b 0

:info
echo [INFO] %*
exit /b 0

:fatal_cd
echo [ERROR] Cannot cd to project root: %PROJECT_ROOT%
pause
exit /b 1

:fatal_python
call :print_header
echo [ERROR] Python executable not found.
echo Tried:
echo   %PROJECT_ROOT%\.venv\Scripts\python.exe
echo   %PROJECT_ROOT%\venv\Scripts\python.exe
echo   py -3
echo   python
echo.
pause
exit /b 1

:fatal_script
call :print_header
echo [ERROR] Probe script not found:
echo   %PROBE_SCRIPT%
echo.
pause
exit /b 1
