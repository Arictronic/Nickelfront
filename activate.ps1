# Скрипт активации виртуального окружения для Windows PowerShell
# Использование: .\activate.ps1

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $scriptDir "venv"

if (Test-Path $venvDir) {
    & "$venvDir\Scripts\Activate.ps1"
    Write-Host "✓ Виртуальное окружение активировано" -ForegroundColor Green
} else {
    Write-Host "✗ Виртуальное окружение не найдено. Создайте:" -ForegroundColor Red
    Write-Host "  python -m venv venv" -ForegroundColor Yellow
}
