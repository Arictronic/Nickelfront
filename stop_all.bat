@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================================
echo Nickelfront - Stop All Services
echo ============================================================
echo.

echo [1/4] Stopping Frontend...
taskkill /F /FI "WINDOWTITLE eq Nickelfront Frontend*" 2>nul
timeout /t 1 >nul

echo [2/4] Stopping Backend...
taskkill /F /FI "WINDOWTITLE eq Nickelfront Backend*" 2>nul
timeout /t 1 >nul

echo [3/4] Stopping Celery Worker...
taskkill /F /FI "WINDOWTITLE eq Nickelfront Celery Worker*" 2>nul
timeout /t 1 >nul

echo [4/4] Stopping Redis...
taskkill /F /FI "IMAGENAME eq redis-server.exe" 2>nul
timeout /t 1 >nul

echo.
echo ============================================================
echo All services stopped
echo ============================================================
echo.

pause
