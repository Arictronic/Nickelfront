@echo off
setlocal
cd /d %~dp0

set REDIS_PORT=6380

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /b /c:"REDIS_URL=" ".env"`) do set "REDIS_URL=%%B"
)

if defined REDIS_URL (
  for /f "tokens=3 delims=:/ " %%A in ("%REDIS_URL%") do set "REDIS_PORT=%%A"
)

set REDIS_EXE=%~dp0redis\redis-server.exe
if not exist "%REDIS_EXE%" (
  echo Redis server not found. Downloading into %~dp0redis\ ...
  set "REDIS_ZIP=%~dp0redis.zip"
  set "REDIS_DOWNLOAD_URL=https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip='%REDIS_ZIP%'; $dest='%~dp0redis'; if(!(Test-Path $dest)){New-Item -ItemType Directory -Path $dest | Out-Null}; Invoke-WebRequest -Uri '%REDIS_DOWNLOAD_URL%' -OutFile $zip; Expand-Archive -Path $zip -DestinationPath $dest -Force; Remove-Item $zip -Force;"
  if not exist "%REDIS_EXE%" (
    echo Failed to download Redis. Check network or URL.
    echo.
    pause
    exit /b 1
  )
)

"%REDIS_EXE%" --port %REDIS_PORT% --dir "%~dp0redis" --bind 127.0.0.1

endlocal
