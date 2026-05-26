@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"
set "TEST_QWEN_PY=%PROJECT_ROOT%\qwen_service\scripts\test_qwen.py"

if not exist "%TEST_QWEN_PY%" (
  echo [ERROR] File not found: %TEST_QWEN_PY%
  echo.
  pause
  exit /b 1
)

set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" "%TEST_QWEN_PY%"
) else (
  python "%TEST_QWEN_PY%"
)
set "EXITCODE=%ERRORLEVEL%"

echo.
echo ==========================================
echo Exit code: %EXITCODE%
echo Console is still open.
echo ==========================================
echo.

pause
endlocal
exit /b %EXITCODE%
