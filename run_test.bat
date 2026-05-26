@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) else if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo Виртуальное окружение Python не найдено.
  echo Ожидается .venv\Scripts\activate.bat или venv\Scripts\activate.bat
  pause
  exit /b 1
)

if exist "%~dp0scripts\load_env.bat" (
  call "%~dp0scripts\load_env.bat" "%~dp0.env"
  if errorlevel 1 (
    echo Не удалось загрузить переменные из .env
    pause
    exit /b 1
  )
)

:menu
cls
echo ==========================================
echo           Запуск тестов Nickelfront
echo ==========================================
echo.
echo Выберите, какие тесты запустить:
echo   1. Все тесты
echo   2. Только backend
echo   3. Только parser
echo   4. Только RAG
echo   0. Выход
echo.
set "TEST_TARGET="
set /p TEST_TARGET=Введите цифру и нажмите Enter: 

if "%TEST_TARGET%"=="1" goto run_all
if "%TEST_TARGET%"=="2" goto run_backend
if "%TEST_TARGET%"=="3" goto run_parser
if "%TEST_TARGET%"=="4" goto run_rag
if "%TEST_TARGET%"=="0" goto finish

echo.
echo Некорректный выбор: "%TEST_TARGET%"
echo Доступные варианты: 0, 1, 2, 3, 4
pause
goto menu

:run_all
set "PYTEST_TARGET=tests"
set "TITLE_TEXT=все тесты"
goto run_tests

:run_backend
set "PYTEST_TARGET=tests\backend"
set "TITLE_TEXT=backend-тесты"
goto run_tests

:run_parser
set "PYTEST_TARGET=tests\parser"
set "TITLE_TEXT=parser-тесты"
goto run_tests

:run_rag
set "PYTEST_TARGET=tests\rag"
set "TITLE_TEXT=RAG-тесты"
goto run_tests

:run_tests
echo.
echo Запускаются %TITLE_TEXT%...
echo Команда: python -m pytest %PYTEST_TARGET%
echo.
python -m pytest %PYTEST_TARGET%
set "TEST_RC=%ERRORLEVEL%"
echo.
if "%TEST_RC%"=="0" (
  echo Тесты завершились успешно.
) else (
  echo Тесты завершились с ошибкой. Код возврата: %TEST_RC%
)
pause
exit /b %TEST_RC%

:finish
exit /b 0
