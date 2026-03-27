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
- `VITE_API_URL=/api/v1`

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

- Frontend: `http://localhost` (порт 80)
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

## 8. Доступ с другого устройства (LAN и белый IP)

- Важно: текущий LAN IP сервера может быть не `192.168.10.3`. Проверьте командой:
  - `ipconfig`
- На этом сервере сейчас активен адрес `192.168.100.3` (если сеть не менялась).
- Frontend должен открываться по:
  - `http://192.168.100.3`
- Backend API (проверка):
  - `http://192.168.100.3:8001/docs`

Если по IP не открывается:

1. Запустите `run_open_ports.bat` от имени администратора (откроет порты 80/8001/5555 в Windows Firewall).
2. Убедитесь, что процессы слушают `0.0.0.0`:
   - `netstat -ano | findstr :80`
   - `netstat -ano | findstr :8001`
3. Проверьте, что заходите на правильный LAN IP (`192.168.100.3`, а не `192.168.10.3`).

Для доступа по белому IP `78.139.95.130`:

- Нужен проброс портов на роутере (NAT/Port Forwarding):
  - `78.139.95.130:80 -> 192.168.100.3:80`
- Если провайдер использует CG-NAT, прямой доступ по белому IP может не работать даже при открытых локальных портах.
