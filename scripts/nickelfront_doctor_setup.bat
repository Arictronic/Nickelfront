@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Nickelfront Doctor + Setup FIXED v23

rem ============================================================================
rem Nickelfront Doctor + Setup
rem VERSION: 2026-05-28.02-INSTALL-ORCHESTRATION-FIX
rem
rem Главное в этой версии:
rem   1) Читает реальные DATABASE_URL и REDIS_URL из .env.
rem   2) Учитывает порт PostgreSQL 5433 и Redis 6380, если они указаны в .env.
rem   3) Для миграций использует backend\apply_migrations.py.
rem   4) По умолчанию работает с .venv, как run_backend.bat/run_worker.bat/run_migrations.bat.
rem   5) RAG обслуживается backend; legacy standalone rag\requirements.txt не ставится и не используется.
rem   6) Не закрывает окно при ошибке/раннем выходе, пишет логи в logs\run.
rem   7) v22: убраны хрупкие inline python/node команды, которые ломались в cmd.exe.
rem   8) v23: единый env-loader, constraints, Redis helper, frontend full-check, health-gated run_all.
rem
rem ============================================================================

set "SCRIPT_VERSION=2026-05-28.02-INSTALL-ORCHESTRATION-FIX"
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "PROJECT_ROOT="
set "LOG_FILE="
set "ERROR_FILE="
set "ISSUES=0"
set "WARNINGS=0"
set "FATAL=0"
set "BEST_PY_CMD="
set "BEST_PY_VERSION="
set "BEST_PY_EXE="
set "BEST_PY_SCORE=0"
set "BEST_PY_KIND="
set "PY13_PROJECT=0"
set "VENV_DIR=.venv"
set "VENV_PY="
set "AUTO_YES=1"
set "SKIP_INSTALL=0"
set "RUN_FRONTEND_BUILD=0"
set "FULL_CHECK=0"
set "START_APP=1"
set "FORCE_INSTALL=0"
set "RECREATE_VENV=0"
set "STATE_DIR=.nickelfront_setup_state"
set "RUN_ROOT="
set "RUN_ID="
set "RUN_LOCK_DIR="
set "LATEST_LOG_FILE="
set "LATEST_ERROR_FILE="
set "UNLOCK_RUN=0"

call :parse_args %*

call :detect_project_root
if not defined PROJECT_ROOT (
    echo [FATAL] Не удалось найти корень проекта. Положи скрипт в корень Nickelfront или в папку scripts.
    echo.
    pause
    exit /b 2
)

cd /d "%PROJECT_ROOT%"

rem Все служебные файлы doctor/setup-скрипта храним только здесь.
set "RUN_ROOT=%PROJECT_ROOT%\logs\run"
if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs" >nul 2>nul
if not exist "%RUN_ROOT%" mkdir "%RUN_ROOT%" >nul 2>nul
set "STATE_DIR=%RUN_ROOT%\state"
set "LATEST_LOG_FILE=%RUN_ROOT%\setup_check_latest.log"
set "LATEST_ERROR_FILE=%RUN_ROOT%\setup_check_LAST_ERROR_latest.txt"
set "RUN_LOCK_DIR=%RUN_ROOT%\.doctor_setup.lock"

if "%UNLOCK_RUN%"=="1" (
    if exist "%RUN_LOCK_DIR%" rd /s /q "%RUN_LOCK_DIR%" >nul 2>nul
    echo [OK] Lock doctor/setup снят: "%RUN_LOCK_DIR%"
    echo.
    pause
    exit /b 0
)

2>nul mkdir "%RUN_LOCK_DIR%"
if errorlevel 1 (
    echo [FATAL] Уже запущен другой экземпляр doctor/setup или остался lock после прерывания.
    echo Lock: "%RUN_LOCK_DIR%"
    echo Если второго запуска точно нет, выполни:
    echo   "%~f0" --unlock
    echo Потом запусти скрипт снова.
    echo.
    pause
    exit /b 3
)
>"%RUN_LOCK_DIR%\started.txt" echo Started: %DATE% %TIME%
>>"%RUN_LOCK_DIR%\started.txt" echo Script: %~f0
>>"%RUN_LOCK_DIR%\started.txt" echo Project: %PROJECT_ROOT%

for /f "delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss_fff" 2^>nul') do set "RUN_ID=%%I"
if not defined RUN_ID set "RUN_ID=%RANDOM%_%RANDOM%"
set "LOG_FILE=%RUN_ROOT%\setup_check_%RUN_ID%.log"
set "ERROR_FILE=%RUN_ROOT%\setup_check_LAST_ERROR_%RUN_ID%.txt"

>"%LOG_FILE%" echo Nickelfront Doctor + Setup log
>>"%LOG_FILE%" echo Version: %SCRIPT_VERSION%
>>"%LOG_FILE%" echo Project root: %PROJECT_ROOT%
>>"%LOG_FILE%" echo Started: %DATE% %TIME%
>>"%LOG_FILE%" echo Run root: %RUN_ROOT%
>>"%LOG_FILE%" echo.
>"%ERROR_FILE%" echo Ошибок пока нет. Если установка упадёт, последняя ошибка будет здесь.

call :banner
call :preflight
call :summary

if "%SKIP_INSTALL%"=="1" goto finish_ok

if "%AUTO_YES%"=="1" (
    call :info "Авто-режим: сам проверяю зависимости, доустанавливаю только недостающее/сломанное и запускаю финальные тесты."
    set "DO_INSTALL=Y"
) else (
    echo.
    set /p "DO_INSTALL=Запустить установку/доустановку проекта сейчас? [Y/N]: "
)

if /I not "%DO_INSTALL%"=="Y" if /I not "%DO_INSTALL%"=="YES" if /I not "%DO_INSTALL%"=="Д" if /I not "%DO_INSTALL%"=="ДА" (
    call :info "Установка отменена пользователем."
    goto finish_ok
)

call :setup_project
if "%FATAL%"=="1" goto finish_error

goto finish_ok

:parse_args
rem Разбор аргументов через SHIFT безопаснее, чем FOR %%A IN (%*):
rem FOR ломается, если в аргументах/путях случайно есть спецсимволы cmd.
if "%~1"=="" exit /b 0
if /I "%~1"=="--yes" set "AUTO_YES=1"
if /I "%~1"=="-y" set "AUTO_YES=1"
if /I "%~1"=="--check-only" set "SKIP_INSTALL=1"
if /I "%~1"=="--ask" set "AUTO_YES=0"
if /I "%~1"=="--frontend-build" set "RUN_FRONTEND_BUILD=1"
if /I "%~1"=="--full-check" set "FULL_CHECK=1"
if /I "%~1"=="--full-check" set "RUN_FRONTEND_BUILD=1"
if /I "%~1"=="--no-start-app" set "START_APP=0"
if /I "%~1"=="--no-run-all" set "START_APP=0"
if /I "%~1"=="--force-install" set "FORCE_INSTALL=1"
if /I "%~1"=="--recreate-venv" set "RECREATE_VENV=1"
if /I "%~1"=="--unlock" set "UNLOCK_RUN=1"
shift
goto parse_args

:banner
echo ==============================================================================
echo Nickelfront: расширенная проверка окружения и установка зависимостей
echo Версия скрипта: %SCRIPT_VERSION%
echo Корень проекта: %PROJECT_ROOT%
echo Лог: %LOG_FILE%
echo Служебные файлы: %RUN_ROOT%
echo ==============================================================================
echo.
>>"%LOG_FILE%" echo ==============================================================================
>>"%LOG_FILE%" echo Nickelfront Doctor + Setup %SCRIPT_VERSION%
>>"%LOG_FILE%" echo ==============================================================================
exit /b 0

:detect_project_root
rem 1) Если скрипт лежит в корне.
if exist "%SCRIPT_DIR%\requirements.txt" if exist "%SCRIPT_DIR%\frontend\package.json" if exist "%SCRIPT_DIR%\backend\app\main.py" (
    set "PROJECT_ROOT=%SCRIPT_DIR%"
    exit /b 0
)
rem 2) Если скрипт лежит в scripts.
if exist "%SCRIPT_DIR%\..\requirements.txt" if exist "%SCRIPT_DIR%\..\frontend\package.json" if exist "%SCRIPT_DIR%\..\backend\app\main.py" (
    for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fI"
    exit /b 0
)
rem 3) Если запущен из корня.
if exist "%CD%\requirements.txt" if exist "%CD%\frontend\package.json" if exist "%CD%\backend\app\main.py" (
    set "PROJECT_ROOT=%CD%"
    exit /b 0
)
exit /b 1

:preflight
call :section "1. Системные инструменты"
call :detect_python_all
call :check_node
call :check_basic_commands
call :check_project_files
call :load_env

call :section "2. Virtualenv и Python-зависимости"
call :check_venv
call :check_python_packages

call :section "3. Frontend"
call :check_frontend

call :section "4. Redis/PostgreSQL/порты"
call :check_services
call :check_app_ports

call :section "5. Известные конфликтные места"
call :known_conflicts
exit /b 0

:section
echo.
echo === %~1 ===
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo === %~1 ===
exit /b 0

:ok
echo [OK] %~1
>>"%LOG_FILE%" echo [OK] %~1
exit /b 0

:warn
echo [WARN] %~1
>>"%LOG_FILE%" echo [WARN] %~1
set /a WARNINGS+=1
set /a ISSUES+=1
exit /b 0

:bad
echo [ERROR] %~1
>>"%LOG_FILE%" echo [ERROR] %~1
>>"%ERROR_FILE%" echo [ERROR] %~1
set /a ISSUES+=1
exit /b 0

:info
echo [INFO] %~1
>>"%LOG_FILE%" echo [INFO] %~1
exit /b 0

:run_logged
rem ВАЖНО: команды установки запускаются напрямую в текущей консоли.
rem Никаких PowerShell tee, никаких временных runner .cmd и никаких редиректов stdout/stderr в файл.
rem Поэтому живой вывод pip/npm/playwright виден именно в этом окне при двойном клике.
rem Команды запускаются через CALL, чтобы npm.cmd/npm.ps1 не уводили управление из этого .bat.
set "NF_RUN_CMD=%*"
if not defined NF_RUN_CMD exit /b 1
echo.
echo [CMD] %NF_RUN_CMD%
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo [CMD] %NF_RUN_CMD%
call %*
set "NF_RUN_RC=%ERRORLEVEL%"
>>"%LOG_FILE%" echo [CMD_EXIT] %NF_RUN_RC%
set "NF_RUN_CMD="
exit /b %NF_RUN_RC%

:detect_python_all
call :info "Поиск установленных Python..."

if exist "requirements.txt" (
    findstr /I /C:"Python 3.13+" "requirements.txt" >nul 2>nul && set "PY13_PROJECT=1"
)
if "%PY13_PROJECT%"=="1" (
    call :info "requirements.txt помечен как Python 3.13+, поэтому Python 3.13 будет в приоритете."
) else (
    call :info "Python 3.13 не указан как обязательный; приоритет: 3.12/3.11/3.10."
)

call :info "Пробую Python Launcher: py -0p"
call :run_logged py -0p
if errorlevel 1 (
    call :warn "Python Launcher py.exe не найден или не отвечает. Буду искать python.exe через PATH."
) else (
    call :ok "Python Launcher отвечает. Список версий записан в лог."
)

echo Найденные/проверенные Python-кандидаты:
>>"%LOG_FILE%" echo Найденные/проверенные Python-кандидаты:

if "%PY13_PROJECT%"=="1" (
    call :test_py_cmd "py -3.13" "py launcher 3.13" 1300
    call :test_py_cmd "py -3.12" "py launcher 3.12" 1200
    call :test_py_cmd "py -3.11" "py launcher 3.11" 1100
    call :test_py_cmd "py -3.10" "py launcher 3.10" 1000
) else (
    call :test_py_cmd "py -3.12" "py launcher 3.12" 1200
    call :test_py_cmd "py -3.11" "py launcher 3.11" 1100
    call :test_py_cmd "py -3.10" "py launcher 3.10" 1000
    call :test_py_cmd "py -3.13" "py launcher 3.13" 800
)
call :test_py_cmd "py -3.9"  "py launcher 3.9"  500
call :test_py_cmd "py -3.8"  "py launcher 3.8"  300
call :test_py_cmd "python"  "PATH python"       100
call :test_py_cmd "python3" "PATH python3"      100

for /f "delims=" %%P in ('where python 2^>nul') do call :test_py_path "%%P" "where python" 150
for /f "delims=" %%P in ('where python3 2^>nul') do call :test_py_path "%%P" "where python3" 150

if not defined BEST_PY_CMD (
    call :bad "Не найден рабочий Python. Нужен Python 3.10+; для этого проекта лучше 3.13 или 3.12."
    set "FATAL=1"
    exit /b 1
)

call :ok "Выбран Python: %BEST_PY_VERSION% [%BEST_PY_KIND%]"
call :info "Команда Python: %BEST_PY_CMD%"
call :info "Файл Python: %BEST_PY_EXE%"

for /f "tokens=1,2 delims=." %%a in ("%BEST_PY_VERSION%") do (
    set "BEST_PY_MAJOR=%%a"
    set "BEST_PY_MINOR=%%b"
)
if not "%BEST_PY_MAJOR%"=="3" (
    call :bad "Выбран не Python 3: %BEST_PY_VERSION%"
    set "FATAL=1"
    exit /b 1
)
if %BEST_PY_MINOR% LSS 10 (
    call :warn "Python %BEST_PY_VERSION% староват. Для проекта лучше 3.13/3.12/3.11/3.10."
)
if "%PY13_PROJECT%"=="1" if not "%BEST_PY_MINOR%"=="13" (
    call :warn "requirements.txt подписан как Python 3.13+. Выбран %BEST_PY_VERSION%. Python 3.14 допускается, если зависимости ставятся и проект запускается; базовый рекомендуемый вариант остаётся Python 3.13."
)
exit /b 0

:test_py_cmd
set "CAND_CMD=%~1"
set "CAND_KIND=%~2"
set "CAND_SCORE=%~3"
set "PYINFO="
set "PYINFO_FILE=%TEMP%\nf_pyinfo_%RANDOM%_%RANDOM%.txt"
set "PYPROBE_FILE=%TEMP%\nf_pyprobe_%RANDOM%_%RANDOM%.py"
call :write_python_probe "%PYPROBE_FILE%"
%CAND_CMD% "%PYPROBE_FILE%" >"%PYINFO_FILE%" 2>nul
if errorlevel 1 (
    del "%PYINFO_FILE%" >nul 2>nul
    del "%PYPROBE_FILE%" >nul 2>nul
    exit /b 0
)
set /p PYINFO=<"%PYINFO_FILE%"
del "%PYINFO_FILE%" >nul 2>nul
del "%PYPROBE_FILE%" >nul 2>nul
if not defined PYINFO exit /b 0
call :register_python "%CAND_CMD%" "%CAND_KIND%" "%CAND_SCORE%" "%PYINFO%"
exit /b 0

:test_py_path
set "CAND_PATH=%~1"
set "CAND_KIND=%~2"
set "CAND_SCORE=%~3"
if not exist "%CAND_PATH%" exit /b 0
set "PYINFO="
set "PYINFO_FILE=%TEMP%\nf_pyinfo_%RANDOM%_%RANDOM%.txt"
set "PYPROBE_FILE=%TEMP%\nf_pyprobe_%RANDOM%_%RANDOM%.py"
call :write_python_probe "%PYPROBE_FILE%"
"%CAND_PATH%" "%PYPROBE_FILE%" >"%PYINFO_FILE%" 2>nul
if errorlevel 1 (
    del "%PYINFO_FILE%" >nul 2>nul
    del "%PYPROBE_FILE%" >nul 2>nul
    exit /b 0
)
set /p PYINFO=<"%PYINFO_FILE%"
del "%PYINFO_FILE%" >nul 2>nul
del "%PYPROBE_FILE%" >nul 2>nul
if not defined PYINFO exit /b 0
call :register_python "%CAND_PATH%" "%CAND_KIND%" "%CAND_SCORE%" "%PYINFO%" "PATH"
exit /b 0

:write_python_probe
set "OUT_PY=%~1"
>"%OUT_PY%" echo import sys, platform
>>"%OUT_PY%" echo print(str(sys.version_info.major) + "." + str(sys.version_info.minor) + "." + str(sys.version_info.micro) + ";" + sys.executable + ";" + platform.architecture()[0])
exit /b 0

:register_python
if /I "%~5"=="PATH" (
    set "RPY_CMD="%~1""
) else (
    set "RPY_CMD=%~1"
)
set "RPY_KIND=%~2"
set "RPY_SCORE=%~3"
set "RPY_INFO=%~4"
for /f "tokens=1,2,3 delims=;" %%a in ("%RPY_INFO%") do (
    set "RPY_VER=%%a"
    set "RPY_EXE=%%b"
    set "RPY_ARCH=%%c"
)
if not defined RPY_VER exit /b 0
if not defined RPY_EXE exit /b 0
if not defined RPY_ARCH set "RPY_ARCH=unknown"

echo   - !RPY_VER! [!RPY_ARCH!] / !RPY_KIND! / !RPY_EXE!
>>"%LOG_FILE%" echo   - !RPY_VER! [!RPY_ARCH!] / !RPY_KIND! / !RPY_EXE!

for /f "tokens=1,2 delims=." %%m in ("!RPY_VER!") do (
    set "RPY_MAJOR=%%m"
    set "RPY_MINOR=%%n"
)
if not "!RPY_MAJOR!"=="3" exit /b 0
if !RPY_MINOR! LSS 10 set /a RPY_SCORE-=300

echo !RPY_ARCH! | findstr /I "64" >nul && set /a RPY_SCORE+=10
echo !RPY_EXE! | findstr /I "WindowsApps" >nul && set /a RPY_SCORE-=80

if !RPY_SCORE! GTR !BEST_PY_SCORE! (
    set "BEST_PY_SCORE=!RPY_SCORE!"
    set "BEST_PY_CMD=!RPY_CMD!"
    set "BEST_PY_VERSION=!RPY_VER!"
    set "BEST_PY_EXE=!RPY_EXE!"
    set "BEST_PY_KIND=!RPY_KIND!"
)
exit /b 0

:check_node
set "NODE_VER="
for /f "delims=" %%A in ('node --version 2^>nul') do set "NODE_VER=%%A"
if defined NODE_VER (
    call :ok "Node.js найден: %NODE_VER%"
    echo %NODE_VER% | findstr /R "^v24\." >nul && call :warn "Node.js 24 очень новый. Для Vite/React чаще безопаснее Node 20 или 22 LTS."
) else (
    call :bad "Node.js не найден. Нужен для frontend."
)

set "NPM_VER="
for /f "delims=" %%A in ('npm --version 2^>nul') do set "NPM_VER=%%A"
if defined NPM_VER (call :ok "npm найден: %NPM_VER%") else call :bad "npm не найден."
exit /b 0

:check_basic_commands
where powershell >nul 2>nul && call :ok "PowerShell найден." || call :warn "PowerShell не найден в PATH. Проверки TCP и парсинг URL будут ограничены."
where git >nul 2>nul && call :ok "Git найден." || call :warn "Git не найден. Не критично, если проект уже скачан."
where rustc >nul 2>nul && call :info "Rust найден. Для backend-RAG он обычно не нужен." || call :info "Rust не найден. Это нормально для backend-RAG и основной установки."
where cargo >nul 2>nul && call :info "Cargo найден." || call :info "Cargo не найден. Это нормально для основной установки."
exit /b 0

:check_project_files
if exist "requirements.txt" (call :ok "requirements.txt найден.") else call :bad "requirements.txt не найден."
if exist "pyproject.toml" (call :ok "pyproject.toml найден.") else call :warn "pyproject.toml не найден."
if exist "parser_alpha\requirements.txt" (
    call :warn "parser_alpha\requirements.txt найден, но отдельная установка parser-зависимостей отключена: зависимости объединены в корневой requirements.txt."
) else (
    call :ok "parser_alpha зависимости объединены в корневой requirements.txt; отдельный parser_alpha\requirements.txt не нужен."
)
if exist "rag\requirements.txt" (
    call :info "Backend-only RAG: legacy rag\requirements.txt найден, но не используется и не ставится."
) else (
    call :info "Backend-only RAG: rag\requirements.txt отсутствует — это нормально."
)
if exist "frontend\package.json" (call :ok "frontend\package.json найден.") else call :bad "frontend\package.json не найден."
if exist "frontend\package-lock.json" (call :ok "frontend\package-lock.json найден.") else call :warn "frontend\package-lock.json не найден. Будет использован npm install."
if exist ".env" (call :ok ".env найден.") else call :warn ".env не найден. Если есть .env.example, скрипт предложит создать копию."
if exist "backend\apply_migrations.py" (call :ok "Скрипт миграций найден: backend\apply_migrations.py") else call :warn "backend\apply_migrations.py не найден. Попробую Alembic напрямую."
if exist "backend\alembic.ini" (call :ok "Alembic config найден: backend\alembic.ini") else call :warn "backend\alembic.ini не найден."
if exist "qwen_service\service.py" (call :ok "qwen_service найден.") else call :warn "qwen_service\service.py не найден."
exit /b 0

:load_env
set "DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/nickelfront"
set "REDIS_URL=redis://localhost:6380/0"
set "POSTGRES_HOST=127.0.0.1"
set "POSTGRES_PORT=5433"
set "POSTGRES_DB=nickelfront"
set "POSTGRES_USER=postgres"
set "POSTGRES_PASSWORD=postgres"
set "REDIS_HOST=localhost"
set "REDIS_PORT=6380"
set "API_HOST=0.0.0.0"
set "API_PORT=8001"
set "QWEN_SERVICE_HOST=127.0.0.1"
set "QWEN_SERVICE_PORT=8767"
set "FRONTEND_PORT=5173"
set "FLOWER_PORT=5555"
set "BACKEND_WAIT_SECONDS=180"
set "QWEN_WAIT_SECONDS=90"
set "FRONTEND_WAIT_SECONDS=90"
set "REDIS_WAIT_SECONDS=30"
set "CELERY_BROKER_URL="
set "CELERY_RESULT_BACKEND="

if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        set "K=%%A"
        set "V=%%B"
        if /I "!K!"=="DATABASE_URL" set "DATABASE_URL=!V!"
        if /I "!K!"=="REDIS_URL" set "REDIS_URL=!V!"
        if /I "!K!"=="CELERY_BROKER_URL" if not defined REDIS_URL set "REDIS_URL=!V!"
        if /I "!K!"=="POSTGRES_HOST" set "POSTGRES_HOST=!V!"
        if /I "!K!"=="DB_HOST" set "POSTGRES_HOST=!V!"
        if /I "!K!"=="POSTGRES_PORT" set "POSTGRES_PORT=!V!"
        if /I "!K!"=="DB_PORT" set "POSTGRES_PORT=!V!"
        if /I "!K!"=="POSTGRES_DB" set "POSTGRES_DB=!V!"
        if /I "!K!"=="DB_NAME" set "POSTGRES_DB=!V!"
        if /I "!K!"=="POSTGRES_USER" set "POSTGRES_USER=!V!"
        if /I "!K!"=="DB_USER" set "POSTGRES_USER=!V!"
        if /I "!K!"=="POSTGRES_PASSWORD" set "POSTGRES_PASSWORD=!V!"
        if /I "!K!"=="DB_PASSWORD" set "POSTGRES_PASSWORD=!V!"
        if /I "!K!"=="REDIS_HOST" set "REDIS_HOST=!V!"
        if /I "!K!"=="REDIS_PORT" set "REDIS_PORT=!V!"
        if /I "!K!"=="API_HOST" set "API_HOST=!V!"
        if /I "!K!"=="API_PORT" set "API_PORT=!V!"
        if /I "!K!"=="QWEN_SERVICE_HOST" set "QWEN_SERVICE_HOST=!V!"
        if /I "!K!"=="QWEN_SERVICE_PORT" set "QWEN_SERVICE_PORT=!V!"
        if /I "!K!"=="FRONTEND_PORT" set "FRONTEND_PORT=!V!"
        if /I "!K!"=="VITE_PORT" set "FRONTEND_PORT=!V!"
        if /I "!K!"=="FLOWER_PORT" set "FLOWER_PORT=!V!"
        if /I "!K!"=="CELERY_BROKER_URL" set "CELERY_BROKER_URL=!V!"
        if /I "!K!"=="CELERY_RESULT_BACKEND" set "CELERY_RESULT_BACKEND=!V!"
    )
)

call :strip_quotes DATABASE_URL
call :strip_quotes REDIS_URL
call :strip_quotes POSTGRES_HOST
call :strip_quotes POSTGRES_PORT
call :strip_quotes POSTGRES_DB
call :strip_quotes POSTGRES_USER
call :strip_quotes POSTGRES_PASSWORD
call :strip_quotes REDIS_HOST
call :strip_quotes REDIS_PORT
call :strip_quotes API_HOST
call :strip_quotes API_PORT
call :strip_quotes QWEN_SERVICE_HOST
call :strip_quotes QWEN_SERVICE_PORT
call :strip_quotes FRONTEND_PORT
call :strip_quotes FLOWER_PORT
call :strip_quotes CELERY_BROKER_URL
call :strip_quotes CELERY_RESULT_BACKEND

if not defined REDIS_URL if defined CELERY_BROKER_URL set "REDIS_URL=%CELERY_BROKER_URL%"
call :parse_database_url
call :parse_redis_url

call :ok "Настройки из .env: PostgreSQL %POSTGRES_HOST%:%POSTGRES_PORT%/%POSTGRES_DB%, Redis %REDIS_HOST%:%REDIS_PORT%, API %API_HOST%:%API_PORT%, Qwen %QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%, Flower %FLOWER_PORT%, Frontend %FRONTEND_PORT%."
call :info "Таймауты ожидания сервисов внутренние, не из .env: Redis %REDIS_WAIT_SECONDS%s, Backend %BACKEND_WAIT_SECONDS%s, Qwen %QWEN_WAIT_SECONDS%s, Frontend %FRONTEND_WAIT_SECONDS%s."
>>"%LOG_FILE%" echo DATABASE_URL=%DATABASE_URL%
>>"%LOG_FILE%" echo REDIS_URL=%REDIS_URL%
>>"%LOG_FILE%" echo CELERY_BROKER_URL=%CELERY_BROKER_URL%
>>"%LOG_FILE%" echo CELERY_RESULT_BACKEND=%CELERY_RESULT_BACKEND%
exit /b 0

:strip_quotes
set "SQ_NAME=%~1"
set "SQ_VAL="
for /f "tokens=1,* delims==" %%A in ('set %SQ_NAME% 2^>nul') do set "SQ_VAL=%%B"
if defined SQ_VAL (
    set "SQ_VAL=%SQ_VAL:"=%"
    for /f "tokens=* delims= " %%S in ("!SQ_VAL!") do set "SQ_VAL=%%S"
    set "%SQ_NAME%=!SQ_VAL!"
)
exit /b 0

:parse_database_url
if not defined DATABASE_URL exit /b 0
where powershell >nul 2>nul
if errorlevel 1 exit /b 0
set "NF_URL=%DATABASE_URL%"
for /f "tokens=1,* delims==" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=[Uri]$env:NF_URL; if($u.Host){'POSTGRES_HOST='+$u.Host}; if($u.Port -gt 0){'POSTGRES_PORT='+$u.Port}; $db=$u.AbsolutePath.Trim('/'); if($db){'POSTGRES_DB='+[Uri]::UnescapeDataString($db)}; if($u.UserInfo){$p=$u.UserInfo.Split(':',2); if($p.Count -ge 1){'POSTGRES_USER='+[Uri]::UnescapeDataString($p[0])}; if($p.Count -ge 2){'POSTGRES_PASSWORD='+[Uri]::UnescapeDataString($p[1])}}" 2^>nul') do set "%%A=%%B"
exit /b 0

:parse_redis_url
if not defined REDIS_URL exit /b 0
where powershell >nul 2>nul
if errorlevel 1 exit /b 0
set "NF_URL=%REDIS_URL%"
for /f "tokens=1,* delims==" %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$u=[Uri]$env:NF_URL; if($u.Host){'REDIS_HOST='+$u.Host}; if($u.Port -gt 0){'REDIS_PORT='+$u.Port}" 2^>nul') do set "%%A=%%B"
exit /b 0

:check_venv
set "VENV_DIR="
set "VENV_PY="
set "VENV_VER="
set "VENV_EXE="
set "BROKEN_VENV_DIR="
set "PREFERRED_CREATE_VENV=.venv"

rem Project run_*.bat prefer .venv, but if only venv exists, repair/use venv.
call :probe_venv ".venv"
call :probe_venv "venv"

if defined VENV_PY (
    call :ok "Virtualenv выбран: %VENV_DIR% / Python %VENV_VER%"
    if defined BROKEN_VENV_DIR call :warn "Также найден битый virtualenv: %BROKEN_VENV_DIR%. Он не будет использоваться."
    exit /b 0
)

if exist "venv" if not exist ".venv" set "PREFERRED_CREATE_VENV=venv"
if defined BROKEN_VENV_DIR set "PREFERRED_CREATE_VENV=%BROKEN_VENV_DIR%"
call :warn "Рабочий virtualenv не найден. В install-режиме будет создан/починен: %PREFERRED_CREATE_VENV% через Python %BEST_PY_VERSION%."
exit /b 0


:probe_venv
set "PV_DIR=%~1"
set "PV_ABS="
set "PV_INFO="
set "PV_INFO_FILE=%TEMP%\nf_venv_probe_%RANDOM%_%RANDOM%.txt"
if not exist "%PV_DIR%\Scripts\python.exe" exit /b 2
for %%I in ("%PV_DIR%") do set "PV_ABS=%%~fI"

rem В v13 проверка была через FOR /F с quoted python.exe. На Windows это иногда
rem ложно падало: созданный venv рабочий, но preflight считал его битым.
rem Теперь запускаем python напрямую и читаем вывод из временного файла.
"%PV_ABS%\Scripts\python.exe" -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'.'+str(sys.version_info.micro)+';'+sys.executable)" >"%PV_INFO_FILE%" 2>>"%LOG_FILE%"
if errorlevel 1 (
    del "%PV_INFO_FILE%" >nul 2>nul
    call :warn "Virtualenv найден, но Python внутри не запускается: %PV_DIR%\Scripts\python.exe"
    if not defined BROKEN_VENV_DIR set "BROKEN_VENV_DIR=%PV_DIR%"
    exit /b 1
)
set /p PV_INFO=<"%PV_INFO_FILE%"
del "%PV_INFO_FILE%" >nul 2>nul
if not defined PV_INFO (
    call :warn "Virtualenv найден, но не удалось получить версию Python: %PV_DIR%\Scripts\python.exe"
    if not defined BROKEN_VENV_DIR set "BROKEN_VENV_DIR=%PV_DIR%"
    exit /b 1
)
if not defined VENV_PY (
    for /f "tokens=1,2 delims=;" %%a in ("%PV_INFO%") do (
        set "VENV_VER=%%a"
        set "VENV_EXE=%%b"
    )
    set "VENV_DIR=%PV_DIR%"
    set "VENV_PY=%PV_ABS%\Scripts\python.exe"
)
exit /b 0

:check_python_packages
if not defined VENV_PY (
    call :warn "Проверка Python-пакетов пропущена: venv пока нет."
    exit /b 0
)

"%VENV_PY%" -c "import fastapi,uvicorn,sqlalchemy,alembic,pydantic,redis,celery,asyncpg; print('ok')" >nul 2>>"%LOG_FILE%"
if errorlevel 1 (
    call :warn "Не все ключевые Python-зависимости импортируются. Установка попробует исправить."
) else (
    call :ok "Ключевые Python-зависимости импортируются."
)

call :run_logged "%VENV_PY%" -m pip --version
call :run_logged "%VENV_PY%" -m pip check
if errorlevel 1 (
    call :warn "pip check нашёл конфликт зависимостей. Детали выше в этой консоли и в логе: %LOG_FILE%."
) else (
    call :ok "pip check: явных конфликтов нет."
)
exit /b 0

:check_frontend
if not exist "frontend\package.json" exit /b 0
if exist "frontend\node_modules" (call :ok "frontend\node_modules найден.") else call :warn "frontend\node_modules не найден. Нужен npm install/npm ci."

call :write_frontend_deps_check_js "%TEMP%\nf_frontend_deps_check_%RANDOM%_%RANDOM%.js" "FRONT_CHECK_JS"
pushd frontend >nul
node "%FRONT_CHECK_JS%" >>"%LOG_FILE%" 2>>&1
set "FRONT_CHECK_RC=%ERRORLEVEL%"
popd >nul
del "%FRONT_CHECK_JS%" >nul 2>nul
if not "%FRONT_CHECK_RC%"=="0" (
    call :warn "frontend зависимости не полностью проверены или часть отсутствует. Установка попробует исправить. Детали в логе: %LOG_FILE%."
) else (
    call :ok "frontend\package.json и прямые зависимости быстро проверены."
)
exit /b 0

:check_services
call :check_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis"
if errorlevel 1 (
    if exist "run_redis.bat" (
        call :warn "Redis не отвечает на %REDIS_HOST%:%REDIS_PORT%. При установке попробую запустить run_redis.bat."
    ) else if exist "redis\redis-server.exe" (
        call :warn "Redis не отвечает. При установке попробую запустить redis\redis-server.exe."
    ) else (
        call :warn "Redis не отвечает и локальный запускатор не найден. Запусти Redis вручную."
    )
) else (
    call :ok "Redis отвечает на %REDIS_HOST%:%REDIS_PORT%."
)

call :check_tcp "%POSTGRES_HOST%" "%POSTGRES_PORT%" "PostgreSQL"
if errorlevel 1 (
    call :warn "PostgreSQL не отвечает на %POSTGRES_HOST%:%POSTGRES_PORT%. Проверь сервис PostgreSQL и .env."
) else (
    call :ok "PostgreSQL отвечает на %POSTGRES_HOST%:%POSTGRES_PORT%."
)

where psql >nul 2>nul && call :ok "psql найден." || call :info "psql не найден в PATH. БД буду пробовать создавать через Python/psycopg2 после установки зависимостей."
exit /b 0

:check_app_ports
call :check_tcp "127.0.0.1" "%API_PORT%" "API"
if errorlevel 1 (call :info "API порт %API_PORT% свободен или недоступен извне — это нормально до запуска backend.") else call :warn "Порт API %API_PORT% уже занят. Backend может не стартовать."
call :check_tcp "%QWEN_SERVICE_HOST%" "%QWEN_SERVICE_PORT%" "Qwen service"
if errorlevel 1 (call :info "Qwen service порт %QWEN_SERVICE_PORT% свободен или сервис пока не запущен.") else call :info "Qwen service уже отвечает на %QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT%."
call :check_tcp "127.0.0.1" "%FRONTEND_PORT%" "Frontend"
if errorlevel 1 (call :info "Frontend порт %FRONTEND_PORT% свободен или dev-server пока не запущен.") else call :warn "Frontend порт %FRONTEND_PORT% уже занят."
call :check_tcp "127.0.0.1" "%FLOWER_PORT%" "Flower"
if errorlevel 1 (call :info "Flower порт %FLOWER_PORT% свободен или Flower пока не запущен.") else call :info "Flower уже отвечает на 127.0.0.1:%FLOWER_PORT%."
exit /b 0

:check_tcp
set "TCP_HOST=%~1"
set "TCP_PORT=%~2"
where powershell >nul 2>nul
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=New-Object Net.Sockets.TcpClient; try{$iar=$c.BeginConnect('%TCP_HOST%',%TCP_PORT%,$null,$null); if($iar.AsyncWaitHandle.WaitOne(1200,$false) -and $c.Connected){$c.Close(); exit 0}else{$c.Close(); exit 1}} catch {exit 1}" >nul 2>nul
exit /b %ERRORLEVEL%

:known_conflicts
if exist "requirements.txt" (
    findstr /I /C:"torch" "requirements.txt" >nul 2>nul && call :info "В requirements есть torch: setuptools держим ниже 82, чтобы не повторять конфликт старых сборок."
    findstr /I /C:"chromadb" "requirements.txt" >nul 2>nul && call :ok "Корневой requirements содержит chromadb для backend-RAG."
    if exist "requirements-constraints.txt" (call :ok "requirements-constraints.txt найден: установка будет использовать стабильные верхние границы зависимостей.") else call :warn "requirements-constraints.txt не найден: pip может подтянуть слишком новые зависимости."
)
if exist "rag\requirements.txt" (
    call :info "Backend-only RAG: legacy rag\requirements.txt не ставится и не нужен для обычного запуска."
)
exit /b 0

:summary
echo.
echo === Итог проверки ===
echo [INFO] Найдено предупреждений/пунктов: %ISSUES%.
echo [INFO] Лог: "%LOG_FILE%"
echo [INFO] Последняя ошибка, если будет: "%ERROR_FILE%"
echo.
>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo === Итог проверки ===
>>"%LOG_FILE%" echo Issues: %ISSUES%
exit /b 0

:setup_project
call :section "Установка/доустановка Nickelfront"

if "%FATAL%"=="1" (
    call :bad "Есть критическая ошибка preflight. Установка остановлена."
    exit /b 1
)

call :ensure_env
call :load_env
call :ensure_runtime_dirs
call :ensure_venv
if "%FATAL%"=="1" exit /b 1

call :install_python_deps
if "%FATAL%"=="1" exit /b 1

call :install_playwright_browsers
call :install_frontend_deps
if "%FATAL%"=="1" exit /b 1

call :ensure_redis_launcher
call :prepare_database
call :run_migrations
call :final_healthcheck
call :start_project_services
exit /b 0

:ensure_env
if exist ".env" exit /b 0
if exist ".env.example" (
    copy ".env.example" ".env" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (call :warn "Не удалось создать .env из .env.example.") else call :ok "Создан .env из .env.example. Проверь значения вручную."
) else (
    call :warn ".env отсутствует и .env.example не найден. Создай .env вручную."
)
exit /b 0

:ensure_runtime_dirs
for %%D in ("logs" "logs\run" "logs\run\tmp" "logs\run\backups" "data" "storage" "uploads" "tmp" "runtime" "chroma_db" "models" "%STATE_DIR%") do (
    if not exist %%~D mkdir %%~D >>"%LOG_FILE%" 2>>&1
)
call :ok "Runtime-папки созданы/проверены."
exit /b 0

:ensure_venv
if "%RECREATE_VENV%"=="1" (
    call :warn "Флаг --recreate-venv: virtualenv будет пересоздан."
) else (
    if defined VENV_PY if exist "%VENV_PY%" (
        "%VENV_PY%" -c "import sys; print(sys.version)" >>"%LOG_FILE%" 2>>&1
        if not errorlevel 1 (
            call :info "Использую существующий рабочий venv: %VENV_DIR%."
            exit /b 0
        )
        call :warn "Ранее выбранный venv перестал запускаться, буду чинить: %VENV_DIR%."
        set "BROKEN_VENV_DIR=%VENV_DIR%"
    )
)

set "TARGET_VENV=%PREFERRED_CREATE_VENV%"
if not defined TARGET_VENV set "TARGET_VENV=.venv"
if "%RECREATE_VENV%"=="1" if defined VENV_DIR set "TARGET_VENV=%VENV_DIR%"

if exist "%TARGET_VENV%" (
    call :warn "Папка %TARGET_VENV% будет сохранена в logs\run\backups и создана заново."
    if not exist "%RUN_ROOT%\backups" mkdir "%RUN_ROOT%\backups" >nul 2>nul
    set "VENV_BACKUP=%RUN_ROOT%\backups\%TARGET_VENV%_broken_%RUN_ID%_%RANDOM%"
    move "%TARGET_VENV%" "!VENV_BACKUP!" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (
        call :bad "Не удалось переместить %TARGET_VENV% в backup. Закрой терминалы/процессы, которые используют этот venv, или запусти --unlock после закрытия старого процесса."
        call :save_last_error "Не удалось переместить virtualenv"
        set "FATAL=1"
        exit /b 1
    ) else (
        call :info "Старый %TARGET_VENV% сохранён как !VENV_BACKUP!."
    )
)

call :info "Создаю %TARGET_VENV% через: %BEST_PY_CMD%"
call :run_logged %BEST_PY_CMD% -m venv "%TARGET_VENV%"
if errorlevel 1 (
    call :bad "Не удалось создать %TARGET_VENV%. Подробности в логе."
    call :save_last_error "Ошибка создания virtualenv"
    set "FATAL=1"
    exit /b 1
)
set "VENV_DIR=%TARGET_VENV%"
for %%I in ("%TARGET_VENV%") do set "VENV_PY=%%~fI\Scripts\python.exe"

"%VENV_PY%" -c "import sys; print(sys.version)" >>"%LOG_FILE%" 2>>&1
if errorlevel 1 (
    call :bad "Созданный %TARGET_VENV% есть, но Python внутри не запускается."
    call :save_last_error "Созданный venv не запускается"
    set "FATAL=1"
    exit /b 1
)
call :ok "%TARGET_VENV% создан и проверен."
exit /b 0


:capture_python_version
set "CPV_OUT=%~1"
set "%CPV_OUT%="
if not exist "%VENV_PY%" exit /b 1
if not exist "%RUN_ROOT%\tmp" mkdir "%RUN_ROOT%\tmp" >nul 2>nul
set "CPV_FILE=%RUN_ROOT%\tmp\nf_py_version_%RUN_ID%_%RANDOM%.txt"
"%VENV_PY%" -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'.'+str(sys.version_info.micro))" >"%CPV_FILE%" 2>>"%LOG_FILE%"
if errorlevel 1 (
    del "%CPV_FILE%" >nul 2>nul
    exit /b 1
)
set /p CPV_VALUE=<"%CPV_FILE%"
del "%CPV_FILE%" >nul 2>nul
if defined CPV_VALUE set "%CPV_OUT%=%CPV_VALUE%"
set "CPV_FILE="
set "CPV_VALUE="
exit /b 0

:capture_python_module_version
set "CPMV_MODULE=%~1"
set "CPMV_OUT=%~2"
set "%CPMV_OUT%="
if not exist "%VENV_PY%" exit /b 1
if not exist "%RUN_ROOT%\tmp" mkdir "%RUN_ROOT%\tmp" >nul 2>nul
set "CPMV_FILE=%RUN_ROOT%\tmp\nf_py_module_%RUN_ID%_%RANDOM%.txt"
"%VENV_PY%" -c "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))" "%CPMV_MODULE%" >"%CPMV_FILE%" 2>>"%LOG_FILE%"
if errorlevel 1 (
    del "%CPMV_FILE%" >nul 2>nul
    exit /b 1
)
set /p CPMV_VALUE=<"%CPMV_FILE%"
del "%CPMV_FILE%" >nul 2>nul
if defined CPMV_VALUE set "%CPMV_OUT%=%CPMV_VALUE%"
set "CPMV_FILE="
set "CPMV_VALUE="
set "CPMV_MODULE="
exit /b 0

:install_python_deps
if not exist "%VENV_PY%" (
    call :bad "Python внутри venv не найден: %VENV_PY%"
    set "FATAL=1"
    exit /b 1
)

if not "%FORCE_INSTALL%"=="1" (
    call :python_deps_are_current
    if not errorlevel 1 (
        call :ok "Python-зависимости уже актуальны. Повторная установка не нужна."
        exit /b 0
    )
)

call :info "Обновляю pip/wheel и применяю constraints для стабильной установки..."
if not exist "%RUN_ROOT%\tmp" mkdir "%RUN_ROOT%\tmp" >nul 2>nul
set "NF_PIP_CONSTRAINTS=%RUN_ROOT%\tmp\pip_constraints_setuptools_lt82.txt"
>"%NF_PIP_CONSTRAINTS%" echo setuptools^<82
if exist "requirements-constraints.txt" set "NF_PIP_CONSTRAINTS=requirements-constraints.txt"
call :run_logged "%VENV_PY%" -m pip install --upgrade pip wheel setuptools -c "%NF_PIP_CONSTRAINTS%"
if errorlevel 1 (
    call :bad "Ошибка обновления pip/wheel/setuptools."
    call :save_last_error "Ошибка pip bootstrap"
    set "FATAL=1"
    exit /b 1
)

if exist "requirements.txt" (
    call :info "Ставлю корневые Python-зависимости из requirements.txt..."
    call :run_logged "%VENV_PY%" -m pip install --prefer-binary -r requirements.txt -c "%NF_PIP_CONSTRAINTS%"
    if errorlevel 1 (
        call :bad "Ошибка установки requirements.txt. Подробности в текущем логе и файле последней ошибки: %LOG_FILE% / %ERROR_FILE%."
        call :save_last_error "Ошибка установки requirements.txt"
        set "FATAL=1"
        exit /b 1
    ) else call :ok "requirements.txt установлен/проверен."
)

call :info "parser_alpha\requirements.txt не устанавливается отдельно: parser-зависимости объединены в корневой requirements.txt."

if exist "qwen_service\service.py" (
    call :info "Проверяю импорт qwen_service..."
    "%VENV_PY%" -c "import sys; sys.path.insert(0,'.'); import qwen_service.service; print('qwen_service import ok')" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 call :warn "qwen_service пока не импортируется. Возможно, не хватает зависимости или переменной .env. Смотри лог."
)

call :run_logged "%VENV_PY%" -m pip check
if errorlevel 1 (
    call :warn "После установки pip check всё ещё видит конфликты. Смотри лог: %LOG_FILE%."
) else call :ok "pip check после установки: OK."

call :mark_python_deps_current
exit /b 0

:python_deps_are_current
set "PY_DEPS_ADOPT=0"
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%" >nul 2>nul

call :hash_file "requirements.txt" "ROOT_REQ_HASH"
if errorlevel 1 set "ROOT_REQ_HASH=NO_REQUIREMENTS"
call :hash_file "requirements-constraints.txt" "CONSTRAINTS_HASH"
if errorlevel 1 set "CONSTRAINTS_HASH=NO_CONSTRAINTS"

call :capture_python_version "CURRENT_PY_ID"
if not defined CURRENT_PY_ID exit /b 1

call :read_marker "%STATE_DIR%\python_version.txt" "MARK_PY_ID"
call :read_marker "%STATE_DIR%\requirements.sha256" "MARK_ROOT_REQ_HASH"
call :read_marker "%STATE_DIR%\requirements_constraints.sha256" "MARK_CONSTRAINTS_HASH"

set "NO_PY_MARKERS=0"
if not exist "%STATE_DIR%\python_version.txt" if not exist "%STATE_DIR%\requirements.sha256" if not exist "%STATE_DIR%\requirements_constraints.sha256" set "NO_PY_MARKERS=1"

"%VENV_PY%" -c "import fastapi,uvicorn,sqlalchemy,alembic,pydantic,redis,celery,asyncpg; print('python imports ok')" >>"%LOG_FILE%" 2>>&1
if errorlevel 1 exit /b 1
"%VENV_PY%" -m pip check >>"%LOG_FILE%" 2>>&1
if errorlevel 1 exit /b 1

if "%NO_PY_MARKERS%"=="1" (
    call :info "Маркеров установки Python ещё нет: запущу pip install для полной проверки requirements."
    exit /b 1
)

if not "%MARK_PY_ID%"=="%CURRENT_PY_ID%" exit /b 1
if not "%MARK_ROOT_REQ_HASH%"=="%ROOT_REQ_HASH%" exit /b 1
if not "%MARK_CONSTRAINTS_HASH%"=="%CONSTRAINTS_HASH%" exit /b 1
exit /b 0

:mark_python_deps_current
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%" >nul 2>nul
call :hash_file "requirements.txt" "ROOT_REQ_HASH"
if errorlevel 1 set "ROOT_REQ_HASH=NO_REQUIREMENTS"
call :hash_file "requirements-constraints.txt" "CONSTRAINTS_HASH"
if errorlevel 1 set "CONSTRAINTS_HASH=NO_CONSTRAINTS"
call :capture_python_version "CURRENT_PY_ID"
if not defined CURRENT_PY_ID set "CURRENT_PY_ID=UNKNOWN"
>"%STATE_DIR%\python_version.txt" echo %CURRENT_PY_ID%
>"%STATE_DIR%\requirements.sha256" echo %ROOT_REQ_HASH%
>"%STATE_DIR%\requirements_constraints.sha256" echo %CONSTRAINTS_HASH%
exit /b 0

:install_playwright_browsers
if not exist "%VENV_PY%" exit /b 0
"%VENV_PY%" -c "import playwright" >nul 2>nul
if errorlevel 1 exit /b 0

call :capture_python_module_version "playwright" "CURRENT_PLAYWRIGHT_VER"
call :read_marker "%STATE_DIR%\playwright_chromium_version.txt" "MARK_PLAYWRIGHT_VER"
if not "%FORCE_INSTALL%"=="1" if defined CURRENT_PLAYWRIGHT_VER if "%MARK_PLAYWRIGHT_VER%"=="%CURRENT_PLAYWRIGHT_VER%" (
    call :ok "Playwright chromium уже был установлен для playwright %CURRENT_PLAYWRIGHT_VER%. Повторная проверка пропущена."
    exit /b 0
)

call :info "Проверяю/устанавливаю браузеры Playwright..."
call :run_logged "%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
    call :warn "Playwright browsers не установились. Это не всегда критично, но парсер через Playwright может не работать."
    call :save_last_error "Ошибка playwright install chromium"
) else (
    if not exist "%STATE_DIR%" mkdir "%STATE_DIR%" >nul 2>nul
    >"%STATE_DIR%\playwright_chromium_version.txt" echo %CURRENT_PLAYWRIGHT_VER%
    call :ok "Playwright chromium установлен/проверен."
)
exit /b 0

:install_frontend_deps
if not exist "frontend\package.json" exit /b 0

if not "%FORCE_INSTALL%"=="1" (
    call :frontend_deps_are_current
    if not errorlevel 1 (
        call :ok "Frontend зависимости уже актуальны. npm ci/npm install не нужен."
        exit /b 0
    )
)

call :info "Устанавливаю frontend зависимости..."
pushd frontend >nul
if exist "package-lock.json" (
    call :run_logged npm ci
    if errorlevel 1 (
        call :warn "npm ci не прошёл. Пробую npm install..."
        call :run_logged npm install
        if errorlevel 1 (
            popd >nul
            call :bad "Ошибка установки frontend зависимостей."
            call :save_last_error "Ошибка npm install"
            set "FATAL=1"
            exit /b 1
        )
    )
) else (
    call :run_logged npm install
    if errorlevel 1 (
        popd >nul
        call :bad "Ошибка npm install."
        call :save_last_error "Ошибка npm install"
        set "FATAL=1"
        exit /b 1
    )
)

if "%RUN_FRONTEND_BUILD%"=="1" (
    call :info "Запускаю npm run build по флагу --frontend-build/--full-check..."
    call :run_logged npm run build
    if errorlevel 1 (
        popd >nul
        call :warn "npm run build завершился с ошибкой. Смотри лог: %LOG_FILE%."
        call :save_last_error "Ошибка npm run build"
        exit /b 0
    ) else call :ok "Frontend build: OK."
)
popd >nul
call :mark_frontend_deps_current
if not "%RUN_FRONTEND_BUILD%"=="1" call :info "Frontend build не запускался. Для полной проверки используй --frontend-build или --full-check."
call :ok "Frontend зависимости установлены/проверены."
exit /b 0

:frontend_deps_are_current
if not exist "frontend\node_modules" exit /b 1
call :hash_file "frontend\package.json" "FRONT_PKG_HASH"
if errorlevel 1 exit /b 1
call :hash_file "frontend\package-lock.json" "FRONT_LOCK_HASH"
if errorlevel 1 set "FRONT_LOCK_HASH=NO_PACKAGE_LOCK"
call :read_marker "%STATE_DIR%\frontend_package.sha256" "MARK_FRONT_PKG_HASH"
call :read_marker "%STATE_DIR%\frontend_lock.sha256" "MARK_FRONT_LOCK_HASH"

call :write_frontend_deps_check_js "%TEMP%\nf_frontend_deps_check_%RANDOM%_%RANDOM%.js" "FRONT_CHECK_JS"
pushd frontend >nul
node "%FRONT_CHECK_JS%" >>"%LOG_FILE%" 2>>&1
set "FRONT_NODE_RC=%ERRORLEVEL%"
popd >nul
del "%FRONT_CHECK_JS%" >nul 2>nul
if not "%FRONT_NODE_RC%"=="0" exit /b 1

if not exist "%STATE_DIR%\frontend_package.sha256" if not exist "%STATE_DIR%\frontend_lock.sha256" (
    call :info "Маркеров frontend ещё нет: запущу npm ci/npm install для полной проверки package-lock/package.json."
    exit /b 1
)

if not "%MARK_FRONT_PKG_HASH%"=="%FRONT_PKG_HASH%" exit /b 1
if not "%MARK_FRONT_LOCK_HASH%"=="%FRONT_LOCK_HASH%" exit /b 1
exit /b 0

:write_frontend_deps_check_js
set "OUT_JS=%~1"
set "%~2=%OUT_JS%"
>"%OUT_JS%" echo const fs = require('fs');
>>"%OUT_JS%" echo const path = require('path');
>>"%OUT_JS%" echo const p = require(path.join(process.cwd(), 'package.json'));
>>"%OUT_JS%" echo const deps = Object.assign({}, p.dependencies ^|^| {}, p.devDependencies ^|^| {});
>>"%OUT_JS%" echo const miss = Object.keys(deps).filter((n) =^> !fs.existsSync(path.join(process.cwd(), 'node_modules', ...n.split('/'), 'package.json')));
>>"%OUT_JS%" echo if (miss.length) { console.error('missing frontend deps: ' + miss.join(', ')); process.exit(1); }
>>"%OUT_JS%" echo console.log('frontend direct deps ok: ' + Object.keys(deps).length);
exit /b 0

:mark_frontend_deps_current
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%" >nul 2>nul
call :hash_file "frontend\package.json" "FRONT_PKG_HASH"
if errorlevel 1 set "FRONT_PKG_HASH=NO_PACKAGE_JSON"
call :hash_file "frontend\package-lock.json" "FRONT_LOCK_HASH"
if errorlevel 1 set "FRONT_LOCK_HASH=NO_PACKAGE_LOCK"
>"%STATE_DIR%\frontend_package.sha256" echo %FRONT_PKG_HASH%
>"%STATE_DIR%\frontend_lock.sha256" echo %FRONT_LOCK_HASH%
exit /b 0

:ensure_redis_launcher
if exist "run_redis.bat" (
    call :ok "run_redis.bat найден."
) else (
    call :warn "run_redis.bat не найден. Создаю wrapper на scripts\run_redis.bat."
    >"run_redis.bat" echo @echo off
    >>"run_redis.bat" echo setlocal EnableExtensions
    >>"run_redis.bat" echo cd /d %%~dp0
    >>"run_redis.bat" echo if exist "scripts\run_redis.bat" ^(
    >>"run_redis.bat" echo   call "scripts\run_redis.bat" %%*
    >>"run_redis.bat" echo   exit /b %%ERRORLEVEL%%
    >>"run_redis.bat" echo ^)
    >>"run_redis.bat" echo echo [ERROR] scripts\run_redis.bat was not found.
    >>"run_redis.bat" echo exit /b 1
)
if exist "scripts\run_redis.bat" (call :ok "scripts\run_redis.bat найден.") else call :warn "scripts\run_redis.bat не найден. Redis нужно будет запускать вручную."
if exist "scripts\download_redis.ps1" (call :ok "Redis download helper найден.") else call :warn "scripts\download_redis.ps1 не найден. Автоскачивание Redis будет недоступно."
exit /b 0

:start_redis_if_possible
call :check_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis"
if not errorlevel 1 exit /b 0
if exist "scripts\run_redis.bat" (
    call :info "Пробую запустить Redis через scripts\run_redis.bat на порту из .env..."
    start "Nickelfront Redis" /min cmd /c "cd /d ""%PROJECT_ROOT%"" && call scripts\run_redis.bat"
    timeout /t 4 >nul
    call :check_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis"
    if errorlevel 1 (call :warn "Redis не запустился автоматически. Проверь scripts\run_redis.bat и порт %REDIS_PORT%.") else call :ok "Redis запущен/отвечает."
    exit /b 0
)
if exist "run_redis.bat" (
    call :info "Пробую запустить Redis через run_redis.bat..."
    start "Nickelfront Redis" /min cmd /c "cd /d ""%PROJECT_ROOT%"" && call run_redis.bat"
    timeout /t 4 >nul
    call :check_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis"
    if errorlevel 1 (call :warn "Redis не запустился автоматически. Запусти run_redis.bat вручную.") else call :ok "Redis запущен."
) else (
    call :warn "Redis launcher не найден. Автозапуск Redis невозможен."
)
exit /b 0

:prepare_database
call :check_tcp "%POSTGRES_HOST%" "%POSTGRES_PORT%" "PostgreSQL"
if errorlevel 1 (
    call :warn "PostgreSQL недоступен. Создание БД и миграции будут пропущены."
    exit /b 0
)
if not exist "%VENV_PY%" exit /b 0

call :info "Проверяю/создаю БД %POSTGRES_DB% через Python/psycopg2..."
if not exist "%RUN_ROOT%\tmp" mkdir "%RUN_ROOT%\tmp" >nul 2>nul
set "NF_PREPARE_DB_PY=%RUN_ROOT%\tmp\nf_prepare_db_%RUN_ID%_%RANDOM%.py"
call :write_prepare_db_py "%NF_PREPARE_DB_PY%"
"%VENV_PY%" "%NF_PREPARE_DB_PY%" >>"%LOG_FILE%" 2>>&1
del "%NF_PREPARE_DB_PY%" >nul 2>nul
if errorlevel 1 (
    call :warn "Не удалось проверить/создать БД автоматически. Проверь DATABASE_URL и права пользователя PostgreSQL."
    call :save_last_error "Ошибка prepare_database"
) else call :ok "БД %POSTGRES_DB% существует или создана."
exit /b 0

:write_prepare_db_py
set "OUT_PY=%~1"
>"%OUT_PY%" echo import os, sys
>>"%OUT_PY%" echo from urllib.parse import urlsplit, unquote
>>"%OUT_PY%" echo try:
>>"%OUT_PY%" echo ^    import psycopg2
>>"%OUT_PY%" echo ^    from psycopg2 import sql
>>"%OUT_PY%" echo except Exception as e:
>>"%OUT_PY%" echo ^    print("psycopg2 import failed:", e)
>>"%OUT_PY%" echo ^    sys.exit(3)
>>"%OUT_PY%" echo url = os.environ.get("DATABASE_URL", "")
>>"%OUT_PY%" echo if "://" in url and url.startswith("postgresql+"):
>>"%OUT_PY%" echo ^    url = "postgresql://" + url.split("://", 1)[1]
>>"%OUT_PY%" echo u = urlsplit(url)
>>"%OUT_PY%" echo host = u.hostname or os.environ.get("POSTGRES_HOST", "127.0.0.1")
>>"%OUT_PY%" echo port = u.port or int(os.environ.get("POSTGRES_PORT", "5432"))
>>"%OUT_PY%" echo user = unquote(u.username or os.environ.get("POSTGRES_USER", "postgres"))
>>"%OUT_PY%" echo password = unquote(u.password or os.environ.get("POSTGRES_PASSWORD", ""))
>>"%OUT_PY%" echo target_db = unquote((u.path or "/").strip("/") or os.environ.get("POSTGRES_DB", "nickelfront"))
>>"%OUT_PY%" echo admin_db = os.environ.get("POSTGRES_ADMIN_DB", "postgres")
>>"%OUT_PY%" echo conn = psycopg2.connect(dbname=admin_db, user=user, password=password, host=host, port=port)
>>"%OUT_PY%" echo conn.autocommit = True
>>"%OUT_PY%" echo try:
>>"%OUT_PY%" echo ^    with conn.cursor() as cur:
>>"%OUT_PY%" echo ^        cur.execute("SELECT 1 FROM pg_database WHERE datname=%%s", (target_db,))
>>"%OUT_PY%" echo ^        exists = cur.fetchone() is not None
>>"%OUT_PY%" echo ^        if not exists:
>>"%OUT_PY%" echo ^            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
>>"%OUT_PY%" echo ^            print("created", target_db)
>>"%OUT_PY%" echo ^        else:
>>"%OUT_PY%" echo ^            print("exists", target_db)
>>"%OUT_PY%" echo finally:
>>"%OUT_PY%" echo ^    conn.close()
exit /b 0

:run_migrations
if not exist "%VENV_PY%" exit /b 0
call :check_tcp "%POSTGRES_HOST%" "%POSTGRES_PORT%" "PostgreSQL"
if errorlevel 1 (
    call :warn "Миграции пропущены: PostgreSQL недоступен на %POSTGRES_HOST%:%POSTGRES_PORT%."
    if "%START_APP%"=="1" (
        call :bad "PostgreSQL нужен для автозапуска backend. Запусти PostgreSQL или используй --no-start-app."
        set "FATAL=1"
        exit /b 1
    )
    exit /b 0
)

if exist "backend\apply_migrations.py" (
    call :info "Запускаю backend\apply_migrations.py..."
    "%VENV_PY%" backend\apply_migrations.py >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (
        call :warn "backend\apply_migrations.py завершился с ошибкой. Пробую fallback Alembic. Смотри лог: %LOG_FILE%."
        call :save_last_error "Ошибка backend/apply_migrations.py"
    ) else (
        call :ok "Миграции выполнены через backend\apply_migrations.py."
        exit /b 0
    )
)

if exist "backend\alembic.ini" (
    call :info "Пробую fallback: alembic -c alembic.ini upgrade head из папки backend..."
    pushd backend >nul
    "%VENV_PY%" -m alembic -c alembic.ini upgrade head >>"%LOG_FILE%" 2>>&1
    set "ALEMBIC_FALLBACK_RC=%ERRORLEVEL%"
    popd >nul
    if not "%ALEMBIC_FALLBACK_RC%"=="0" (
        call :bad "Fallback Alembic завершился с ошибкой. Backend запускать нельзя, смотри лог."
        call :save_last_error "Ошибка alembic fallback"
        set "FATAL=1"
        exit /b 1
    )
    call :ok "Fallback Alembic upgrade head выполнен."

    if exist "backend\apply_migrations.py" (
        call :info "Контрольная проверка backend\apply_migrations.py после fallback..."
        "%VENV_PY%" backend\apply_migrations.py >>"%LOG_FILE%" 2>>&1
        if errorlevel 1 (
            call :bad "После fallback backend\apply_migrations.py всё ещё падает. Backend запускать нельзя."
            call :save_last_error "backend/apply_migrations.py падает после fallback"
            set "FATAL=1"
            exit /b 1
        )
        call :ok "Контрольная проверка миграций через backend\apply_migrations.py: OK."
    )
) else (
    call :bad "backend\alembic.ini не найден. Миграции выполнить невозможно."
    set "FATAL=1"
    exit /b 1
)
exit /b 0

:final_healthcheck
call :section "Финальная проверка"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.path[:0]=['backend','.']; import fastapi,uvicorn,sqlalchemy,alembic,pydantic,redis,celery,asyncpg; from app.core.config import settings; print('backend imports ok', settings.API_PORT)" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (call :warn "Backend import check не прошёл. Смотри лог.") else call :ok "Backend import check: OK."
)
if exist "qwen_service\service.py" if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.path.insert(0,'.'); import qwen_service.service; print('qwen service import ok')" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (call :warn "Qwen service import check не прошёл. Смотри лог.") else call :ok "Qwen service import check: OK."
)
if exist "frontend\package.json" (
    pushd frontend >nul
    node -e "require('./package.json'); console.log('frontend package.json ok')" >>"%LOG_FILE%" 2>>&1
    if errorlevel 1 (call :warn "Frontend package.json check не прошёл. Смотри лог.") else call :ok "Frontend package.json check: OK. npm ls пропущен."
    popd >nul
)
call :info "Локальные import/package проверки завершены. Далее будет автозапуск и проверка портов, если не указан --no-start-app."
exit /b 0


:start_project_services
if not "%START_APP%"=="1" (
    call :info "Автозапуск сервисов отключён флагом --no-start-app."
    exit /b 0
)
call :section "Автозапуск сервисов проекта"
if exist "run_all.bat" (
    call :info "Запускаю run_all.bat в отдельном окне. Миграции уже выполнены установщиком."
    start "Nickelfront run_all" cmd /k "cd /d ""%PROJECT_ROOT%"" && set SKIP_BACKEND_MIGRATIONS=1&& call run_all.bat"
) else (
    call :warn "run_all.bat не найден. Пробую запускать основные сервисы по отдельности."
    if exist "run_redis.bat" start "Nickelfront Redis" cmd /k "cd /d ""%PROJECT_ROOT%"" && call run_redis.bat"
    if exist "run_qwen_service.bat" start "Nickelfront Qwen Service" cmd /k "cd /d ""%PROJECT_ROOT%"" && call run_qwen_service.bat"
    if exist "run_backend.bat" start "Nickelfront Backend" cmd /k "cd /d ""%PROJECT_ROOT%"" && set SKIP_BACKEND_MIGRATIONS=1&& call run_backend.bat"
    if exist "run_frontend.bat" start "Nickelfront Frontend" cmd /k "cd /d ""%PROJECT_ROOT%"" && call run_frontend.bat"
)
call :info "Жду старта сервисов и проверяю порты из .env. run_all дополнительно ждёт backend /health перед worker-процессами."

call :wait_tcp "%REDIS_HOST%" "%REDIS_PORT%" "Redis" "%REDIS_WAIT_SECONDS%"
if errorlevel 1 (call :warn "Redis не отвечает на %REDIS_HOST%:%REDIS_PORT% после ожидания %REDIS_WAIT_SECONDS%s. Смотри окно Redis/run_all.") else call :ok "Redis отвечает после автозапуска."

call :wait_tcp "127.0.0.1" "%API_PORT%" "Backend API" "%BACKEND_WAIT_SECONDS%"
if errorlevel 1 (call :warn "Backend API не отвечает на 127.0.0.1:%API_PORT% после ожидания %BACKEND_WAIT_SECONDS%s. Проверь окно Backend/run_all и лог backend.") else call :ok "Backend API отвечает на 127.0.0.1:%API_PORT%."

call :wait_tcp "%QWEN_SERVICE_HOST%" "%QWEN_SERVICE_PORT%" "Qwen service" "%QWEN_WAIT_SECONDS%"
if errorlevel 1 (call :warn "Qwen service не отвечает на %QWEN_SERVICE_HOST%:%QWEN_SERVICE_PORT% после ожидания %QWEN_WAIT_SECONDS%s. Смотри окно Qwen/run_all.") else call :ok "Qwen service отвечает."

call :wait_tcp "127.0.0.1" "%FRONTEND_PORT%" "Frontend" "%FRONTEND_WAIT_SECONDS%"
if errorlevel 1 (call :warn "Frontend не отвечает на 127.0.0.1:%FRONTEND_PORT% после ожидания %FRONTEND_WAIT_SECONDS%s. Vite может стартовать дольше — смотри окно Frontend/run_all.") else call :ok "Frontend отвечает."

call :check_tcp "127.0.0.1" "%FLOWER_PORT%" "Flower"
if errorlevel 1 (call :info "Flower не отвечает на 127.0.0.1:%FLOWER_PORT%. Это нормально, если run_all не запускает Flower.") else call :ok "Flower отвечает."
exit /b 0

:wait_tcp
set "WT_HOST=%~1"
set "WT_PORT=%~2"
set "WT_NAME=%~3"
set "WT_SECONDS=%~4"
if not defined WT_SECONDS set "WT_SECONDS=120"
set /a "WT_LEFT=WT_SECONDS" >nul 2>nul
if not defined WT_LEFT set "WT_LEFT=120"
:wait_tcp_loop
call :check_tcp "%WT_HOST%" "%WT_PORT%" "%WT_NAME%"
if not errorlevel 1 exit /b 0
if %WT_LEFT% LEQ 0 exit /b 1
set "WT_SLEEP=5"
if %WT_LEFT% LSS 5 set "WT_SLEEP=%WT_LEFT%"
timeout /t %WT_SLEEP% /nobreak >nul
set /a "WT_LEFT-=WT_SLEEP" >nul 2>nul
goto wait_tcp_loop

:hash_file
set "HF_FILE=%~1"
set "HF_OUT=%~2"
set "!HF_OUT!="
if not exist "%HF_FILE%" exit /b 1
for %%I in ("%HF_FILE%") do set "HF_ABS=%%~fI"
set "NF_HASH_FILE=%HF_ABS%"
for /f "delims=" %%H in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:NF_HASH_FILE; if(Test-Path -LiteralPath $p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash}" 2^>nul') do set "!HF_OUT!=%%H"
if defined !HF_OUT! exit /b 0
for /f "tokens=1" %%H in ('certutil -hashfile "%HF_FILE%" SHA256 2^>nul ^| findstr /R /I "^[0-9A-F][0-9A-F]"') do if not defined !HF_OUT! set "!HF_OUT!=%%H"
if defined !HF_OUT! exit /b 0
exit /b 1

:read_marker
set "RM_FILE=%~1"
set "RM_OUT=%~2"
set "!RM_OUT!="
if exist "%RM_FILE%" set /p "!RM_OUT!="<"%RM_FILE%"
exit /b 0

:save_last_error
set "ERR_TITLE=%~1"
>"%ERROR_FILE%" echo %ERR_TITLE%
>>"%ERROR_FILE%" echo Время: %DATE% %TIME%
>>"%ERROR_FILE%" echo Проект: %PROJECT_ROOT%
>>"%ERROR_FILE%" echo.
>>"%ERROR_FILE%" echo Последние строки текущего лога:
where powershell >nul 2>nul && powershell -NoProfile -ExecutionPolicy Bypass -Command "if(Test-Path '%LOG_FILE%'){Get-Content -LiteralPath '%LOG_FILE%' -Tail 160}" >>"%ERROR_FILE%" 2>nul
exit /b 0

:release_lock
if defined LOG_FILE if defined LATEST_LOG_FILE if exist "%LOG_FILE%" copy /Y "%LOG_FILE%" "%LATEST_LOG_FILE%" >nul 2>nul
if defined ERROR_FILE if defined LATEST_ERROR_FILE if exist "%ERROR_FILE%" copy /Y "%ERROR_FILE%" "%LATEST_ERROR_FILE%" >nul 2>nul
if defined RUN_LOCK_DIR if exist "%RUN_LOCK_DIR%" rd /s /q "%RUN_LOCK_DIR%" >nul 2>nul
exit /b 0

:finish_ok
call :release_lock
echo.
echo ==============================================================================
echo ГОТОВО. Версия скрипта: %SCRIPT_VERSION%
echo Лог: "%LOG_FILE%"
echo Последняя копия лога: "%LATEST_LOG_FILE%"
echo Если была ошибка, смотри: "%ERROR_FILE%"
echo Служебные файлы doctor/setup: "%RUN_ROOT%"
echo Окно НЕ закроется, можно скопировать текст.
echo ==============================================================================
echo.
pause
exit /b 0

:finish_error
call :release_lock
echo.
echo ==============================================================================
echo УСТАНОВКА ЗАВЕРШИЛАСЬ С ОШИБКАМИ.
echo Версия скрипта: %SCRIPT_VERSION%
echo Лог: "%LOG_FILE%"
echo Последняя ошибка: "%ERROR_FILE%"
echo Служебные файлы doctor/setup: "%RUN_ROOT%"
echo Окно НЕ закроется, можно скопировать ошибку.
echo ==============================================================================
echo.
pause
exit /b 1
