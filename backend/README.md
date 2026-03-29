# Nickelfront Backend

Backend на FastAPI с очередью задач Celery + Redis.

## Быстрый старт

### Локальный запуск (Windows)

```bash
cd backend

# Установка зависимостей
pip install -r requirements.txt

# Запуск API
..\run_backend.bat

# Запуск Celery worker (в отдельном окне)
..\run_worker.bat
```

## API Endpoints

### Papers

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/papers` | Список статей |
| GET | `/api/v1/papers/count` | Количество статей |
| GET | `/api/v1/papers/id/{id}` | Статья по ID |
| POST | `/api/v1/papers/search` | Поиск в БД |
| POST | `/api/v1/papers/parse` | Запустить парсинг |
| POST | `/api/v1/papers/parse-all` | Массовый парсинг |
| DELETE | `/api/v1/papers/id/{id}` | Удалить статью |

## Команды Celery

```bash
# Запуск worker
celery -A app.tasks.celery_app worker --loglevel=info

# Проверка worker
celery -A app.tasks.celery_app inspect ping
```

## Миграции БД (Alembic)

```bash
# Создать миграцию
alembic revision --autogenerate -m "Description"

# Применить миграции
alembic upgrade head

# Откатить миграции
alembic downgrade -1
```

## Тесты

```bash
# Все тесты
pytest tests/ -v
```

## Переменные окружения

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/nickelfront
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```
