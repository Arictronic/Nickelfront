# Парсер научных статей

Модуль для парсинга научных статей из открытых источников (arXiv, CORE).

## Источники

| Источник | API | Статус |
|----------|-----|--------|
| arXiv | https://arxiv.org/help/api | ✅ |
| CORE | https://core.ac.uk/services/api | ✅ |

## Быстрый старт

### Парсинг через API

```bash
# Запустить парсинг из arXiv
curl -X POST "http://localhost:8000/api/v1/papers/parse?query=nickel-based%20alloys&limit=10&source=arXiv"

# Запустить массовый парсинг
curl -X POST "http://localhost:8000/api/v1/papers/parse-all?limit_per_query=10&source=all"
```

### Программное использование

```python
from parser.arxiv import ArxivClient, ArxivParser

async def parse():
    client = ArxivClient(rate_limit=True)
    parser = ArxivParser()

    results = await client.search(query="nickel alloys", limit=10)
    papers = await parser.parse_search_results(results)

    for paper in papers:
        print(f"{paper.title} - {paper.authors}")

    await client.close()
```

## API Endpoints

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/papers` | Список статей |
| GET | `/api/v1/papers/count` | Количество статей |
| POST | `/api/v1/papers/search` | Поиск в БД |
| POST | `/api/v1/papers/parse` | Запустить парсинг |
| POST | `/api/v1/papers/parse-all` | Массовый парсинг |

## Поисковые запросы (arXiv)

```python
ARXIV_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys",
    "Ni-based superalloys",
    "inconel",
    "hastelloy",
]
```

## Категории arXiv

```python
ARXIV_CATEGORIES = [
    "cond-mat.mtrl-sci",    # Materials Science
    "physics.chem-ph",      # Chemical Physics
    "physics.app-ph",       # Applied Physics
]
```

## Тесты

```bash
# Unit тесты
pytest tests/unit/parser/test_arxiv_*.py -v

# Integration тесты
pytest tests/integration/test_arxiv_client.py -v
```

## Добавление нового источника

1. Создайте `parser/<source>/client.py` и `parser.py`
2. Реализуйте `BaseAPIClient` и `BaseParser`
3. Обновите `parser/__init__.py`

## Структура

```
parser/
├── base/               # Базовые классы
│   ├── base_client.py  # Базовый класс для API клиентов
│   └── base_parser.py  # Базовый класс для парсеров
├── core/               # CORE API парсер
│   ├── client.py
│   └── parser.py
├── arxiv/              # arXiv API парсер
│   ├── client.py
│   └── parser.py
└── __init__.py
```
