# 📦 Развёртывание Nickelfront на сервере

## 🚀 Быстрый старт на сервере

### Вариант 1: Docker Compose (рекомендуется)

```bash
# 1. Клонируйте репозиторий на сервер
git clone <repository-url>
cd Nickelfront

# 2. Настройте .env.docker (при необходимости)
nano .env.docker

# 3. Запустите все сервисы
docker-compose -f docker-compose.prod.yml up -d

# 4. Проверьте статус
docker-compose -f docker-compose.prod.yml ps

# 5. Откройте в браузере
# http://<ваш-ip>
```

**Сервисы:**
- **Frontend** (порт 80) — веб-интерфейс
- **Backend** (порт 8001 внутри сети) — API
- **PostgreSQL** (порт 5432 внутри сети) — база данных
- **Redis** (порт 6379 внутри сети) — кэш и очередь
- **Celery Worker** — фоновые задачи
- **Celery Beat** — периодические задачи
- **Flower** (порт 5555) — мониторинг Celery

---

### Вариант 2: Ручная установка (Linux)

#### 1. Установка зависимостей

```bash
# Python
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip

# Node.js
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Redis
sudo apt install -y redis-server

# Nginx
sudo apt install -y nginx
```

#### 2. Настройка PostgreSQL

```bash
sudo -u postgres psql
CREATE DATABASE nickelfront;
CREATE USER postgres WITH PASSWORD 'postgres';
GRANT ALL PRIVILEGES ON DATABASE nickelfront TO postgres;
\q
```

#### 3. Настройка Redis

```bash
sudo systemctl start redis
sudo systemctl enable redis
```

#### 4. Установка Backend

```bash
cd Nickelfront

# Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install -r backend/requirements.txt

# Копируем .env
cp .env.docker .env

# Запускаем backend
python backend/start_server.py
```

#### 5. Сборка Frontend

```bash
cd frontend

# Устанавливаем зависимости
npm install

# Собираем
npm run build

# Копируем в nginx
sudo cp -r dist/* /var/www/nickelfront/
```

#### 6. Настройка Nginx

```bash
# Копируем конфигурацию
sudo cp deploy/nginx.conf /etc/nginx/sites-available/nickelfront
sudo ln -s /etc/nginx/sites-available/nickelfront /etc/nginx/sites-enabled/

# Проверяем конфигурацию
sudo nginx -t

# Перезапускаем nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

#### 7. Запуск Celery Worker

```bash
# В отдельном терминале
source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info -E
```

#### 8. Запуск Celery Beat

```bash
# В отдельном терминале
source venv/bin/activate
celery -A app.tasks.celery_app beat --loglevel=info
```

---

## 🔧 Конфигурация

### Переменные окружения

| Переменная | Описание | Значение по умолчанию |
|------------|----------|----------------------|
| `API_HOST` | Хост для backend | `0.0.0.0` |
| `API_PORT` | Порт для backend | `8001` |
| `DATABASE_URL` | URL PostgreSQL | `postgresql+asyncpg://...` |
| `REDIS_URL` | URL Redis | `redis://localhost:6380/0` |
| `CORS_ORIGINS` | Разрешённые домены | `["*"]` |
| `VITE_API_URL` | URL API для frontend | `` (относительный путь) |

### Важные изменения для работы на сервере

1. **`.env`**:
   - `API_HOST=0.0.0.0` — слушать все интерфейсы
   - `CORS_ORIGINS=["*"]` — разрешить все домены
   - `VITE_API_URL=` — пустое значение для относительного пути

2. **Frontend** (`frontend/src/api/client.ts`):
   - Использует относительный путь `/api/v1`
   - Запросы идут на тот же домен, где размещён frontend

3. **Nginx**:
   - Проксирует `/api/` на `http://localhost:8001/api/`
   - Раздаёт статику frontend

---

## 🔍 Проверка работы

```bash
# Проверка backend
curl http://localhost:8001/health

# Проверка frontend
curl http://localhost/

# Проверка API через nginx
curl http://localhost/api/v1/auth/me
```

---

## 📊 Мониторинг

### Flower (Celery мониторинг)

```bash
# Откройте в браузере
http://<ваш-ip>:5555
```

### Логи

```bash
# Backend логи
tail -f logs/app.log

# Docker логи
docker-compose -f docker-compose.prod.yml logs -f backend
docker-compose -f docker-compose.prod.yml logs -f worker
```

---

## 🔒 Безопасность (продакшен)

Перед развёртыванием в продакшене:

1. **Смените секретные ключи**:
   ```bash
   # В .env.docker
   SECRET_KEY=<сгенерируйте новый ключ>
   ```

2. **Ограничьте CORS**:
   ```bash
   # В .env.docker
   CORS_ORIGINS=["https://ваш-домен.com"]
   ```

3. **Настройте HTTPS** (рекомендуется):
   ```bash
   # Используйте Let's Encrypt
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d ваш-домен.com
   ```

4. **Смените пароли БД**:
   ```bash
   # В .env.docker
   DATABASE_URL=postgresql+asyncpg://user:password@...
   ```

---

## 🐛 Решение проблем

### Backend не запускается

```bash
# Проверьте логи
python backend/start_server.py 2>&1 | tee backend.log

# Проверьте подключение к БД
psql postgresql://user:pass@localhost:5433/nickelfront
```

### Frontend не видит API

```bash
# Проверьте nginx конфигурацию
sudo nginx -t

# Проверьте логи nginx
sudo tail -f /var/log/nginx/error.log

# Проверьте, что backend работает
curl http://localhost:8001/health
```

### Celery не выполняет задачи

```bash
# Проверьте, что worker запущен
celery -A app.tasks.celery_app inspect ping

# Проверьте Redis
redis-cli ping

# Проверьте логи worker
celery -A app.tasks.celery_app worker --loglevel=debug
```

---

## 📝 Архитектура развёртывания

```
┌─────────────────────────────────────────────────────────┐
│                     Nginx (порт 80)                     │
│  ┌─────────────────┐    ┌─────────────────────────┐    │
│  │   Frontend      │    │   Proxy /api/           │    │
│  │   (статика)     │───▶│   → Backend:8001        │    │
│  └─────────────────┘    └─────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Backend (FastAPI, порт 8001)               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   Celery     │  │   PostgreSQL │  │    Redis     │ │
│  │   Worker     │  │   (БД)       │  │   (кэш/оч)   │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```
