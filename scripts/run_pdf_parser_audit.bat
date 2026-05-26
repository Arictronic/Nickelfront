@echo off
setlocal EnableExtensions

rem Run Nickelfront batch PDF parser audit from project root or scripts folder.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    echo Python venv not found. Expected .venv\Scripts\python.exe or venv\Scripts\python.exe
    exit /b 1
)

echo Using %PY%
"%PY%" -c "from pathlib import Path; import ast; p=Path('backend/scripts/pdf_parser_batch_audit.py'); mod=ast.parse(p.read_text(encoding='utf-8')); version=next((str(node.value.value) for node in mod.body if isinstance(node, ast.Assign) for target in node.targets if getattr(target, 'id', '') == 'AUDIT_VERSION' and isinstance(node.value, ast.Constant)), 'VERSION_NOT_FOUND'); print('Audit script:', p.resolve()); print('Audit version:', version)"
"%PY%" backend\scripts\pdf_parser_batch_audit.py %*
