@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

if exist "%PROJECT_ROOT%\scripts\load_env.bat" (
  call "%PROJECT_ROOT%\scripts\load_env.bat" "%PROJECT_ROOT%\.env"
)

set "PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "AUDIT=%PROJECT_ROOT%\backend\scripts\pdf_parser_batch_audit.py"
set "VERIFY=%PROJECT_ROOT%\backend\scripts\verify_pdf_parser_patch.py"
set "PDF_DIR=%PROJECT_ROOT%\storage\papers_pdf"
set "OUT_DIR=%PROJECT_ROOT%\storage\pdf_parser_audit"

echo 1 - Run verify
echo 2 - Run audit without OCR
echo 3 - Run audit with OCR
echo 4 - Show commands
echo 0 - Exit
echo.

set /p ACTION=Choose action: 

if "%ACTION%"=="1" "%PY%" "%VERIFY%"
if "%ACTION%"=="2" "%PY%" "%AUDIT%" --pdf-dir "%PDF_DIR%" --out-base "%OUT_DIR%" --no-ocr --audit-domain-mode generic --sample-blocks 5 --sample-chars 500 --per-pdf-timeout-sec 180
if "%ACTION%"=="3" "%PY%" "%AUDIT%" --pdf-dir "%PDF_DIR%" --out-base "%OUT_DIR%_ocr" --audit-domain-mode generic --sample-blocks 5 --sample-chars 500 --per-pdf-timeout-sec 240
if "%ACTION%"=="4" (
  echo "%PY%" "%VERIFY%"
  echo "%PY%" "%AUDIT%" --pdf-dir "%PDF_DIR%" --out-base "%OUT_DIR%" --no-ocr --audit-domain-mode generic --sample-blocks 5 --sample-chars 500 --per-pdf-timeout-sec 180
)

pause