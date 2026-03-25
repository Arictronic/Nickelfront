# Скрипт установки зависимостей для Windows PowerShell
# Использование: .\setup.ps1

Write-Host "=== Nickelfront Setup ===" -ForegroundColor Cyan
Write-Host ""

# Проверка Python
Write-Host "Проверка Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "✗ Python не найден. Установите Python 3.12+" -ForegroundColor Red
    exit 1
}

# Проверка Node.js
Write-Host "Проверка Node.js..." -ForegroundColor Yellow
$nodeVersion = node --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Node.js $nodeVersion" -ForegroundColor Green
} else {
    Write-Host "✗ Node.js не найден. Установите Node.js 18+" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Создание виртуального окружения
Write-Host "Создание виртуального окружения..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "✓ venv уже существует" -ForegroundColor Green
} else {
    python -m venv venv
    Write-Host "✓ venv создано" -ForegroundColor Green
}

Write-Host ""

# Активация venv
Write-Host "Активация виртуального окружения..." -ForegroundColor Yellow
.\venv\Scripts\Activate.ps1

# Установка зависимостей backend
Write-Host "Установка зависимостей backend..." -ForegroundColor Yellow
cd backend
pip install --upgrade pip
pip install -r requirements.txt
cd ..

Write-Host ""

# Установка зависимостей frontend
Write-Host "Установка зависимостей frontend..." -ForegroundColor Yellow
cd frontend
npm install
cd ..

Write-Host ""
Write-Host "=== Установка завершена ===" -ForegroundColor Green
Write-Host ""
Write-Host "Далее:" -ForegroundColor Cyan
Write-Host "1. Настройте файл .env (скопируйте .env.example)"
Write-Host "2. Запустите PostgreSQL и Redis"
Write-Host "3. Активируйте venv: .\venv\Scripts\Activate.ps1"
Write-Host "4. Backend: cd backend && uvicorn app.main:app --reload"
Write-Host "5. Frontend: cd frontend && npm run dev"
