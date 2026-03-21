# Nickelfront Backend

Backend на FastAPI с очередью задач на Celery + Redis.

## Быстрый старт

### Вариант 1: Docker Compose (рекомендуется)

```bash
cd backend

# Запуск всех сервисов (PostgreSQL, Redis, Backend, Worker)
docker-compose up --build

# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f worker
docker-compose logs -f backend
```

Сервисы будут доступны по адресам:
- **API**: http://localhost:8000
- **Docs (Swagger)**: http://localhost:8000/docs
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### Вариант 2: Локальная разработка

```bash
cd backend

# Установка зависимостей
pip install -r requirements.txt

# Запуск Redis (требуется установленный Redis)
# Windows: скачайте с https://github.com/microsoftarchive/redis/releases
# Linux: sudo systemctl start redis

# Запуск PostgreSQL (требуется установленный PostgreSQL)
# Создайте базу данных:
# createdb -U user nickelfront

# Инициализация БД
python -m app.db.init_db

# Запуск сервера разработки
uvicorn app.main:app --reload --port 8000

# Запуск Celery worker (в отдельном терминале)
celery -A app.tasks.celery_app worker --loglevel=info
```

## API Endpoints

### Tasks

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/tasks/` | Создать задачу на обработку патента |
| GET | `/api/v1/tasks/{task_id}` | Получить статус задачи |

### Примеры запросов

**Создание задачи:**
```bash
curl -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"patent_number": "RU123456", "options": {}}'
```

**Получение статуса:**
```bash
curl http://localhost:8000/api/v1/tasks/1
```

## Структура проекта

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── endpoints/
│   │           └── tasks.py       # API роуты
│   ├── core/
│   │   ├── config.py              # Настройки приложения
│   │   └── logging.py             # Настройка логирования
│   ├── db/
│   │   ├── models/
│   │   │   └── task.py            # SQLAlchemy модели
│   │   ├── base.py                # Базовый класс для моделей
│   │   ├── session.py             # Сессии БД
│   │   └── init_db.py             # Инициализация БД
│   ├── services/
│   │   └── task_service.py        # Бизнес-логика
│   ├── tasks/
│   │   ├── celery_app.py          # Настройка Celery
│   │   └── tasks.py               # Celery задачи
│   └── main.py                    # Точка входа FastAPI
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Команды Celery

```bash
# Запуск worker
celery -A app.tasks.celery_app worker --loglevel=info

# Запуск flower (мониторинг)
celery -A app.tasks.celery_app flower --port=5555

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
