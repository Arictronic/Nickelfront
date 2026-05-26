# Nickelfront

Nickelfront - локальная платформа для сбора, парсинга, индексации и анализа научных статей, патентов и PDF-документов. Проект ориентирован на Windows-сценарий запуска и объединяет FastAPI backend, React frontend, Celery workers, Redis, Qwen service и пайплайн обработки PDF.

## Что умеет проект

- собирать и обогащать метаданные статей и патентов
- скачивать и разбирать PDF
- извлекать текст, структуру и служебные признаки документов
- строить векторный поиск по ChromaDB
- отдавать API для поиска, аналитики, отчетов и мониторинга
- запускать AI-функции через `qwen_service`
- работать с очередями Celery и фоновыми задачами

## Структура репозитория

```text
Nickelfront/
|- backend/                    FastAPI API, сервисы, Celery tasks, Alembic
|- frontend/                   React + Vite frontend
|- parser_alpha/               парсеры источников и вспомогательные зависимости
|- qwen_service/               отдельный локальный сервис для AI/Qwen
|- rag/                        RAG-логика и связанные модули
|- shared/                     общие модели и схемы
|- scripts/                    bat/ps1 сценарии запуска, установки и диагностики
|- deploy/                     конфиги деплоя, включая nginx
|- storage/                    артефакты аудита, отчеты, runtime-данные
|- requirements.txt            общие Python-зависимости
|- install_all.bat             основной вход в установку
`- run_all.bat                 основной вход в локальный запуск
```

## Технологии

- Backend: FastAPI, SQLAlchemy, Alembic, Pydantic, Loguru
- Очереди: Celery, Redis, Flower
- Поиск и RAG: ChromaDB, sentence-transformers, LangChain
- PDF и экспорт: pdfplumber, PyMuPDF, reportlab, python-docx, WeasyPrint
- Frontend: React 18, Vite 5, TypeScript, Zustand, Recharts
- AI: локальный `qwen_service` и backend-интеграция

## Требования

Основной локальный сценарий рассчитан на Windows.

Нужно:
- Python `3.13+`
- Node.js `20` или `22` LTS желательно
- npm
- PostgreSQL

Опционально:
- Git
- Redis
  Если Redis не установлен, `scripts/run_redis.bat` умеет поднимать локальную portable-сборку.

Типовые локальные порты:
- Frontend: `5173`
- Backend API: `8001`
- Qwen service: `8767`
- Flower: `5555`
- Redis: `6380`
- PostgreSQL: обычно `5433`

## Настройка окружения

Шаблон переменных лежит в [.env.example](/d:/Project/Nickelfront/.env.example).

Минимально проверьте:
- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `QWEN_TOKEN`
- `QWEN_API_KEY`
- `API_PORT`
- `QWEN_SERVICE_PORT`
- `VITE_API_URL`

Важно:
- `.env` хранится локально и не должен коммититься
- плейсхолдеры в `.env.example` надо заменить на реальные значения
- без `QWEN_TOKEN` backend может стартовать, но AI-функции будут ограничены

## Быстрый старт

### 1. Установка

Из корня проекта:

```bat
install_all.bat
```

Сейчас `install_all.bat` делегирует в `scripts/nickelfront_doctor_setup_FIXED_v18.bat`. Если вы поддерживаете несколько вариантов doctor/setup-скриптов, сначала проверьте, какой из них считается каноническим для вашей ветки.

Ожидаемое поведение установки:
- создание `.venv`
- установка зависимостей из `requirements.txt`
- установка зависимостей frontend
- подготовка runtime-директорий
- установка Playwright Chromium при необходимости
- создание `.env` из `.env.example`, если `.env` отсутствует

### 2. Проверка `.env`

Перед первым полным запуском проверьте хотя бы:
- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `QWEN_TOKEN`
- `QWEN_API_KEY`

### 3. Локальный запуск

Основной стартовый скрипт:

```bat
run_all.bat
```

`run_all.bat` стартует сервисы в отдельных окнах примерно в таком порядке:
1. Redis
2. `qwen_service`
3. backend
4. frontend
5. отложенно: Qwen workers, content workers, обычные Celery workers и Flower

Важно:
- PostgreSQL должен быть запущен заранее
- отдельный RAG-сервис локально не поднимается, RAG идет через backend

### 4. Основные URL

- Frontend: `http://localhost:5173`
- Backend docs: `http://localhost:8001/docs`
- Backend health: `http://localhost:8001/health`
- Flower: `http://localhost:5555`

## Главные скрипты

### Установка и orchestration

- [install_all.bat](/d:/Project/Nickelfront/install_all.bat)  
  Точка входа для установки.
- [run_all.bat](/d:/Project/Nickelfront/run_all.bat)  
  Точка входа для локального старта всего стека.
- [scripts/run_deferred_workers.bat](/d:/Project/Nickelfront/scripts/run_deferred_workers.bat)  
  Отложенный старт тяжелых фоновых сервисов.

### Backend и frontend

- [scripts/run_backend.bat](/d:/Project/Nickelfront/scripts/run_backend.bat)  
  Активирует окружение, применяет миграции при необходимости и запускает backend.
- [scripts/run_frontend.bat](/d:/Project/Nickelfront/scripts/run_frontend.bat)  
  Запускает Vite dev server.
- [scripts/run_migrations.bat](/d:/Project/Nickelfront/scripts/run_migrations.bat)  
  Запускает только миграции.

### Redis и воркеры

- [scripts/run_redis.bat](/d:/Project/Nickelfront/scripts/run_redis.bat)  
  Старт Redis, при необходимости с локальной portable-сборкой.
- [scripts/run_worker.bat](/d:/Project/Nickelfront/scripts/run_worker.bat)  
  Старт обычного или content worker в зависимости от аргументов.
- [scripts/run_qwen_worker.bat](/d:/Project/Nickelfront/scripts/run_qwen_worker.bat)  
  Старт Qwen worker.
- [scripts/run_flower.bat](/d:/Project/Nickelfront/scripts/run_flower.bat)  
  Мониторинг очередей через Flower.

### Диагностика и PDF

- [scripts/PDF_PARSER_AUDIT.bat](/d:/Project/Nickelfront/scripts/PDF_PARSER_AUDIT.bat)  
  Основной запуск аудита PDF parser.
- [scripts/run_pdf_parser_audit.bat](/d:/Project/Nickelfront/scripts/run_pdf_parser_audit.bat)  
  Вспомогательный запуск audit-процесса.
- [scripts/verify_pdf_parser_patch.bat](/d:/Project/Nickelfront/scripts/verify_pdf_parser_patch.bat)  
  Проверка патча PDF parser.
- [scripts/test_qwen.bat](/d:/Project/Nickelfront/scripts/test_qwen.bat)  
  Базовая проверка интеграции с Qwen.

### Вспомогательные утилиты

- [run_cleanup_tasks_and_papers.bat](/d:/Project/Nickelfront/run_cleanup_tasks_and_papers.bat)  
  Очистка runtime-данных задач, буферов и части служебных артефактов.
- [scripts/load_env.bat](/d:/Project/Nickelfront/scripts/load_env.bat)  
  Загрузка `.env` в текущий batch-процесс.
- [scripts/load_env.ps1](/d:/Project/Nickelfront/scripts/load_env.ps1)  
  PowerShell-вариант загрузки `.env`.
- [scripts/nf-server.ps1](/d:/Project/Nickelfront/scripts/nf-server.ps1)  
  Вспомогательный PowerShell runner.

## Backend API

Ключевые backend endpoint-ы:
- `/`
- `/ping`
- `/health`
- `/docs`
- `/api/v1/...`

Основная сборка роутеров находится в [backend/app/main.py](/d:/Project/Nickelfront/backend/app/main.py). Там подключены модули:
- auth
- parse
- tasks
- analytics
- reports
- monitoring
- search
- qwen
- rag
- vector
- admin settings

## Qwen service

`qwen_service` используется как отдельный локальный сервис для AI-функций.

Типовой сценарий:
1. заполнить `QWEN_TOKEN` в `.env`
2. запустить `scripts/run_qwen_service.bat`
3. при очередном режиме дополнительно запустить `scripts/run_qwen_worker.bat`

Полезные команды для токена из HAR:

```bat
python qwen_service/har_token_scanner.py --instructions
python qwen_service/har_token_scanner.py "chat.qwen.ai.har" --apply
python qwen_service/har_token_scanner.py "chat.qwen.ai.har" --apply --push-service --validate
```

## PDF parsing

PDF-пайплайн сосредоточен в `backend/app/services/pdf_parser/`.

Важно:
- в коде используется `import fitz`, но правильная зависимость в проекте это `PyMuPDF`
- отдельный пакет `fitz` ставить не нужно
- аудит и проверочные артефакты пишутся в `storage/pdf_parser_audit/`
- для части OCR-сценариев может использоваться `pytesseract`

## Frontend

Основные команды:

```bat
cd frontend
npm install
npm run dev
npm run build
npm test -- --run
```

Сейчас frontend использует:
- React 18
- Vite 5
- Vitest 1
- Axios 1.16.x

## Тесты

Python / backend:

```bat
.venv\Scripts\python -m pytest
```

Frontend:

```bat
cd frontend
npm test -- --run
```

Qwen smoke-check:

```bat
scripts\test_qwen.bat
```

## Частые проблемы

Если не стартует backend:
- проверьте PostgreSQL и `DATABASE_URL`
- прогоните `scripts/run_migrations.bat`
- посмотрите логи в `logs/`

Если frontend поднялся, но не видит API:
- проверьте backend на `http://127.0.0.1:8001`
- проверьте `API_PORT`
- проверьте `VITE_API_URL`

Если не работают Qwen-функции:
- проверьте `QWEN_TOKEN`
- запустите `scripts/run_qwen_service.bat`
- если используется очередь, запустите `scripts/run_qwen_worker.bat`

Если не хватает Playwright browser runtime:

```bat
.venv\Scripts\python -m playwright install chromium
```

Если нужен почти чистый runtime reset:
- используйте `run_cleanup_tasks_and_papers.bat`
- перед этим убедитесь, что понимаете, какие локальные данные и временные артефакты будут очищены
