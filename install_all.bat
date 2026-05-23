@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo Nickelfront: локальный установщик
echo ==========================================
echo.

set "PYTHON_CMD="

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD (
  echo [ERROR] Python не найден в PATH.
  echo Установите Python 3.11+ и попробуйте снова.
  exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js не найден в PATH.
  echo Установите Node.js 18+ и попробуйте снова.
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm не найден в PATH.
  echo Установите npm и попробуйте снова.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/7] Создание виртуального окружения...
  call %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Не удалось создать виртуальное окружение.
    exit /b 1
  )
) else (
  echo [1/7] Виртуальное окружение уже существует.
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Не удалось активировать .venv.
  exit /b 1
)

echo [2/7] Обновление pip, setuptools, wheel...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERROR] Не удалось обновить инструменты pip.
  exit /b 1
)

echo [3/7] Установка Python-зависимостей...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Не удалось установить Python-зависимости.
  exit /b 1
)

echo [4/7] Установка frontend-зависимостей...
pushd frontend
call npm install
if errorlevel 1 (
  popd
  echo [ERROR] Не удалось установить frontend-зависимости.
  exit /b 1
)
popd

echo [5/7] Установка Playwright Chromium...
python -m playwright install chromium
if errorlevel 1 (
  echo [WARN] Не удалось установить Playwright Chromium.
  echo        Парсеры с браузерной автоматизацией могут не работать, пока вы не установите его вручную.
)

echo [6/7] Подготовка локальных файлов и папок...
if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Создан .env из .env.example
  ) else (
    echo [WARN] Файл .env.example не найден, поэтому .env не был создан.
  )
) else (
  echo .env уже существует, текущий файл сохранен без изменений.
)

for %%D in (
  logs
  data
  runtime
  tmp
  uploads
  archives
  chroma_db
  redis
  models
  storage
  storage\papers_pdf
) do (
  if not exist "%%~D" mkdir "%%~D" >nul 2>nul
)

echo [7/7] Финальная проверка...
python -c "import fastapi, uvicorn, celery, sqlalchemy; print('Python dependencies OK')"
if errorlevel 1 (
  echo [ERROR] Финальная проверка Python-зависимостей завершилась ошибкой.
  exit /b 1
)

echo.
echo ==========================================
echo Установка завершена.
echo ==========================================
echo Дальше:
echo 1. Проверьте и отредактируйте .env
echo 2. Убедитесь, что PostgreSQL запущен и база данных создана
echo 3. Запустите проект через run_all.bat
echo.

endlocal
