@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo Nickelfront runtime cleanup
echo ============================================================
echo This script removes runtime data: papers, parser jobs, Celery/Redis
echo queues, PDF/RAG/ChromaDB files, logs and temporary caches.
echo.

if exist "%~dp0scripts\load_env.bat" (
  call "%~dp0scripts\load_env.bat" "%~dp0.env"
  if errorlevel 1 (
    echo [ERROR] Failed to load .env.
    pause
    exit /b 1
  )
)
echo Default mode keeps users, refresh_tokens, system_settings and alembic_version.
echo Use --include-users or --include-settings only if you really need it.
echo Use --dry-run to preview database cleanup without deleting anything.
echo.
echo Before running cleanup, stop these services if they are open:
echo   backend, celery workers, qwen workers, qwen_service
echo PostgreSQL and Redis must stay running.
echo.

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo [ERROR] Python virtual environment was not found.
  echo Create it from project root:
  echo   python -m venv .venv
  echo   .venv\Scripts\activate
  echo   pip install -r requirements.txt
  pause
  exit /b 1
)

python "backend\reset_runtime_data.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Cleanup failed. Exit code: %EXIT_CODE%
  pause
  exit /b %EXIT_CODE%
)

echo [OK] Cleanup finished successfully.
echo.
echo Next steps:
echo   1. Start backend/qwen/worker services again.
echo   2. If the old frontend page is still open, press Ctrl+F5 or clear browser localStorage if needed.
echo.
pause
endlocal
