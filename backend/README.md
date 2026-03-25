# Nickelfront Backend

Backend на FastAPI с очередью задач на Celery + Redis.

## Быстрый старт

### Локальный запуск (Windows)

```bash
cd backend

# Установка зависимостей
pip install -r requirements.txt

# Запуск сервера
..\run_backend.bat

# Запуск Celery worker (в отдельном окне)
..\run_worker.bat
```

### Docker Compose

```bash
cd backend

# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f worker
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

### Примеры

```bash
# Health check
curl http://localhost:8000/health

# Получить статьи
curl http://localhost:8000/api/v1/papers?limit=10

# Запустить парсинг
curl -X POST "http://localhost:8000/api/v1/papers/parse?query=nickel%20alloys&limit=5&source=arXiv"
```

## Структура

```
backend/
├── app/
│   ├── api/v1/endpoints/
│   │   └── parse.py         # API роуты для парсинга
│   ├── core/
│   │   ├── config.py        # Настройки приложения
│   │   └── logging.py       # Логирование
│   ├── db/
│   │   ├── models/
│   │   │   ├── paper.py     # Модель статьи
│   │   │   └── task.py      # Модель задачи
│   │   ├── base.py          # Базовый класс SQLAlchemy
│   │   ├── session.py       # Сессии БД
│   │   └── init_db.py       # Инициализация БД
│   ├── services/
│   │   ├── paper_service.py # Бизнес-логика для статей
│   │   └── task_service.py  # Бизнес-логика для задач
│   ├── tasks/
│   │   ├── celery_app.py    # Настройка Celery
│   │   └── parse_tasks.py   # Celery задачи для парсинга
│   └── main.py              # Точка входа FastAPI
├── tests/                   # Тесты
├── alembic/                 # Миграции БД
├── requirements.txt         # Зависимости
└── .env                     # Переменные окружения
```

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

# Unit тесты парсеров
pytest tests/unit/parser/ -v

# Integration тесты
pytest tests/integration/ -v
```

## Переменные окружения

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/nickelfront
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
```
