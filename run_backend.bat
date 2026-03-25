@echo off
chcp 65001 >nul
cd /d %~dp0

echo [INFO] Запуск FastAPI сервера...
set PYTHONPATH=backend;shared
cd backend
venv\Scripts\python.exe start_server.py
pause
