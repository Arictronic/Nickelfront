# Аналитический пайплайн Nickelfront

## Что сделано

### Схема работы

```
Парсер → Paper + PaperContentPart (БД)
                    ↓
    AnalysisPipelineService.build_context()
                    ↓
    Метаданные (title, authors, journal, ...) + конкатенированные чанки
                    ↓
    Промпт = system_prompt + metadata + текст + output_schema
                    ↓
    QwenServiceClient.send_message() → JSON-ответ
                    ↓
    AnalysisResult (таблица analysis_results)
                    ↓
    Экспорт .xlsx (только по запросу пользователя)
```

### Созданные файлы

| Файл | Назначение |
|------|-----------|
| `backend/app/core/analysis_prompts.py` | Константы `ANALYSIS_SYSTEM_PROMPT` и `ANALYSIS_OUTPUT_SCHEMA` |
| `backend/app/db/models/analysis_result.py` | Модель `AnalysisResult` (SQLAlchemy) |
| `backend/alembic/versions/017_add_analysis_results.py` | Миграция БД |
| `backend/app/services/analysis_pipeline.py` | `AnalysisPipelineService` — сбор контекста → вызов Qwen → парсинг → запись |
| `backend/app/services/analysis_export.py` | Экспорт `.xlsx` через openpyxl |
| `backend/app/api/v1/endpoints/analysis.py` | 4 эндпоинта (см. ниже) |

### Эндпоинты API

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analysis/{paper_id}/context` | Посмотреть сформированный контекст |
| `POST` | `/api/v1/analysis/{paper_id}/run` | Запустить анализ |
| `GET` | `/api/v1/analysis/results` | Список результатов текущего пользователя |
| `GET` | `/api/v1/analysis/{analysis_id}/export` | Скачать `.xlsx` |

### Модель `AnalysisResult`

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer PK | Автоинкремент |
| `paper_id` | FK → papers | Статья |
| `user_id` | FK → users (nullable) | Кто запустил |
| `status` | String | `pending → running → completed/failed` |
| `prompt_version` | String | Версия промпта (для итераций) |
| `context_preview` | Text | Первые 500 символов контекста |
| `raw_response` | Text (nullable) | Сырой ответ Qwen |
| `structured_result` | JSONB (nullable) | Распарсенный JSON |
| `error_message` | Text (nullable) | Текст ошибки |
| `created_at / updated_at / completed_at` | DateTime | Таймстемпы |

---

## Что нужно сделать другим

### 1. ML-специалисту — заменить промпт и схему

Файл: `backend/app/core/analysis_prompts.py`

```python
ANALYSIS_SYSTEM_PROMPT = """..."""  # Ваш промпт
ANALYSIS_OUTPUT_SCHEMA = """..."""  # Ваша JSON-schema
```

Сейчас там заглушки. Промпт и схема живут в отдельном файле — менять можно без правок остального кода.

### 2. ML-специалисту — подключить RAG (по желанию)

Сейчас контекст строится простой конкатенацией всех `PaperContentPart.markdown_text` (fallback `raw_text` → `Paper.full_text`). Если нужен RAG:

- Модифицировать `AnalysisPipelineService._build_context()` — после загрузки чанков выполнить векторный поиск по `ChromaDB` через `VectorService` или `RagVectorStore`, дополнить/заменить контекст релевантными фрагментами.
- ✅ Существующий код не сломается — интерфейс метода (возвращает `dict` с `metadata` и `content`) останется тем же.

### 3. ML-специалисту — сделать анализ асинхронным (по желанию)

Сейчас `QwenServiceClient.send_message()` вызывается синхронно внутри async-эндпоинта — блокирует event loop на время ответа Qwen (10-60 сек). Если станет проблемой для production:

- Обернуть через `asyncio.to_thread()` в `run_analysis()`
- Или запускать через Celery-таск (потребуется сохранять `analysis_results.id` и обновлять статус по завершении)
- ✅ `status` (pending → running → completed/failed) и `completed_at` уже предусмотрены в модели

### 4. Frontend-разработчику — UI для анализа

API готов, но UI пока не реализован. Ориентировочная схема:

1. На странице статьи кнопка **«Анализировать»** — `POST /api/v1/analysis/{paper_id}/run`
2. Получить `id` анализа, можно показать спиннер
3. `GET /api/v1/analysis/results` — список всех анализов пользователя
4. Кнопка **«Скачать Excel»** — `GET /api/v1/analysis/{analysis_id}/export`

Пока нет бэкенд-задачи (Celery), ответ может приходить до ~60 секунд. На фронте нужен таймаут побольше или long-polling, если в будущем добавят асинхронность.

### 5. Применить миграцию

```bash
python backend/apply_migrations.py
```
