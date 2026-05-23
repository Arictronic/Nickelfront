# Nickelfront

Nickelfront - платформа для сбора, обработки и анализа научных статей и патентов по материаловедению, с акцентом на никелевые сплавы, суперсплавы и смежные темы.

Проект включает:
- backend на FastAPI + SQLAlchemy + Alembic
- frontend на React + Vite + TypeScript
- фоновые очереди Celery + Redis
- автономный `qwen_service` для работы с Qwen
- `parser_alpha` с парсерами источников
- векторный поиск на ChromaDB
- набор bat/ps1-скриптов для локального запуска под Windows

## Что Умеет Проект

- собирает статьи из нескольких источников через задачи парсинга
- хранит метаданные, историю задач и результаты обработки в PostgreSQL
- скачивает PDF и выполняет постобработку в фоновых очередях
- строит векторный поиск через эмбеддинги и ChromaDB
- выполняет полнотекстовый поиск, аналитику и построение отчетов
- генерирует AI-анализ и русскоязычные сводки через Qwen
- предоставляет веб-интерфейс для поиска, мониторинга и администрирования

## Основные Каталоги

```text
Nickelfront/
|- backend/                  FastAPI-приложение, сервисы, задачи, миграции
|- frontend/                 интерфейс на React
|- parser_alpha/             парсеры, маршрутизация источников, тесты
|- qwen_service/             автономный HTTP-сервис Qwen и токен-утилиты
|- analytics/                метрики и отчеты
|- rag/                      модули и тесты RAG
|- shared/                   общие схемы и модели обмена
|- scripts/                  вспомогательные bat/ps1-скрипты
|- install_all.bat           установка локального окружения
|- run_all.bat               основной сценарий локального запуска
|- run_cleanup_tasks_and_papers.bat
|- Qwen_scaner.py            wrapper для извлечения Qwen-токена из HAR
```

## Требования

Локальный сценарий ориентирован в первую очередь на Windows.

Нужно установить:
- Python 3.11 или новее
- Node.js 18 или новее
- npm
- PostgreSQL

Опционально:
- Git
- Redis можно не ставить заранее: `run_redis.bat` умеет скачать локальную сборку автоматически

Порты по умолчанию:
- frontend: `5173`
- backend API: `8001`
- qwen_service: `8767`
- Flower: `5555`
- Redis: `6380`
- PostgreSQL: обычно `5433`

## Быстрый Старт

### 1. Установка

Из корня проекта:

```bat
install_all.bat
```

Скрипт:
- создает `.venv`
- обновляет `pip`, `setuptools`, `wheel`
- ставит Python-зависимости из `requirements.txt`
- ставит frontend-зависимости через `npm install`
- ставит Playwright Chromium
- создает `.env` из [`.env.example`](/d:/Project/Nickelfront/.env.example), если `.env` отсутствует
- создает рабочие каталоги проекта

### 2. Настройка `.env`

Минимально проверьте:
- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `QWEN_TOKEN`, если нужен рабочий Qwen

Важно:
- `.env` игнорируется git
- реальные токены и секреты нельзя коммитить
- если токен или ключ уже куда-то утек, его нужно заменить

### 3. Какие ключи и токены нужны

Обязательно для запуска:
- `DATABASE_URL` - PostgreSQL
- `REDIS_URL` - Redis
- `SECRET_KEY` - JWT и подпись внутренних токенов

Обязательно для AI-функций Qwen:
- `QWEN_TOKEN` - основной токен доступа к Qwen

Опционально:
- `QWEN_API_KEY` - защита локального `qwen_service`
- `CORE_API_KEY` - улучшает работу с источником CORE
- `SEMANTIC_SCHOLAR_API_KEY` - нужен для соответствующих интеграций, если вы их используете

Если `QWEN_TOKEN` пустой:
- backend и frontend могут запускаться
- но чат, AI-анализ, markdown-нормализация и связанные Qwen-задачи работать не будут

### 4. Подготовка PostgreSQL

Создайте базу данных из `DATABASE_URL`.

Типичный локальный пример:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/nickelfront
```

### 5. Запуск всего проекта

Основной сценарий:

```bat
run_all.bat
```

Что делает `run_all.bat`:
- загружает переменные из `.env`
- запускает Redis
- запускает `qwen_service`
- запускает backend
- рано поднимает frontend
- откладывает тяжелые сервисы через `run_deferred_workers.bat`

Тяжелые сервисы:
- qwen workers
- content workers
- обычные Celery workers
- Flower

После старта обычно доступны:
- frontend: `http://localhost:5173`
- backend docs: `http://localhost:8001/docs`
- backend health: `http://localhost:8001/health`
- Flower: `http://localhost:5555`

## Все Основные Bat-Скрипты

### Установка и базовый запуск

- [install_all.bat](/d:/Project/Nickelfront/install_all.bat) - устанавливает локальное окружение и зависимости
- [run_all.bat](/d:/Project/Nickelfront/run_all.bat) - основной сценарий запуска всего проекта
- [run_deferred_workers.bat](/d:/Project/Nickelfront/run_deferred_workers.bat) - запускает тяжелые worker-сервисы с задержкой

### Backend и frontend

- [run_backend.bat](/d:/Project/Nickelfront/run_backend.bat) - запускает backend и перед этим применяет Alembic-миграции
- [run_frontend.bat](/d:/Project/Nickelfront/run_frontend.bat) - запускает Vite dev server
- [run_migrations.bat](/d:/Project/Nickelfront/run_migrations.bat) - применяет только миграции

### Redis и очереди

- [run_redis.bat](/d:/Project/Nickelfront/run_redis.bat) - запускает Redis; при необходимости скачивает локальную сборку
- [run_worker.bat](/d:/Project/Nickelfront/run_worker.bat) - запускает обычный Celery worker или content worker, в зависимости от очереди
- [run_qwen_worker.bat](/d:/Project/Nickelfront/run_qwen_worker.bat) - запускает отдельный worker только для очереди Qwen
- [run_flower.bat](/d:/Project/Nickelfront/run_flower.bat) - запускает Flower для мониторинга Celery

### Qwen и диагностика

- [run_qwen_service.bat](/d:/Project/Nickelfront/run_qwen_service.bat) - запускает автономный `qwen_service`
- [Qwen_scaner.py](/d:/Project/Nickelfront/Qwen_scaner.py) - обертка над `qwen_service.har_token_scanner`, извлекает `QWEN_TOKEN` из HAR-файла
- [scripts/test_qwen.bat](/d:/Project/Nickelfront/scripts/test_qwen.bat) - сценарий проверки параллельной работы Qwen через backend API

### Очистка и вспомогательные инструменты

- [run_cleanup_tasks_and_papers.bat](/d:/Project/Nickelfront/run_cleanup_tasks_and_papers.bat) - очищает runtime-данные: статьи, очереди, Chroma, PDF, логи и т.п.
- [scripts/load_env.bat](/d:/Project/Nickelfront/scripts/load_env.bat) - загружает `.env` в текущий bat-процесс
- [scripts/nickelfront_doctor_setup_FIXED_v18.bat](/d:/Project/Nickelfront/scripts/nickelfront_doctor_setup_FIXED_v18.bat) - большой диагностический/setup-скрипт
- [scripts/nf-server.ps1](/d:/Project/Nickelfront/scripts/nf-server.ps1) - вспомогательный PowerShell-скрипт

## `Qwen_scaner.py`

Файл [Qwen_scaner.py](/d:/Project/Nickelfront/Qwen_scaner.py) - это совместимый wrapper над `qwen_service/har_token_scanner.py`.

Он нужен, чтобы:
- извлечь `QWEN_TOKEN` из HAR-файла `chat.qwen.ai`
- записать токен в `.env`
- отправить токен в уже запущенный `qwen_service`
- проверить, что токен сервисом принимается

Примеры:

```bat
python Qwen_scaner.py --instructions
python Qwen_scaner.py "chat.qwen.ai.har" --apply
python Qwen_scaner.py "chat.qwen.ai.har" --apply --push-service --validate
```

Полезные флаги:
- `--apply` - записать токен в `.env`
- `--push-service` - отправить токен в работающий `qwen_service`
- `--validate` - проверить токен через `/auth/status`
- `--instructions` - показать инструкцию, как снять HAR из браузера
- `--print-token` - печатает полный токен; использовать осторожно

## Роли Очередей И Worker-Процессов

В проекте есть разделение по очередям:
- `qwen` - задачи Qwen
- `content` - PDF, извлечение текста, embedding и связанная постобработка
- `celery` - обычные фоновые задачи

Отсюда и разные bat-скрипты:
- `run_qwen_worker.bat` обслуживает только очередь `qwen`
- `run_worker.bat` в обычном режиме обслуживает очередь `celery`
- `run_worker.bat` с очередью `content` превращается в content worker

## Первый Вход

При логине backend автоматически гарантирует наличие встроенной админской учетной записи.

Данные по умолчанию:
- email: `admin@admin.com`
- password: `admin`

Используйте их только для первого локального входа.

## Тестирование

Python/backend:

```bat
.venv\Scripts\python -m pytest
```

Frontend:

```bat
cd frontend
npm test
```

Qwen-проверка через bat-сценарий:

```bat
scripts\test_qwen.bat
```

Также в репозитории есть тесты в:
- `tests/`
- `parser_alpha/tests/`
- `rag/tests/`

## Диагностика

Если backend не стартует:
- проверьте PostgreSQL и `DATABASE_URL`
- выполните `run_migrations.bat`
- проверьте логи в `logs/`

Если frontend открылся, но API не отвечает:
- проверьте backend на `http://127.0.0.1:8001`
- проверьте `API_PORT`, `VITE_API_URL`, `VITE_PROXY_TARGET`

Если не работают функции Qwen:
- проверьте `QWEN_TOKEN`
- запустите `run_qwen_service.bat`
- при фоновых задачах проверьте `run_qwen_worker.bat`

Если нужен браузерный runtime для парсеров:

```bat
.venv\Scripts\python -m playwright install chromium
```

Если хотите почти чистый runtime-reset:
- используйте `run_cleanup_tasks_and_papers.bat`
- по умолчанию пользователи и refresh tokens сохраняются

## Примечания

- `run_backend.bat` автоматически применяет миграции, если не задан `SKIP_BACKEND_MIGRATIONS=1`
- `run_all.bat` не поднимает отдельный RAG-сервис, потому что RAG обслуживается через backend
- Redis и PostgreSQL нужны одновременно для полноценной работы проекта
- в рабочем дереве появляются runtime-данные и сгенерированные артефакты: `logs/`, `chroma_db/`, `storage/`, `archives/`, `redis/`
