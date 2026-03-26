# Nickelfront

Не могу запустить проект

Запуск всего проекта (бэк+воркер+фронт)
Сейчас я не могу запустить бэк “как в проекте”, потому что на машине не доступны локальные сервисы:

PostgreSQL на 127.0.0.1:5432 не отвечает
Redis на 127.0.0.1:6379 не отвечает
и команда docker в окружении не найдена (поэтому run_all.bat/docker-compose поднять не получается).
Если у вас запущены PostgreSQL+Redis локально (или доступен docker), после этого бэк поднимется как обычно.


Платформа для парсинга и анализа научных статей по материаловедению (никелевые сплавы, жаропрочные сплавы, суперсплавы).

## 📋 О проекте

Проект предназначен для:
- Парсинга научных статей из открытых источников (arXiv, CORE)
- Сохранения и каталогизации статей в базе данных
- Анализа данных с помощью ML (в разработке)
- Визуализации и отчетности (в разработке)

## 🚀 Быстрый старт

### Требования
- Python 3.12+
- Docker с Redis и PostgreSQL
- Node.js (для фронтенда)

### Запуск бэкенда

```bash
# Из корня проекта
cd Nickelfront

# Запуск всех компонентов (Redis, PostgreSQL, Backend, Worker)
docker-compose up -d

# Или локально (Windows)
.\run_all.bat
```

### Проверка работы

```bash
# Health check
curl http://localhost:8000/health

# Swagger UI
# http://localhost:8000/docs
```

### Запуск парсинга

```bash
# Парсинг из arXiv
curl -X POST "http://localhost:8000/api/v1/papers/parse?query=nickel%20alloys&limit=5&source=arXiv"

# Массовый парсинг
curl -X POST "http://localhost:8000/api/v1/papers/parse-all?limit_per_query=5&source=all"

# Проверка результата
curl http://localhost:8000/api/v1/papers/count
```

## 📁 Структура проекта

```
Nickelfront/
├── backend/              # Бэкенд на FastAPI + Celery
│   ├── app/
│   │   ├── api/          # REST API endpoints
│   │   ├── core/         # Конфигурация, логирование
│   │   ├── db/           # SQLAlchemy модели, миграции
│   │   ├── services/     # Бизнес-логика
│   │   └── tasks/        # Celery задачи
│   ├── alembic/          # Миграции БД
│   └── tests/            # Тесты
│
├── parser/               # Парсер научных статей
│   ├── base/             # Базовые классы
│   ├── core/             # CORE API парсер
│   └── arxiv/            # arXiv API парсер
│
├── frontend/             # Фронтенд на React + Vite
│   └── src/
│
├── ml/                   # Машинное обучение
│   ├── models/           # Обученные модели
│   └── training/         # Скрипты обучения
│
├── analytics/            # Аналитика и отчёты
├── tests/                # Общие тесты
└── shared/               # Общие модули (schemas, utils)
```

## 🔌 API Endpoints

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
# Получить все статьи
curl http://localhost:8000/api/v1/papers?limit=10

# Поиск
curl -X POST "http://localhost:8000/api/v1/papers/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "superalloys", "limit": 20}'

# Запустить парсинг arXiv
curl -X POST "http://localhost:8000/api/v1/papers/parse?query=nickel%20alloys&limit=5&source=arXiv"
```

## 📊 Источники данных

### arXiv (arxiv.org)
- **Статус**: ✅ Реализовано
- **API**: https://arxiv.org/help/api
- **Тематика**: Препринты по материаловедению, физике, CS
- **Категории**: cond-mat.mtrl-sci, physics.chem-ph, physics.app-ph

### CORE (core.ac.uk)
- **Статус**: ✅ Реализовано
- **API**: https://core.ac.uk/services/api
- **Тематика**: Open Access научные статьи

## 🧪 Тесты

```bash
# Все тесты
pytest tests/ -v

# Тесты парсеров
pytest tests/unit/parser/ -v

# Integration тесты
pytest tests/integration/ -v
```

## 🔧 Разработка

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Парсер (тестирование)

```bash
# Быстрый тест arXiv парсинга
python test_parse.py
```

## 📈 Roadmap

- [x] Парсер arXiv API
- [x] Парсер CORE API
- [x] Интеграция с Celery
- [x] REST API для управления статьями
- [ ] Парсер ScienceDirect (Selenium)
- [ ] Парсер ResearchGate
- [ ] ML анализ статей (NER, классификация)
- [ ] Дашборд аналитики
- [ ] Экспорт результатов

## 👥 Команда

| Участник | Роль | Модули |
|----------|------|--------|
| Ваня | Backend, парсеры | `backend/app/api/`, `parser/` |
| Артем | БД | `backend/app/db/`, `alembic/` |
| Тамерлан | Frontend, тесты | `frontend/`, `tests/` |
| Паша | ML, аналитика | `ml/`, `analytics/` |

## 📄 Лицензия

Проект создан в рамках учебного практикума.

## 📞 Контакты

По вопросам обращайтесь к участникам проекта.
