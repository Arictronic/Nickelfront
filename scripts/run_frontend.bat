@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fI"

cd /d "%PROJECT_ROOT%" || (
  echo [ERROR] Cannot cd to project root: %PROJECT_ROOT%
  pause
  exit /b 1
)

call :print_header

if exist "%PROJECT_ROOT%\scripts\load_env.bat" (
  call "%PROJECT_ROOT%\scripts\load_env.bat" "%PROJECT_ROOT%\.env"
)

if not defined API_HOST set "API_HOST=127.0.0.1"
if not defined API_PORT set "API_PORT=8001"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined VITE_API_URL set "VITE_API_URL=/api/v1"
if not defined VITE_PROXY_TARGET set "VITE_PROXY_TARGET=http://127.0.0.1:%API_PORT%"
if not defined VITE_BACKEND_URL set "VITE_BACKEND_URL=%VITE_PROXY_TARGET%"

where node >nul 2>nul || (
  echo [ERROR] Node.js not found in PATH.
  echo Install Node.js 20/22 LTS or make sure node.exe is available in PATH.
  pause
  exit /b 1
)
where npm >nul 2>nul || (
  echo [ERROR] npm not found in PATH.
  pause
  exit /b 1
)

if not exist "%PROJECT_ROOT%\frontend\package.json" (
  echo [ERROR] frontend\package.json not found.
  pause
  exit /b 1
)

echo Frontend API base: %VITE_API_URL%
echo Frontend proxy target: %VITE_PROXY_TARGET%
echo Frontend port: %FRONTEND_PORT%
echo Frontend command started at: %DATE% %TIME%
echo ============================================================
echo.

pushd "%PROJECT_ROOT%\frontend" >nul || (
  echo [ERROR] Cannot cd to frontend directory.
  pause
  exit /b 1
)

call :ensure_frontend_deps
if errorlevel 1 (
  popd >nul
  pause
  exit /b 1
)

call npm run dev -- --host 0.0.0.0 --port %FRONTEND_PORT% --strictPort
set "FRONTEND_RC=%ERRORLEVEL%"

popd >nul
exit /b %FRONTEND_RC%

:ensure_frontend_deps
if exist "node_modules\.bin\vite.cmd" exit /b 0
if exist "node_modules\vite\package.json" exit /b 0

echo [WARN] Vite executable not found in frontend\node_modules.
echo [INFO] Installing frontend dependencies before starting dev server...

if exist "package-lock.json" (
  call npm ci
  if not errorlevel 1 goto deps_ok
  echo [WARN] npm ci failed. Trying npm install...
)

call npm install
if errorlevel 1 (
  echo [ERROR] Failed to install frontend dependencies.
  echo Try manually:
  echo   cd /d "%PROJECT_ROOT%\frontend"
  echo   npm ci
  exit /b 1
)

:deps_ok
if not exist "node_modules\.bin\vite.cmd" if not exist "node_modules\vite\package.json" (
  echo [ERROR] Frontend dependencies installed, but vite is still missing.
  echo Check frontend\package.json dependencies/devDependencies.
  exit /b 1
)

echo [OK] Frontend dependencies are ready.
exit /b 0

:print_header
echo ============================================================
echo Nickelfront Frontend console
echo Console started at: %DATE% %TIME%
echo Project root: %PROJECT_ROOT%
echo ============================================================
exit /b 0
