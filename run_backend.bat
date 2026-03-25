@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONPATH=backend
backend\venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
