# RAG-система для анализа патентов на суперсплавы

Система Retrieval-Augmented Generation (RAG) для работы с патентными документами в области суперсплавов.

## Возможности

- **Загрузка патентов** — загрузка PDF файлов и автоматическое извлечение текста
- **Векторный поиск** — семантический поиск по базе патентов
- **Ответы на вопросы** — генерация ответов на основе содержимого патентов
- **Источники** — указание документов, на которых основан ответ

## Технологический стек

- **FastAPI** — REST API сервер
- **LangChain** — фреймворк для RAG
- **ChromaDB** — векторная база данных
- **sentence-transformers** — эмбеддинги (all-MiniLM-L6-v2)
- **pdfplumber** — извлечение текста из PDF
- **Selenium** — веб-парсинг (заготовка)

## Требования

- Python 3.12+
- 4 ГБ ОЗУ (минимум)
- Chromium (для веб-парсинга)

## Установка

1. **Создайте виртуальное окружение:**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # Linux/Mac
   ```

2. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Настройте переменные окружения:**
   ```bash
   cp .env.example .env
   ```
   
   Отредактируйте `.env` и укажите:
   - `LLM_API_KEY` — ваш API ключ для LLM
   - `LLM_API_BASE_URL` — URL API (по умолчанию OpenAI)
   - Другие параметры при необходимости

## Запуск

### Через CLI:
```bash
cd rag
python -m app.main
```

### Через uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Сервер запустится на `http://localhost:8000`

## API Документация

После запуска сервера доступна интерактивная документация:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## Основные эндпоинты

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/api/v1/health` | Проверка статуса приложения |
| POST | `/api/v1/ask` | Задать вопрос по патентам |
| POST | `/api/v1/upload` | Загрузить PDF патента |
| GET | `/api/v1/stats` | Статистика системы |
| GET | `/api/v1/models` | Информация о моделях |
| POST | `/api/v1/clear` | Очистить векторное хранилище |

## Примеры использования

### Загрузка патента (curl):
```bash
curl -X POST "http://localhost:8000/api/v1/upload" \
  -F "file=@patent.pdf"
```

### Вопрос к системе:
```bash
curl -X POST "http://localhost:8000/api/v1/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Какой состав у сплава ХН77ТЮР?", "include_sources": true}'
```

### На Python:
```python
import requests

# Загрузка файла
with open("patent.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/upload",
        files={"file": f}
    )
    print(response.json())

# Вопрос
response = requests.post(
    "http://localhost:8000/api/v1/ask",
    json={"question": "Что такое суперсплавы?"}
)
print(response.json()["answer"])
```

## Структура проекта

```
rag/
├── app/
│   ├── __init__.py
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py            # Настройки приложения
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py        # Эндпоинты API
│   │   └── schemas.py       # Pydantic модели
│   ├── core/
│   │   ├── __init__.py
│   │   ├── embeddings.py    # Эмбеддинги
│   │   ├── vector_store.py  # ChromaDB
│   │   └── rag_chain.py     # RAG-цепь
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py   # LLM API
│   │   └── parser_service.py # Парсер PDF/Selenium
│   └── utils/
│       ├── __init__.py
│       └── helpers.py       # Утилиты
├── data/
│   ├── .gitignore
│   ├── db/                  # Векторная база данных
│   └── uploads/             # Загруженные файлы
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_config.py
│   ├── test_parser.py
│   └── test_vector_store.py
├── requirements.txt
├── .env.example
└── README.md
```

## Тестирование

Запуск тестов:
```bash
pytest tests/ -v
```

Запуск с покрытием:
```bash
pytest tests/ -v --cov=app
```

## Ограничения

- **Память:** ~4 ГБ RAM (используются легковесные модели)
- **Файлы:** только PDF, макс. 50 МБ
- **Эмбеддинги:** all-MiniLM-L6-v2 (384 измерения)
- **LLM:** внешний API (не локально)

## Настройка LLM

По умолчанию используется OpenAI-compatible API. Для смены провайдера:

```env
LLM_API_KEY=your_key
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-3.5-turbo
```

Поддерживаются любые совместимые API (LocalAI, vLLM, etc.).

## Лицензия

MIT
