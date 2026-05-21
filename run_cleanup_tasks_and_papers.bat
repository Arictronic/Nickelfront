@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0

echo ==========================================
echo Nickelfront: очистка runtime-данных
echo ==========================================
echo.
echo Этот сброс удаляет runtime-данные: статьи, историю задач, статистику парсеров,
echo RAG/Chroma данные, PDF, результаты анализа, логи, очереди Redis/Celery и refresh-токены.
echo.
echo Пользователи по умолчанию сохраняются, чтобы admin-логин продолжал работать.
echo Перед запуском закрой backend, обычные workers, qwen workers и qwen_service.
echo PostgreSQL и Redis можно оставить запущенными.
echo.

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Виртуальное окружение Python не найдено.
  echo Создай его из корня проекта:
  echo   python -m venv .venv
  echo   .venv\Scripts\activate
  echo   pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

python backend\reset_runtime_data.py
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
  echo Очистка завершилась с ошибкой. Код выхода: %EXIT_CODE%.
  echo.
  pause
  exit /b %EXIT_CODE%
)

echo Очистка успешно завершена.
echo.
echo Что сделать дальше:
echo   1. Запусти backend/qwen/worker сервисы заново.
echo   2. Если во frontend видна старая история, сделай hard refresh или очисти localStorage браузера.
echo.
pause
endlocal
