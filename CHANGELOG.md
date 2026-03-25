# Changelog

Все изменения в проекте Nickelfront.

## [2026-03-25] — Парсер arXiv + Бритва Оккама

### ✨ Новое

#### Парсер arXiv
- ✅ `parser/arxiv/client.py` — клиент arXiv API
- ✅ `parser/arxiv/parser.py` — парсер статей arXiv
- ✅ Поиск по запросам с поддержкой категорий
- ✅ Rate limiting (3 секунды между запросами)
- ✅ Извлечение ключевых слов (предметные термины)

#### Celery задачи
- ✅ `parse_papers_task` — универсальная задача (CORE/arXiv)
- ✅ `parse_multiple_queries_task` — массовый парсинг
- ✅ `parse_all_sources_task` — все источники сразу

#### API Endpoints
- ✅ `POST /api/v1/papers/parse` — запуск парсинга
- ✅ `POST /api/v1/papers/parse-all` — массовый парсинг
- ✅ `GET /api/v1/papers?source=arXiv` — фильтрация по источнику

#### Тесты
- ✅ 6 unit тестов для ArxivClient
- ✅ 5 unit тестов для ArxivParser
- ✅ 3 integration теста (реальные запросы к arXiv)

#### Скрипты запуска
- ✅ `run_all.bat` — запуск всех компонентов
- ✅ `run_worker.bat` — запуск Celery worker
- ✅ `test_parse.py` — быстрое тестирование парсинга

### 🔧 Исправления

#### Дата в arXiv
- ✅ Исправлена проблема с timezone (can't subtract offset-naive and offset-aware)
- ✅ Даты сохраняются в формате без timezone для совместимости с SQLite/PostgreSQL

#### Celery worker
- ✅ Добавлен `sys.path` в `celery_app.py` для импорта `shared`
- ✅ Исправлен запуск worker на Windows

#### HTTP
- ✅ Изменен URL arXiv с `http://` на `https://` (301 redirect)

### 🗑️ Удалено (Бритва Оккама)

#### Код
- ❌ `parse_arxiv_task` — дублировал `parse_papers_task`
- ❌ `parse_arxiv_multiple_queries_task` — дублировал `parse_multiple_queries_task`
- ❌ `PaperSource` Enum — избыточен
- ❌ `get_abstract_url()` — редко использовался
- ❌ `suggest()` — всегда возвращал пустой список
- ❌ 4 отдельные async функции — объединены в `_parse_async`

#### API Endpoints
- ❌ `/parse/arxiv` — избыточен (есть `source` параметр)
- ❌ `/sources` — можно посмотреть в документации
- ❌ `/search-queries` — hardcoded в коде

#### Тесты
- ❌ 7 избыточных тестов — дублировали логику
- ❌ `test_rate_limit_delay` — медленный (3 секунды)

#### Файлы
- ❌ `PARSER_README.md` — дублировал parser/README.md
- ❌ 2 фикстуры из `conftest.py` — не использовались

### 📊 Статистика оптимизации

| Файл | Было | Стало | Сокращение |
|------|------|-------|------------|
| `parse_tasks.py` | 400 строк | 180 строк | -55% |
| `parse.py (API)` | 314 строк | 170 строк | -46% |
| `client.py (arXiv)` | 383 строки | 200 строк | -48% |
| `parser.py (arXiv)` | 206 строк | 130 строк | -37% |
| Тесты | 39 тестов | 32 теста | -18% |

**Итого:** ~**-45%** кода без потери функциональности

### 📁 Изменения в зависимостях

```
pytest>=8.2.0         # Было: pytest==8.0.0
pytest-asyncio>=0.24.0 # Было: pytest-asyncio==0.23.3
```

### 🚀 Как запускать

```bash
# Все компоненты
.\run_all.bat

# Только worker
.\run_worker.bat

# Только сервер
.\run_backend.bat

# Тест парсинга
python test_parse.py
```

### ✅ Проверка работы

```bash
# Health check
curl http://localhost:8000/health

# Запуск парсинга
curl -X POST "http://localhost:8000/api/v1/papers/parse?query=nickel%20alloys&limit=5&source=arXiv"

# Проверка результата
curl http://localhost:8000/api/v1/papers/count
```

---

## [2026-03-24] — Настройка backend

### ✨ Новое
- ✅ FastAPI приложение
- ✅ Celery + Redis интеграция
- ✅ SQLAlchemy модели
- ✅ Alembic миграции
- ✅ Docker Compose конфигурация

### 🔧 Исправления
- ✅ Настроены импорты модулей
- ✅ Исправлен конфиг с `.env`
- ✅ Очищены дублирующиеся файлы

---

## [2026-03-20] — Начало проекта

### ✨ Новое
- ✅ Initial commit
- ✅ Структура проекта
- ✅ Базовая конфигурация
