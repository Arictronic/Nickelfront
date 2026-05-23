@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "MSG_HEADER=PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09Ck5pY2tlbGZyb250OiDQvtGH0LjRgdGC0LrQsCBydW50aW1lLdC00LDQvdC90YvRhQo9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT0KCtCt0YLQvtGCINGB0LHRgNC+0YEg0YPQtNCw0LvRj9C10YIgcnVudGltZS3QtNCw0L3QvdGL0LU6Ci0g0YHRgtCw0YLRjNC4LCDQuNGB0YLQvtGA0LjRjiDQt9Cw0LTQsNGHLCDRgdGC0LDRgtC40YHRgtC40LrRgyDQv9Cw0YDRgdC10YDQvtCyCi0gUkFHL0Nocm9tYSDQtNCw0L3QvdGL0LUsIFBERiDQuCDRgNC10LfRg9C70YzRgtCw0YLRiyDQsNC90LDQu9C40LfQsAotINC70L7Qs9C4INC4INC+0YfQtdGA0LXQtNC4IFJlZGlzL0NlbGVyeQoK0J/QvtC70YzQt9C+0LLQsNGC0LXQu9C4INC4IHJlZnJlc2gt0YLQvtC60LXQvdGLINC/0L4g0YPQvNC+0LvRh9Cw0L3QuNGOINGB0L7RhdGA0LDQvdGP0Y7RgtGB0Y8sCtGH0YLQvtCx0Ysg0YLQtdC60YPRidCw0Y8g0LvQvtC60LDQu9GM0L3QsNGPINGB0LXRgdGB0LjRjyDQvdC1INGB0LvQvtC80LDQu9Cw0YHRjC4KCtCf0LXRgNC10LQg0LfQsNC/0YPRgdC60L7QvCDQvtGH0LjRgdGC0LrQuCDQt9Cw0LrRgNC+0LnRgtC1OgotIGJhY2tlbmQKLSDQvtCx0YvRh9C90YvQtSB3b3JrZXJzCi0gcXdlbiB3b3JrZXJzCi0gcXdlbl9zZXJ2aWNlCgpQb3N0Z3JlU1FMINC4IFJlZGlzINC80L7QttC90L4g0L7RgdGC0LDQstC40YLRjCDQt9Cw0L/Rg9GJ0LXQvdC90YvQvNC4LgoK"
set "MSG_VENV=0JLQuNGA0YLRg9Cw0LvRjNC90L7QtSDQvtC60YDRg9C20LXQvdC40LUgUHl0aG9uINC90LUg0L3QsNC50LTQtdC90L4uCtCh0L7Qt9C00LDQudGC0LUg0LXQs9C+INC40Lcg0LrQvtGA0L3RjyDQv9GA0L7QtdC60YLQsDoKICBweXRob24gLW0gdmVudiAudmVudgogIC52ZW52XFNjcmlwdHNcYWN0aXZhdGUKICBwaXAgaW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0Cgo="
set "MSG_ERROR=0J7Rh9C40YHRgtC60LAg0LfQsNCy0LXRgNGI0LjQu9Cw0YHRjCDRgSDQvtGI0LjQsdC60L7QuS4g0JrQvtC0INCy0YvRhdC+0LTQsDogezB9LgoK"
set "MSG_SUCCESS=0J7Rh9C40YHRgtC60LAg0YPRgdC/0LXRiNC90L4g0LfQsNCy0LXRgNGI0LXQvdCwLgoK0KfRgtC+INGB0LTQtdC70LDRgtGMINC00LDQu9GM0YjQtToKMS4g0JfQsNC/0YPRgdGC0LjRgtC1IGJhY2tlbmQvcXdlbi93b3JrZXIg0YHQtdGA0LLQuNGB0Ysg0LfQsNC90L7QstC+LgoyLiDQldGB0LvQuCDRgdGC0LDRgNCw0Y8g0LjRgdGC0L7RgNC40Y8g0LLRgdC1INC10YnQtSDQstC40LTQvdCwINCy0L4gZnJvbnRlbmQsCiAgINGB0LTQtdC70LDQudGC0LUgaGFyZCByZWZyZXNoINC40LvQuCDQvtGH0LjRgdGC0LjRgtC1IGxvY2FsU3RvcmFnZSDQsdGA0LDRg9C30LXRgNCwLgoK"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::Write([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%MSG_HEADER%')))"

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::Write([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%MSG_VENV%')))"
  pause
  exit /b 1
)

python "backend\reset_runtime_data.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::Write(([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%MSG_ERROR%')) -f '%EXIT_CODE%'))"
  pause
  exit /b %EXIT_CODE%
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); [Console]::Write([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%MSG_SUCCESS%')))"

pause
endlocal
