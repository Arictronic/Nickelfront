# Nickelfront

Nickelfront - полнофункциональная платформа для сбора, обработки и анализа научных статей и патентов по материаловедению, с акцентом на никелевые сплавы, суперсплавы и смежные темы.

В репозитории уже есть:
- `backend/` на FastAPI + SQLAlchemy + Alembic
- `frontend/` на React + Vite + TypeScript
- фоновые очереди на `Celery + Redis`
- `qwen_service/` для автономной интеграции с Qwen
- `parser_alpha/` с парсерами источников
- `analytics/`, `rag/`, `shared/` и набор bat/ps1-скриптов для локального запуска

## Что Умеет Проект

- собирает статьи из нескольких источников через задачи парсинга
- сохраняет метаданные и результаты обработки в PostgreSQL
- скачивает и дообрабатывает PDF в фоновых очередях
- строит векторный поиск через ChromaDB и эмбеддинги
- выполняет полнотекстовый поиск и аналитику
- генерирует краткие сводки и анализ на русском языке через Qwen
- предоставляет веб-интерфейс для поиска, мониторинга, отчетов и администрирования

## Технологический Стек

- Python 3.11+ рекомендуется
- FastAPI
- SQLAlchemy 2
- Alembic
- PostgreSQL
- Redis
- Celery
- ChromaDB
- sentence-transformers
- React 18
- Vite
- TypeScript

## Структура Проекта

```text
Nickelfront/
|- backend/                  FastAPI-приложение, сервисы, задачи, миграции
|- frontend/                 интерфейс на React
|- parser_alpha/             парсеры источников и связанные тесты
|- qwen_service/             автономный HTTP-сервис Qwen
|- analytics/                метрики и отчеты
|- rag/                      модули и тесты RAG
|- shared/                   общие схемы
|- scripts/                  вспомогательные bat/ps1-скрипты
|- run_all.bat               основной скрипт локального запуска
|- install_all.bat           единый установочный скрипт
|- run_backend.bat
|- run_frontend.bat
|- run_worker.bat
|- run_qwen_worker.bat
|- run_qwen_service.bat
|- run_redis.bat
```

## Требования

Сейчас репозиторий ориентирован в первую очередь на локальную разработку под Windows, потому что основные сценарии запуска оформлены через `.bat` и `.ps1`.

Перед первым запуском нужны:
- Python 3.11 или новее
- Node.js 18 или новее
- npm
- PostgreSQL

Дополнительно полезно:
- Git
- Redis может скачаться автоматически через `run_redis.bat`, если локально его еще нет

Порты по умолчанию:
- Frontend: `5173`
- Backend API: `8001`
- Qwen-сервис: `8767`
- Flower: `5555`
- Redis: `6380`
- PostgreSQL: обычно `5433` в конфигурации проекта

## Быстрый Старт

### 1. Установить всё сразу

Из корня репозитория:

```bat
install_all.bat
```

Что делает установочный скрипт:
- создает `.venv`, если окружения еще нет
- обновляет `pip`, `setuptools`, `wheel`
- ставит Python-зависимости из `requirements.txt`
- ставит зависимости frontend через `npm install`
- ставит Playwright Chromium для сценариев парсинга
- создает `.env` из `.env.example`, если `.env` отсутствует
- создает базовые локальные директории проекта

### 2. Настроить окружение

Если `.env` был создан из шаблона, в первую очередь проверьте:
- `DATABASE_URL`
- `SECRET_KEY`
- `QWEN_TOKEN`, если нужен рабочий Qwen

Файл-шаблон: [`.env.example`](/d:/Project/Nickelfront/.env.example)

Важно:
- `.env` игнорируется git
- не коммитьте реальные секреты и токены
- если секреты уже куда-то утекли, их нужно перевыпустить или заменить

### 2.1. Какие ключи и токены нужно добавить в `.env`

Обязательно для нормального локального запуска:
- `SECRET_KEY` - секрет для JWT и внутреннего подписывания
- `DATABASE_URL` - строка подключения к PostgreSQL
- `REDIS_URL` - адрес Redis

Обязательно для работы Qwen:
- `QWEN_TOKEN` - основной токен доступа к Qwen-провайдеру

Опционально, но может понадобиться:
- `QWEN_API_KEY` - локальный ключ защиты `qwen_service`; нужен, если вы хотите закрыть прямой доступ к сервису
- `CORE_API_KEY` - ключ для источника CORE, нужен для более стабильной работы парсинга CORE
- `SEMANTIC_SCHOLAR_API_KEY` - ключ для Semantic Scholar, если используете соответствующие интеграции или расширенный сбор данных

Обычно не являются токенами, но тоже важны:
- `VITE_API_URL` - адрес API для frontend
- `CORS_ORIGINS` - список разрешенных origin
- `QWEN_SERVICE_HOST` и `QWEN_SERVICE_PORT` - адрес локального Qwen-сервиса

Если хотите использовать проект без Qwen-функций:
- можно оставить `QWEN_TOKEN` пустым
- но тогда чат, AI-анализ, markdown-нормализация и часть связанных задач работать не будут

### 3. Подготовить PostgreSQL

Создайте базу данных, указанную в `DATABASE_URL`.

Типичный локальный вариант:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/nickelfront
```

### 4. Запустить систему

Основной локальный сценарий:

```bat
run_all.bat
```

Скрипт поднимает:
- Redis
- Qwen-сервис
- backend API
- frontend
- тяжелые worker-процессы с отложенным запуском
- Flower

Запуск специально разбит по этапам: UI поднимается раньше, а тяжелые worker-процессы стартуют немного позже.

После старта будут доступны:
- Frontend: `http://localhost:5173`
- Документация backend: `http://localhost:8001/docs`
- Endpoint проверки состояния: `http://localhost:8001/health`
- Flower: `http://localhost:5555`

## Основные Скрипты

Если нужен запуск по частям:

- `run_backend.bat` - запускает backend и предварительно применяет Alembic-миграции
- `run_frontend.bat` - запускает dev-сервер Vite
- `run_redis.bat` - запускает Redis на порту из `.env`
- `run_qwen_service.bat` - запускает автономный Qwen-сервис
- `run_worker.bat` - запускает обычный Celery worker
- `run_qwen_worker.bat` - запускает отдельный worker для очереди Qwen
- `run_deferred_workers.bat` - запускает отложенную группу worker-процессов
- `run_flower.bat` - запускает мониторинг Flower
- `run_migrations.bat` - применяет только Alembic-миграции
- `run_cleanup_tasks_and_papers.bat` - очищает runtime-данные по статьям, задачам и связанным артефактам
- `test.bat` - запускает проверочный сценарий параллельного Qwen-чата

## Основные Переменные Окружения

Ключевые переменные проекта:

- `DATABASE_URL` - строка подключения к PostgreSQL
- `REDIS_URL` - строка подключения к Redis
- `SECRET_KEY` - секрет для JWT и подписи токенов
- `API_HOST` и `API_PORT` - адрес и порт backend
- `CORS_ORIGINS` - разрешенные источники для frontend
- `QWEN_TOKEN` - основной токен провайдера Qwen
- `QWEN_API_KEY` - опциональный ключ защиты локального `qwen_service`
- `QWEN_SERVICE_HOST` и `QWEN_SERVICE_PORT` - адрес автономного Qwen-сервиса
- `QWEN_QUEUE_NAME` - очередь Celery для Qwen-задач
- `CONTENT_QUEUE_NAME` - очередь Celery для PDF и обработки контента
- `EMBEDDING_MODEL` - имя модели эмбеддингов
- `CHROMA_DB_PATH` - путь к хранилищу ChromaDB
- `VITE_API_URL` - переопределение адреса API для frontend
- `VITE_PROXY_TARGET` - локальная proxy-цель для frontend

В качестве безопасной стартовой конфигурации используйте [`.env.example`](/d:/Project/Nickelfront/.env.example).

## Первый Вход

При логине backend автоматически гарантирует наличие встроенной админской учетной записи.

Дефолтные учетные данные:
- email: `admin@admin.com`
- password: `admin`

Используйте их только для первого локального входа.

## Тестирование

Python/backend тесты:

```bat
.venv\Scripts\python -m pytest
```

Frontend тесты:

```bat
cd frontend
npm test
```

Также в репозитории есть интеграционные и специализированные тесты в `tests/`, `parser_alpha/tests/` и `rag/tests/`.

## Диагностика

Если backend не стартует:
- проверьте, что PostgreSQL запущен и `DATABASE_URL` указан правильно
- выполните `run_migrations.bat`
- посмотрите логи в `logs/`

Если frontend открывается, но API не отвечает:
- проверьте доступность backend на `http://127.0.0.1:8001`
- проверьте `.env`: `API_PORT`, `VITE_API_URL`, `VITE_PROXY_TARGET`

Если не работают Qwen API-методы:
- проверьте `QWEN_TOKEN`
- запустите `run_qwen_service.bat`
- запустите `run_qwen_worker.bat`, если ожидаются очереди Qwen

Если парсерам нужен браузерный runtime для автоматизации:
- повторно выполните `install_all.bat` или вручную:

```bat
.venv\Scripts\python -m playwright install chromium
```

## Примечания

- `run_backend.bat` автоматически применяет Alembic migrations, если не задан `SKIP_BACKEND_MIGRATIONS=1`
- Redis и PostgreSQL нужны одновременно: для корректной работы backend оба сервиса должны быть доступны
- в текущем локальном сценарии RAG обслуживается через backend, `run_all.bat` не поднимает отдельный RAG-сервис
- в рабочем дереве могут появляться runtime-данные и сгенерированные файлы: `logs/`, `chroma_db/`, `storage/`, `archives/`, `redis/`
