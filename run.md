# Запуск проекта (Windows)

## 1. Что должно быть установлено

- Python 3.13 (`C:\SERVAK\python313\python.exe`)
- Node.js LTS + npm
- PostgreSQL 16 (локально)
- Redis (запускается через `run_redis.bat`)

## 2. Подготовка (первый запуск)

Откройте PowerShell в корне проекта `c:\SERVAK\Nickelfront`:

```powershell
# 1) Создать venv
C:\SERVAK\python313\python.exe -m venv venv

# 2) Активировать venv
.\venv\Scripts\Activate.ps1

# 3) Поставить Python-зависимости
pip install -r requirements.txt

# 4) Поставить frontend-зависимости
cd frontend
npm install
cd ..
```

## 3. Настройка `.env` (важно)

Проверьте ключевые переменные:

- `DATABASE_URL=postgresql+asyncpg://postgres:A_vova22@localhost:5432/nickelfront`
- `REDIS_URL=redis://localhost:6380/0`
- `CELERY_BROKER_URL=redis://localhost:6380/0`
- `CELERY_RESULT_BACKEND=redis://localhost:6380/1`
- `VITE_API_URL=http://localhost:8001`

Примечание: PostgreSQL в этой установке работает на `5432` (не `5433`).

## 4. Подготовка базы данных PostgreSQL

Если база `nickelfront` ещё не создана:

```powershell
$env:PGPASSWORD='A_vova22'
& "C:\Program Files\PostgreSQL\16\bin\createdb.exe" -h 127.0.0.1 -p 5432 -U postgres nickelfront
```

Примените миграции:

```powershell
cd backend
..\venv\Scripts\python.exe apply_migrations.py
cd ..
```

## 5. Запуск проекта

### Вариант A: всё сразу

```powershell
.\run_all.bat
```

### Вариант B: по отдельности (в разных окнах)

```powershell
.\run_redis.bat
.\run_backend.bat
.\run_worker.bat
.\run_flower.bat
.\run_frontend.bat
```

## 6. Проверка после запуска

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8001`
- Swagger: `http://localhost:8001/docs`
- Flower: `http://localhost:5555`

## 7. Частые проблемы

- `npm` не найден: установите Node.js LTS и откройте новый терминал.
- `500` на `/api/v1/papers*` с ошибкой подключения к БД:
  - проверьте `DATABASE_URL` (порт `5432`);
  - проверьте пароль пользователя `postgres`;
  - убедитесь, что база `nickelfront` создана;
  - примените миграции из `backend/apply_migrations.py`.
- Ошибка Redis: запустите `run_redis.bat` и не закрывайте окно Redis.
