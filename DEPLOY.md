# Развёртывание Nickelfront

## Требования

- Python 3.11+
- Node.js 20+
- PostgreSQL
- Redis
- Nginx

## 1. Подготовка окружения

```bash
git clone <repository-url>
cd Nickelfront
```

## 2. Backend

```bash
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows
# .\\venv\\Scripts\\activate

pip install -r backend/requirements.txt
```

Создайте `.env` в корне проекта и заполните ключевые переменные:

```env
API_HOST=0.0.0.0
API_PORT=8001
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nickelfront
REDIS_URL=redis://localhost:6380/0
CORS_ORIGINS=["*"]
```

Примените миграции:

```bash
cd backend
alembic upgrade head
cd ..
```

## 3. Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

## 4. Запуск сервисов

В отдельных терминалах:

```bash
# API
python backend/start_server.py

# Celery worker
celery -A app.tasks.celery_app worker --loglevel=info -E

# Celery beat
celery -A app.tasks.celery_app beat --loglevel=info

# Flower (опционально)
celery -A app.tasks.celery_app flower --port=5555
```

## 5. Nginx

Используйте конфиг из `deploy/nginx.conf` и проверьте его:

```bash
sudo nginx -t
sudo systemctl restart nginx
```

## Проверка

```bash
curl http://localhost:8001/health
curl http://localhost/api/v1/papers/count
```

## Логи

Все логи хранятся в каталоге `logs/`.
