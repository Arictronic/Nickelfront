@echo off
chcp 65001 >nul
cd /d %~dp0backend

echo [INFO] Запуск Celery worker...
venv\Scripts\celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
pause
