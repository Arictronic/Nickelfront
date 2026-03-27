# Архитектура платформы Nickelfront

**Версия:** 1.0.0  
**Дата:** Март 2026

---

## 📋 Оглавление

1. [Описание проекта](#описание-проекта)
2. [Стек разработки](#стек-разработки)
3. [Архитектурная схема](#архитектурная-схема)
4. [Структура проекта](#структура-проекта)
5. [Основные связи компонентов](#основные-связи-компонентов)
6. [API Endpoints](#api-endpoints)
7. [Модели данных](#модели-данных)
8. [Схема данных](#схема-данных)
9. [Поток данных](#поток-данных)
10. [Детальное описание сервисов](#детальное-описание-сервисов)
11. [Парсеры](#парсеры)
12. [Система безопасности](#система-безопасности)
13. [Frontend архитектура](#frontend-архитектура)
14. [Конфигурация и переменные окружения](#конфигурация-и-переменные-окружения)
15. [Логирование и мониторинг](#логирование-и-мониторинг)
16. [Тестирование](#тестирование)
17. [CI/CD](#cicd)
18. [Troubleshooting](#troubleshooting)

---

## 📖 Описание проекта

**Nickelfront** — это полнофункциональная платформа для парсинга и анализа научных статей и патентов в области материаловедения (никелевые сплавы, жаропрочные сплавы, суперсплавы).

### Основные возможности

| Функция | Описание |
|---------|----------|
| 📥 Парсинг | Автоматический сбор статей из arXiv, CORE, ScienceDirect, ResearchGate |
| 🔍 Поиск | Полнотекстовый (PostgreSQL FTS) и векторный поиск (ChromaDB) |
| 📊 Аналитика | Метрики статей, патентов, качества данных |
| 📑 Отчёты | Генерация отчётов в PDF/DOCX формате |
| 📈 Мониторинг | Отслеживание Celery задач через Flower |
| 🔐 Авторизация | JWT аутентификация пользователей |

---

## 🛠️ Стек разработки

### Backend

| Компонент | Технология | Версия |
|-----------|------------|--------|
| Фреймворк | FastAPI | 0.109.0 |
| ORM | SQLAlchemy (async) | 2.0.25 |
| База данных | PostgreSQL | 15+ |
| Миграции | Alembic | 1.13.1 |
| Очередь задач | Celery | 5.3.6 |
| Брокер | Redis | 7+ |
| Векторный поиск | ChromaDB | 0.4.22+ |
| Эмбеддинги | sentence-transformers | 2.3.1+ |
| Безопасность | python-jose, passlib | 3.3.0, 1.7.4 |
| Валидация | Pydantic | 2.5.3 |
| Логирование | Loguru | 0.7.2 |

### Frontend

| Компонент | Технология | Версия |
|-----------|------------|--------|
| Фреймворк | React | 18.2.0 |
| Сборщик | Vite | 5.0.12 |
| Роутинг | React Router DOM | 6.21.0 |
| HTTP клиент | Axios | 1.6.5 |
| Графики | Recharts | 2.10.0 |
| State | Zustand | 4.5.0 |
| Типизация | TypeScript | - |

### Analytics

| Компонент | Технология | Версия |
|-----------|------------|--------|
| Обработка данных | Polars | 0.20.0+ |
| Анализ | Pandas, NumPy | 2.0.0+, 1.24.0+ |
| Отчёты | reportlab, python-docx | 4.0.0+, 1.0.0+ |

### Парсеры

| Источник | Тип | Технология |
|----------|-----|------------|
| arXiv | API | HTTP REST |
| CORE | API | HTTP REST |
| ScienceDirect | Selenium | WebDriver |
| ResearchGate | Spider | BeautifulSoup |
| Google Patents | API/Selenium | Mixed |
| Espacenet | API | HTTP REST |

---

## 🏗️ Архитектурная схема

```
┌───────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React 18)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │  Поиск   │ │  Статьи  │ │ Аналитика│ │  Отчёты  │ │ Задачи   │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP/REST API
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                             │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                      API Endpoints (v1)                         │  │
│  │  /auth  /papers  /vector  /search  /analytics  /reports  /tasks │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                    │                                  │
│  ┌─────────────────────────────────┼───────────────────────────────┐  │
│  │              Services Layer     ▼                               │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │
│  │  │  Paper   │ │  Vector  │ │Embedding │ │  User    │            │  │
│  │  │ Service  │ │ Service  │ │ Service  │ │ Service  │            │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │
│  │  │FullText  │ │  Report  │ │  Task    │ │Analytics │            │  │
│  │  │ Search   │ │ Service  │ │ Service  │ │ Service  │            │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                    │                                  │
│  ┌─────────────────────────────────┼───────────────────────────────┐  │
│  │              Data Access Layer  ▼                               │  │
│  │  ┌──────────────────────────────────────────────────────────┐   │  │
│  │  │                    SQLAlchemy ORM                        │   │  │
│  │  └──────────────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
           │                    │                    │
           │                    │                    │
           ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐
│   PostgreSQL    │  │   Redis         │  │   Celery Workers            │
│   (Основная БД) │  │   (Кэш/Брокер)  │  │   ┌─────────────────────┐   │
│  ┌───────────┐  │  └─────────────────┘  │   │  parse_tasks.py     │   │
│  │ papers    │  │                       │   │  - parse_papers     │   │
│  │ users     │  │  ┌─────────────────┐  │   │  - parse_all        │   │
│  │ tasks     │  │  │   ChromaDB      │  │   │                     │   │
│  └───────────┘  │  │(Векторный поиск)│  │   └─────────────────────┘   │
└─────────────────┘  └─────────────────┘  └─────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   External APIs     │
                    │  ┌───────────────┐  │
                    │  │ arXiv API     │  │
                    │  │ CORE API      │  │
                    │  │ ScienceDirect │  │
                    │  │ ResearchGate  │  │
                    │  │ Google Patents│  │
                    │  └───────────────┘  │
                    └─────────────────────┘
```

---

## 📁 Структура проекта

```
Nickelfront/
├── backend/                    # FastAPI + Celery + SQLAlchemy
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── endpoints/
│   │   │       │   ├── auth.py         # Авторизация (JWT)
│   │   │       │   ├── papers.py       # CRUD статей
│   │   │       │   ├── parse.py        # Запуск парсеров
│   │   │       │   ├── vector.py       # Векторный поиск
│   │   │       │   ├── search.py       # Полнотекстовый поиск
│   │   │       │   ├── analytics.py    # Метрики и статистика
│   │   │       │   ├── reports.py      # Экспорт отчётов
│   │   │       │   ├── tasks.py        # Мониторинг задач
│   │   │       │   └── monitoring.py   # Health checks
│   │   │       └── deps.py             # Зависимости (auth)
│   │   │
│   │   ├── core/
│   │   │   ├── config.py               # Настройки приложения
│   │   │   ├── security.py             # JWT, password hashing
│   │   │   └── logging.py              # Настройка логирования
│   │   │
│   │   ├── db/
│   │   │   ├── models/
│   │   │   │   ├── paper.py            # Модель статьи
│   │   │   │   ├── user.py             # Модель пользователя
│   │   │   │   └── task.py             # Модель задачи
│   │   │   ├── base.py                 # Базовый класс ORM (DeclarativeBase)
│   │   │   ├── session.py              # AsyncSession factory
│   │   │   └── init_db.py              # Инициализация БД
│   │   │
│   │   ├── services/
│   │   │   ├── paper_service.py        # Логика работы со статьями
│   │   │   ├── user_service.py         # Логика работы с пользователями
│   │   │   ├── embedding_service.py    # Генерация эмбеддингов
│   │   │   ├── vector_service.py       # Векторный поиск (ChromaDB)
│   │   │   ├── fulltext_search_service.py  # FTS (PostgreSQL)
│   │   │   ├── report_service.py       # Генерация отчётов
│   │   │   └── task_service.py         # Управление задачами
│   │   │
│   │   ├── tasks/
│   │   │   ├── celery_app.py           # Конфигурация Celery + Beat
│   │   │   ├── parse_tasks.py          # Задачи парсинга
│   │   │   └── tasks.py                # Фоновые задачи
│   │   │
│   │   └── main.py                     # Точка входа FastAPI
│   │
│   ├── alembic/                        # Миграции БД
│   │   └── versions/
│   │       ├── 001_initial.py          # Таблица papers
│   │       ├── 002_users.py            # Таблица users
│   │       ├── 003_add_embedding.py    # Добавление embedding
│   │       └── 004_add_fulltext_search.py  # FTS + триггеры
│   ├── tests/                          # Тесты backend
│   └── requirements.txt                # Зависимости Python
│
├── frontend/                   # React 18 + Vite + TypeScript
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts       # axios instance
│   │   │   ├── auth.ts         # Auth API
│   │   │   ├── papers.ts       # Papers API (papers, vector, search)
│   │   │   └── patents.ts      # Patents API
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Layout.tsx  # Основной layout
│   │   │   │   ├── Header.tsx  # Шапка
│   │   │   │   ├── Sidebar.tsx # Боковое меню
│   │   │   │   └── Footer.tsx  # Подвал
│   │   │   └── ui/             # UI компоненты (Toast, etc.)
│   │   ├── context/
│   │   │   └── ThemeProvider.tsx  # Темизация
│   │   ├── hooks/              # Кастомные хуки
│   │   ├── pages/
│   │   │   ├── Landing.tsx     # Главная страница
│   │   │   ├── Dashboard.tsx   # Дашборд с метриками
│   │   │   ├── Patents.tsx     # Список статей
│   │   │   ├── PatentDetail.tsx # Детали статьи
│   │   │   ├── PaperReport.tsx # Отчёт по статье
│   │   │   ├── Analytics.tsx   # Векторный поиск
│   │   │   ├── Metrics.tsx     # Метрики
│   │   │   ├── FullTextSearch.tsx  # FTS поиск
│   │   │   ├── CeleryMonitoring.tsx  # Мониторинг Celery
│   │   │   ├── WorkerStatus.tsx    # Статус воркеров
│   │   │   ├── Database.tsx        # Управление БД
│   │   │   ├── Login.tsx           # Вход
│   │   │   └── Register.tsx        # Регистрация
│   │   ├── store/
│   │   │   └── authStore.ts    # Zustand auth store
│   │   ├── types/
│   │   │   ├── paper.ts        # TypeScript типы статей
│   │   │   └── user.ts         # TypeScript типы пользователя
│   │   ├── utils/              # Утилиты
│   │   ├── App.tsx             # Роутинг
│   │   └── main.tsx            # Точка входа
│   ├── package.json
│   └── vite.config.js
│
├── analytics/                  # Модуль аналитики
│   ├── metrics/
│   │   ├── paper_metrics.py    # Метрики статей
│   │   └── patent_metrics.py   # Метрики патентов
│   ├── reports/
│   │   └── report_generator.py # Генерация отчётов
│   ├── validation/
│   │   └── data_validator.py   # Валидация данных
│   └── __init__.py
│
├── parsers_pkg/                # Парсеры статей
│   ├── base/
│   │   ├── base_parser.py      # Базовый парсер
│   │   ├── base_client.py      # Базовый API клиент
│   │   └── deduplicator.py     # Дедупликация
│   ├── pipelines/
│   │   └── data_pipeline.py    # ETL конвейер
│   ├── arxiv/
│   │   ├── client.py           # arXiv API клиент
│   │   └── parser.py           # arXiv парсер
│   ├── core/
│   │   ├── client.py           # CORE API клиент
│   │   └── parser.py           # CORE парсер
│   ├── selenium/               # Selenium парсеры
│   ├── spiders/                # Spider парсеры
│   └── patents/                # Парсеры патентов
│
├── shared/                     # Общие модули
│   └── schemas/
│       ├── paper.py            # Pydantic схемы статей
│       ├── task.py             # Pydantic схемы задач
│       └── auth.py             # Pydantic схемы авторизации
│
├── docs/                       # Документация
├── report/                     # Сгенерированные отчёты
├── ml/                         # ML модели
├── chroma_db/                  # ChromaDB персистентное хранилище
├── logs/                       # Логи приложения
└── .env.example                # Переменные окружения
```

---

## 🔗 Основные связи компонентов

### 1. Поток запроса пользователя

```
User → Frontend → API Gateway → Service Layer → Data Layer → Database
                     │
                     └→ Celery Task → Worker → External API
```

### 2. Парсинг статей

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  API Request│ ──▶ │  Parse Task │ ──▶ │   Parser    │
│  /api/v1/   │     │   (Celery)  │     │  (arXiv/    │
│  papers/parse│    │             │     │   CORE)     │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Database  │ ◀── │   Service   │ ◀── │   Pipeline  │
│  (PostgreSQL)│    │  (Paper)    │     │  (ETL)      │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 3. Векторный поиск

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Search     │ ──▶ │  Embedding  │ ──▶ │  ChromaDB   │
│  Query      │     │  Service    │     │  (Vector)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Response  │ ◀── │   Paper     │ ◀── │  Similarity │
│   (JSON)    │     │   Service   │     │  Search     │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 4. Генерация отчёта

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  API Request│ ──▶ │  Report     │ ──▶ │  Analytics  │
│  /reports/  │     │  Service    │     │  Module     │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   PDF/DOCX  │ ◀── │  Template   │ ◀── │   Metrics   │
│   Export    │     │  Engine     │     │  Calculator │
└─────────────┘     └─────────────┘     └─────────────┘
```

---

## 🌐 API Endpoints

### Auth (Авторизация)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/auth/register` | Регистрация пользователя |
| POST | `/api/v1/auth/login` | Вход (JWT токен) |
| POST | `/api/v1/auth/logout` | Выход из системы |
| GET | `/api/v1/auth/me` | Данные текущего пользователя |

### Papers (Статьи)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/papers` | Список всех статей |
| GET | `/api/v1/papers/{id}` | Статья по ID |
| POST | `/api/v1/papers/search` | Поиск статей |
| POST | `/api/v1/papers/parse` | Запуск парсинга |
| POST | `/api/v1/papers/parse-all` | Массовый парсинг |
| DELETE | `/api/v1/papers/{id}` | Удаление статьи |
| GET | `/api/v1/papers/count` | Количество статей |

### Vector Search (Векторный поиск)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/vector/search` | Векторный поиск |
| GET | `/api/v1/vector/stats` | Статистика векторного поиска |
| POST | `/api/v1/vector/rebuild` | Перестройка индекса |

### Search (Полнотекстовый поиск)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/v1/search/fulltext` | FTS поиск |
| GET | `/api/v1/search/suggest` | Автодополнение |
| POST | `/api/v1/search/keywords` | Поиск по ключевым словам |
| GET | `/api/v1/search/stats` | Статистика поиска |
| GET | `/api/v1/search/highlight/{id}` | Подсветка совпадений |

### Analytics (Аналитика)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/analytics/metrics/summary` | Сводная статистика |
| GET | `/api/v1/analytics/metrics/trend` | Тренд публикаций |
| GET | `/api/v1/analytics/metrics/top` | Топ элементов |
| GET | `/api/v1/analytics/metrics/source-distribution` | Распределение по источникам |
| GET | `/api/v1/analytics/metrics/quality-report` | Отчёт о качестве |

### Reports (Отчёты)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/reports/paper/{id}/pdf` | Экспорт в PDF |
| GET | `/api/v1/reports/paper/{id}/docx` | Экспорт в DOCX |
| GET | `/api/v1/reports/paper/{id}` | Отчёт в JSON |

### Tasks (Задачи)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/tasks` | Список задач |
| GET | `/api/v1/tasks/{id}` | Задача по ID |
| GET | `/api/v1/tasks/{id}/status` | Статус задачи |

### Monitoring (Мониторинг)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/v1/monitoring/health` | Health check |
| GET | `/api/v1/monitoring/celery` | Статус Celery |
| GET | `/health` | Общий health check |

---

## 📊 Модели данных

### Paper (Статья)

```python
class Paper(Base):
    id: int                      # Primary key
    title: str                   # Название
    authors: List[str]           # Авторы (JSON)
    publication_date: datetime   # Дата публикации
    journal: str                 # Журнал
    doi: str                     # DOI (unique)
    abstract: str                # Аннотация
    full_text: str               # Полный текст
    keywords: List[str]          # Ключевые слова (JSON)
    embedding: List[float]       # Векторный эмбеддинг (JSON)
    search_vector: TSVECTOR      # FTS вектор
    source: str                  # Источник (CORE, arXiv)
    source_id: str               # ID в источнике
    url: str                     # URL
    created_at: datetime         # Дата создания
    updated_at: datetime         # Дата обновления
```

### User (Пользователь)

```python
class User(Base):
    id: int                      # Primary key
    email: str                   # Email (unique)
    username: str                # Имя пользователя
    password_hash: str           # Хеш пароля
    is_active: bool              # Активен ли
    is_verified: bool            # Подтверждён ли
    created_at: datetime         # Дата регистрации
    last_login_at: datetime      # Последний вход
```

### PatentTask (Задача обработки патента)

```python
class PatentTask(Base):
    id: int                      # Primary key
    patent_number: str           # Номер патента
    status: str                  # pending/processing/completed/failed
    input_data: dict             # Входные данные (JSON)
    result: dict                 # Результат (JSON)
    created_at: datetime         # Дата создания
    updated_at: datetime         # Дата обновления
```

---

## 🗄️ Схема данных

### Миграции Alembic

| Миграция | Описание |
|----------|----------|
| `001_initial` | Создание таблицы papers |
| `002_users` | Создание таблицы users |
| `003_add_embedding` | Добавление колонки embedding (JSON) |
| `004_add_fulltext_search` | FTS: search_vector, GIN индексы, триггеры |

### Таблицы базы данных

```sql
-- papers: Научные статьи
CREATE TABLE papers (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    authors JSONB,
    publication_date TIMESTAMP,
    journal VARCHAR(500),
    doi VARCHAR(200) UNIQUE,
    abstract TEXT,
    full_text TEXT,
    keywords JSONB,
    embedding JSONB,                    -- Векторный эмбеддинг (384 float)
    search_vector TSVECTOR,             -- FTS вектор
    source VARCHAR(50) NOT NULL,
    source_id VARCHAR(200),
    url VARCHAR(1000),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

-- Индексы
CREATE INDEX ix_papers_id ON papers(id);
CREATE INDEX ix_papers_title ON papers(title);
CREATE INDEX ix_papers_publication_date ON papers(publication_date);
CREATE INDEX ix_papers_doi ON papers(doi);
CREATE INDEX ix_papers_source ON papers(source);
CREATE INDEX ix_papers_source_id ON papers(source_id);
CREATE INDEX ix_papers_search_vector ON papers USING GIN(search_vector);  -- FTS
CREATE INDEX ix_papers_title_trgm ON papers USING GIN(title gin_trgm_ops); -- Trigram

-- users: Пользователи
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100),
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    last_login_at TIMESTAMP
);

-- patent_tasks: Задачи обработки патентов
CREATE TABLE patent_tasks (
    id SERIAL PRIMARY KEY,
    patent_number VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'pending',
    input_data JSONB,
    result JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
```

### FTS Триггер

```sql
-- Автоматическое обновление search_vector при INSERT/UPDATE
CREATE FUNCTION papers_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.abstract, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(array_to_string(NEW.keywords, ' '), '')), 'C');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER papers_search_vector_trigger
    BEFORE INSERT OR UPDATE ON papers
    FOR EACH ROW
    EXECUTE FUNCTION papers_search_vector_update();
```

### ChromaDB Коллекция

```
Collection: papers
├── id: paper_{id}
├── embedding: vector[384] (нормализованный)
└── metadata:
    ├── paper_id: int
    ├── title: str
    ├── source: str (CORE, arXiv)
    ├── doi: str (optional)
    ├── publication_date: str (YYYY-MM-DD)
    └── journal: str (optional)
```

---

## 🔄 Поток данных

### 1. Добавление статьи через парсинг

```
1. Пользователь → POST /api/v1/papers/parse
2. API → Создаёт Celery задачу
3. Worker → Выполняет парсинг (arXiv/CORE API)
4. Parser → Возвращает сырые данные
5. Pipeline → Очистка, валидация, дедупликация
6. Embedding Service → Генерация вектора
7. Paper Service → Сохранение в PostgreSQL
8. Vector Service → Добавление в ChromaDB
9. Task Service → Обновление статуса задачи
```

### 2. Поиск статьи

```
1. Пользователь → POST /api/v1/vector/search
2. Embedding Service → Генерация эмбеддинга запроса
3. Vector Service → Поиск ближайших соседей в ChromaDB
4. Paper Service → Получение полных данных из БД
5. API → Возврат результатов с similarity score
```

### 3. Генерация аналитики

```
1. Пользователь → GET /api/v1/analytics/metrics/summary
2. Analytics Module → Запрос данных из БД
3. PaperMetricsService → Вычисление метрик
4. ReportGenerator → Формирование отчёта
5. API → Возврат JSON с метриками
```

---

## 📈 Диаграмма последовательности (Парсинг)

```
User          API            Celery         Parser        DB           ChromaDB
 │             │               │              │            │               │
 │──Parse Req─▶│               │              │            │               │
 │             │──Create Task▶│              │            │               │
 │             │               │              │            │               │
 │             │               │──Execute───▶│            │               │
 │             │               │              │──Parse───▶│               │
 │             │               │              │            │               │
 │             │               │◀─Data───────│            │               │
 │             │               │              │            │               │
 │             │               │──Process───▶│            │               │
 │             │               │  (Pipeline)  │            │               │
 │             │               │              │            │               │
 │             │               │──Save──────▶│            │               │
 │             │               │              │            │               │
 │             │               │──Index─────▶│───────────▶│               │
 │             │               │              │            │               │
 │             │◀─Task Done───│              │            │               │
 │◀─Response───│               │              │            │               │
```

---

## 🔐 Безопасность

### JWT Аутентификация

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Login     │ ──▶ │   Verify    │ ──▶ │   Generate  │
│   Request   │     │   Password  │     │   JWT Token │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Response  │ ◀── │   Attach    │ ◀── │   Return    │
│   (Token)   │     │   to User   │     │   to Client │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Защищённые endpoints

| Endpoint | Требуется авторизация |
|----------|----------------------|
| `/api/v1/auth/*` | Нет (кроме `/me`) |
| `/api/v1/papers/*` | Нет |
| `/api/v1/vector/*` | Нет |
| `/api/v1/search/*` | Нет |
| `/api/v1/analytics/*` | Нет |
| `/api/v1/reports/*` | Нет |
| `/api/v1/tasks/*` | Нет |
| `/api/v1/auth/me` | **Да** |

---

## 🚀 Развёртывание

### Docker Compose

```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: nickelfront
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password

  redis:
    image: redis:7

  backend:
    build: ./backend
    depends_on: [postgres, redis]
    ports: ["8000:8000"]

  celery-worker:
    build: ./backend
    command: celery -A app.tasks.celery_app worker
    depends_on: [postgres, redis]

  frontend:
    build: ./frontend
    ports: ["5173:5173"]

  flower:
    build: ./backend
    command: celery -A app.tasks.celery_app flower
    ports: ["5555:5555"]
```

---

## 🔧 Детальное описание сервисов

### Paper Service

**Файл:** `backend/app/services/paper_service.py`

Сервис для управления научными статьями.

| Метод | Описание |
|-------|----------|
| `create_paper()` | Создать статью (с проверкой на дубликаты) |
| `get_by_id()` | Получить статью по ID |
| `get_by_doi()` | Получить статью по DOI |
| `get_by_source_id()` | Получить статью по ID в источнике |
| `search()` | Поиск по названию и аннотации |
| `get_all()` | Получить список всех статей |
| `get_total_count()` | Получить общее количество статей |
| `update_paper()` | Обновить статью |
| `delete_paper()` | Удалить статью |

### Embedding Service

**Файл:** `backend/app/services/embedding_service.py`

Сервис генерации векторных эмбеддингов.

```python
class EmbeddingService:
    MODEL_NAME = "all-MiniLM-L6-v2"  # 384 измерения
    EMBEDDING_DIM = 384
    
    def get_embedding(text: str) -> list[float]
    def get_embeddings_batch(texts: list[str]) -> list[list[float]]
    def get_paper_embedding_text(title, abstract, keywords) -> str
```

**Принцип работы:**
1. Ленивая загрузка модели sentence-transformers
2. Генерация нормализованных эмбеддингов для косинусного сходства
3. Пакетная обработка для производительности

### Vector Service

**Файл:** `backend/app/services/vector_service.py`

Сервис векторного поиска на основе ChromaDB.

| Метод | Описание |
|-------|----------|
| `add_paper()` | Добавить статью в векторную базу |
| `search()` | Векторный поиск с фильтрами |
| `delete_paper()` | Удалить статью из индекса |
| `rebuild_index()` | Перестроить индекс заново |
| `get_stats()` | Статистика векторной базы |

**Характеристики:**
- Персистентное хранение в `./chroma_db`
- Косинусное сходство (HNSW индекс)
- Фильтрация по метаданным (source, date)

### FullText Search Service

**Файл:** `backend/app/services/fulltext_search_service.py`

Сервис полнотекстового поиска PostgreSQL.

| Метод | Описание |
|-------|----------|
| `search()` | FTS поиск с режимами (plain, phrase, websearch) |
| `search_with_highlight()` | Поиск с подсветкой совпадений |
| `suggest()` | Автодополнение запросов |
| `search_keywords()` | Поиск по ключевым словам (AND/OR) |
| `get_search_stats()` | Статистика поиска |

**Режимы поиска:**
- **plain**: Обычный поиск (слова соединяются AND)
- **phrase**: Поиск точной фразы
- **websearch**: Расширенный поиск с AND, OR, NOT

### User Service

**Файл:** `backend/app/services/user_service.py`

Сервис управления пользователями.

| Метод | Описание |
|-------|----------|
| `get_by_email()` | Получить пользователя по email |
| `get_by_id()` | Получить пользователя по ID |
| `create_user()` | Создать нового пользователя |
| `update_last_login()` | Обновить время последнего входа |
| `authenticate()` | Аутентификация пользователя |

### Report Service

**Файл:** `backend/app/services/report_service.py`

Сервис генерации отчётов.

| Метод | Описание |
|-------|----------|
| `generate_paper_pdf()` | Генерация PDF отчёта |
| `generate_paper_docx()` | Генерация DOCX отчёта |

**Компоненты:**
- `PaperReportData` - данные отчёта
- `ReportExporter` - экспорт в форматы

---

## 🕷️ Парсеры

### Архитектура парсеров

```
parsers_pkg/
├── base/                    # Базовые классы
│   ├── base_parser.py       # Базовый парсер
│   ├── base_client.py       # Базовый API клиент
│   └── deduplicator.py      # Дедупликация
├── pipelines/               # ETL конвейеры
│   └── data_pipeline.py
├── arxiv/                   # arXiv парсер
│   ├── client.py
│   └── parser.py
├── core/                    # CORE парсер
│   ├── client.py
│   └── parser.py
├── selenium/                # Selenium парсеры
├── spiders/                 # Spider парсеры
└── patents/                 # Парсеры патентов
```

### Поддерживаемые источники

| Источник | Тип | API | Статус |
|----------|-----|-----|--------|
| arXiv | API | REST | ✅ |
| CORE | API | REST | ✅ |
| ScienceDirect | Selenium | WebDriver | 🔄 |
| ResearchGate | Spider | HTML | 🔄 |
| Google Patents | Mixed | API/Selenium | 🔄 |
| Espacenet | API | REST | 🔄 |

### Задачи парсинга (Celery)

**Файл:** `backend/app/tasks/parse_tasks.py`

| Задача | Описание |
|--------|----------|
| `parse_papers_task` | Парсинг по одному запросу |
| `parse_multiple_queries_task` | Парсинг по нескольким запросам |
| `parse_all_sources_task` | Парсинг по всем источникам |

**Прогресс выполнения:**
```json
{
  "status": "STARTED",
  "meta": {
    "query": "nickel-based alloys",
    "source": "CORE",
    "current": 25,
    "total": 50,
    "saved_count": 20,
    "embedded_count": 18,
    "status": "Сохранение статей..."
  }
}
```

### Базовые классы

**BaseAPIClient** (`parsers_pkg/base/base_client.py`):
```python
class BaseAPIClient(ABC):
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: float = 30.0)
    async def _get_client() -> httpx.AsyncClient
    async def search(query: str, **kwargs) -> list[dict]
    async def get_full_text(item_id: str) -> Optional[str]
    async def close()
```

**BaseParser** (`parsers_pkg/base/base_parser.py`):
```python
class BaseParser(ABC):
    def __init__(self, source: str = "unknown")
    async def parse_search_results(data: list[dict]) -> list[Paper]
    async def parse_full_text(text: str, metadata: dict) -> Paper
    async def extract_keywords(paper: Paper) -> list[str]
    def normalize_paper(paper: Paper) -> Paper  # Очистка текста
    def validate_paper(paper: Paper) -> tuple[bool, List[str]]
```

### Дедупликация

**Файл:** `parsers_pkg/base/deduplication.py`

| Стратегия | Порог | Описание |
|-----------|-------|----------|
| DOI match | 1.0 | Точное совпадение DOI |
| Source ID match | 1.0 | Точное совпадение source_id |
| Title similarity | 0.85 | SequenceMatcher (Levenshtein) |
| Content similarity | 0.75 | Jaccard similarity (множества слов) |

### ETL Конвейер

**Файл:** `parsers_pkg/pipelines/data_pipeline.py`

| Этап | Класс | Описание |
|------|-------|----------|
| Cleaning | `CleaningStage` | Очистка текста (encoding, whitespace) |
| Validation | `ValidationStage` | Проверка обязательных полей, DOI, URL |
| Deduplication | `DeduplicationStage` | Удаление дубликатов |
| Enrichment | `EnrichmentStage` | Добавление metadata (source, created_at) |

### arXiv Парсер

**Файл:** `parsers_pkg/arxiv/client.py`

- **API:** `https://export.arxiv.org/api/query`
- **Rate limit:** 3 секунды между запросами
- **Формат:** XML (Atom)
- **Категории:** cond-mat.mtrl-sci, physics.chem-ph, physics.app-ph

### CORE Парсер

**Файл:** `parsers_pkg/core/client.py`

- **API:** `https://core.ac.uk/api-v2`
- **Endpoint:** `/articles/search`
- **Параметры:** q, limit, offset, filter (has_full_text:true)

### Patent Parser

**Файл:** `parsers_pkg/patents/patent_parser.py`

| Источник | URL | Метод |
|----------|-----|-------|
| Google Patents | `https://patents.google.com` | HTML scraping (BeautifulSoup) |
| Espacenet | `https://worldwide.espacenet.com` | JSON API |

**Извлекаемые данные:**
- patent_number, title, applicants, inventors
- publication_date, ipc_classes
- abstract, description, claims

### ScienceDirect Parser

**Файл:** `parsers_pkg/selenium/sciencedirect_parser.py`

- **Технология:** Selenium WebDriver (Chrome)
- **Особенности:** Обход защиты, scroll для загрузки

### ResearchGate Parser

**Файл:** `parsers_pkg/spiders/researchgate_parser.py`

- **Технология:** httpx + BeautifulSoup
- **Пагинация:** page parameter

### Поисковые запросы по умолчанию

```python
# CORE запросы
DEFAULT_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys corrosion",
    "nickel alloys high temperature",
]

# arXiv запросы
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

### Celery Beat Расписание

**Файл:** `backend/app/tasks/celery_app.py`

| Задача | Расписание | Описание |
|--------|------------|----------|
| `hourly-parse-core` | Каждый час (minute=0) | Парсинг CORE по основным запросам |
| `daily-parse-all-sources` | Ежедневно в 00:00 | Парсинг всех источников |
| `weekly-parse-all-sources` | Каждое воскресенье в 00:00 | Увеличенный лимит парсинга |

```python
beat_schedule = {
    "hourly-parse-core": {
        "task": "app.tasks.parse_tasks.parse_multiple_queries_task",
        "schedule": crontab(minute=0),
        "kwargs": {
            "queries": settings.PARSE_QUERIES,
            "limit_per_query": settings.PARSE_LIMIT_PER_RUN // 2,
            "source": "CORE",
        },
    },
    "daily-parse-all-sources": {
        "task": "app.tasks.parse_tasks.parse_all_sources_task",
        "schedule": crontab(hour=0, minute=0),
        "kwargs": {"limit_per_query": settings.PARSE_LIMIT_PER_RUN},
    },
    "weekly-parse-all-sources": {
        "task": "app.tasks.parse_tasks.parse_all_sources_task",
        "schedule": crontab(hour=0, minute=0, day_of_week=0),
        "kwargs": {"limit_per_query": settings.PARSE_LIMIT_PER_RUN * 2},
    },
}
```

---

## 🔒 Система безопасности

### JWT Token Flow

```
┌─────────┐      ┌─────────┐      ┌─────────┐
│ Client  │      │  API    │      │  User   │
│         │─────▶│         │─────▶│  DB     │
│         │      │         │      │         │
│  Login  │      │ Verify  │      │  Find   │
│ Request │      │  Data   │      │  User   │
│         │      │         │      │         │
│         │◀─────│         │◀─────│         │
│  Token  │      │ Generate│      │  Hash   │
│         │      │  JWT    │      │ Compare │
└─────────┘      └─────────┘      └─────────┘
```

### Компоненты безопасности

**Файл:** `backend/app/core/security.py`

| Функция | Описание |
|---------|----------|
| `verify_password()` | Проверка пароля (bcrypt) |
| `get_password_hash()` | Хеширование пароля |
| `create_access_token()` | Создание JWT токена |
| `decode_access_token()` | Декодирование токена |

### Параметры JWT

```python
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
SECRET_KEY = "random-32-chars"  # из .env
```

### Dependency для авторизации

**Файл:** `backend/app/api/deps.py`

```python
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Получить текущего пользователя из JWT токена."""
```

---

## 🎨 Frontend архитектура

### Структура компонентов

```
frontend/src/
├── api/                    # API клиенты
│   ├── client.ts          # HTTP клиент (axios)
│   ├── auth.ts            # Auth API
│   ├── papers.ts          # Papers API (papers, vector, search)
│   └── patents.ts         # Patents API
├── components/             # UI компоненты
│   ├── layout/
│   │   ├── Layout.tsx     # Основной layout
│   │   ├── Header.tsx     # Шапка
│   │   ├── Sidebar.tsx    # Боковое меню
│   │   └── Footer.tsx     # Подвал
│   └── ui/                # UI компоненты (Toast)
├── context/
│   └── ThemeProvider.tsx  # Темизация (light/dark)
├── hooks/                  # Кастомные хуки
├── pages/                  # Страницы
│   ├── Landing.tsx        # Главная страница
│   ├── Dashboard.tsx      # Дашборд с метриками
│   ├── Patents.tsx        # Список статей
│   ├── PatentDetail.tsx   # Детали статьи
│   ├── PaperReport.tsx    # Отчёт по статье
│   ├── Analytics.tsx      # Векторный поиск
│   ├── Metrics.tsx        # Метрики
│   ├── FullTextSearch.tsx # FTS поиск
│   ├── CeleryMonitoring.tsx  # Мониторинг Celery
│   ├── WorkerStatus.tsx   # Статус воркеров
│   ├── Database.tsx       # Управление БД
│   ├── Login.tsx          # Вход
│   └── Register.tsx       # Регистрация
├── store/                  # Zustand store
│   └── authStore.ts       # Auth store (token, user)
├── types/                  # TypeScript типы
│   ├── paper.ts           # Типы статей
│   └── user.ts            # Типы пользователя
├── utils/                  # Утилиты
├── App.tsx                 # Роутинг
└── main.tsx                # Точка входа
```

### State Management (Zustand)

**Файл:** `frontend/src/store/authStore.ts`

```typescript
interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (user: User, token: string) => void;
  logout: () => void;
  setToken: (token: string) => void;
  setLoading: (loading: boolean) => void;
}

// Хранение токена в localStorage
const getStoredToken = (): string | null => 
  localStorage.getItem("auth_token");
```

### UI Компоненты

**Файл:** `frontend/src/components/ui/`

| Компонент | Файл | Описание |
|-----------|------|----------|
| Toast | `Toast.tsx` | Уведомления (success, error, warning, info) |
| Button | `Button.tsx` | Стилизованные кнопки |
| Input | `Input.tsx` | Поля ввода |
| Select | `Select.tsx` | Выпадающие списки |
| Table | `Table.tsx` | Таблицы данных |
| Modal | `Modal.tsx` | Модальные окна |
| Pagination | `Pagination.tsx` | Пагинация |
| Loading | `Loading.tsx` | Индикатор загрузки |
| ErrorBoundary | `ErrorBoundary.tsx` | Обработка ошибок |
| AdvancedFilters | `AdvancedFilters.tsx` | Расширенные фильтры |
| ExportButton | `ExportButton.tsx` | Экспорт (CSV, Excel) |

### Toast Уведомления

**Файл:** `frontend/src/components/ui/Toast.tsx`

```typescript
interface Toast {
  id: string;
  type: "success" | "error" | "info" | "warning";
  message: string;
  duration?: number;  // ms, default 5000
}

// Хук для управления
const { success, error, warning, info, dismiss } = useToast();
```

### Theme Provider

**Файл:** `frontend/src/context/ThemeProvider.tsx`

```typescript
type Theme = "light" | "dark";

// Сохранение в localStorage
localStorage.setItem("nickelfront-theme", theme);

// Применение к document
document.documentElement.setAttribute("data-theme", theme);
```

### Хуки

**Файл:** `frontend/src/hooks/useAuth.ts`

```typescript
function useAuth() {
  const { login, register, logout } = authApi;
  const { login: loginStore, logout: logoutStore } = useAuthStore();
  
  const login = async (data: LoginRequest) => {
    const response = await authApi.login(data);
    const user = await authApi.getCurrentUser();
    loginStore(user, response.access_token);
  };
  
  return { login, register, logout };
}
```

### Утилиты

**Файл:** `frontend/src/utils/formatters.ts`

```typescript
export const formatDate = (value: string) => 
  new Date(value).toLocaleDateString("ru-RU");
```

**Файл:** `frontend/src/utils/validators.ts`

```typescript
// Валидация форм
export const validateEmail = (email: string): boolean => {...}
export const validatePassword = (password: string): boolean => {...}
```

### API Client (Axios)

**Файл:** `frontend/src/api/client.ts`

```typescript
const apiClient = axios.create({
  baseURL: "/api/v1",
  timeout: 10000,
});

// Interceptor для токена
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("auth_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
```

### TypeScript Типы

**Файл:** `frontend/src/types/paper.ts`

```typescript
type PaperSource = "CORE" | "arXiv";

interface Paper {
  id: number;
  title: string;
  authors: string[];
  publicationDate: string | null;
  journal: string | null;
  doi: string | null;
  abstract: string | null;
  fullText: string | null;
  keywords: string[];
  source: PaperSource | string;
  sourceId: string | null;
  url: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

type SearchType = "vector" | "semantic" | "hybrid" | "text";

interface VectorSearchResult {
  paper: Paper;
  similarity: number;  // 0-1
}
```

### Страницы приложения

| Страница | Маршрут | Описание |
|----------|---------|----------|
| Landing | `/` | Главная страница |
| Dashboard | `/dashboard` | Дашборд с метриками и запуском парсинга |
| Patents | `/papers` | Список всех статей |
| PatentDetail | `/papers/:id` | Детали статьи |
| PaperReport | `/papers/:id/report` | Отчёт по статье |
| Analytics | `/vector-search` | Векторный поиск |
| Metrics | `/metrics` | Метрики и статистика |
| FullTextSearch | `/search` | Полнотекстовый поиск |
| CeleryMonitoring | `/celery` | Мониторинг Celery задач |
| WorkerStatus | `/jobs` | Статус воркеров |
| Database | `/database` | Управление БД |
| Login | `/login` | Вход в систему |
| Register | `/register` | Регистрация |

### Protected Routes

```typescript
function ProtectedRoute({ children }) {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" replace />;
}
```

---

## ⚙️ Конфигурация и переменные окружения

### Основной файл конфигурации

**Файл:** `backend/app/core/config.py`

```python
class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    
    # Redis
    REDIS_URL: str
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str
    
    # Парсинг
    PARSE_SCHEDULE_INTERVAL: int = 60
    PARSE_LIMIT_PER_RUN: int = 50
    PARSE_QUERIES: List[str]
    
    # CORS
    CORS_ORIGINS: List[str]
    
    # Vector Search
    CHROMA_DB_PATH: str = "./chroma_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
```

### Переменные окружения (.env)

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/nickelfront

# Redis
REDIS_URL=redis://localhost:6379/0

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Vector Search
CHROMA_DB_PATH=./chroma_db
EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIM=384

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/app.log

# Frontend
VITE_API_URL=http://localhost:8000/api/v1
```

---

## 📊 Логирование и мониторинг

### Логирование (Loguru)

**Файл:** `backend/app/core/logging.py`

```python
from loguru import logger

# Настройка логирования
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time} | {level} | {module} | {message}"
)
```

### Уровни логирования

| Уровень | Описание |
|---------|----------|
| DEBUG | Отладочная информация |
| INFO | Общая информация |
| WARNING | Предупреждения |
| ERROR | Ошибки |
| CRITICAL | Критические ошибки |

### Мониторинг Celery

**Файл:** `backend/app/api/v1/endpoints/monitoring.py`

| Endpoint | Описание |
|----------|----------|
| `GET /monitoring/celery/status` | Статус Celery кластера |
| `GET /monitoring/celery/workers` | Информация о воркерах |
| `GET /monitoring/celery/tasks` | Список задач |
| `GET /monitoring/celery/queues` | Информация об очередях |
| `GET /monitoring/celery/scheduled-tasks` | Запланированные задачи |

### Flower (веб-интерфейс)

```bash
# Запуск Flower
celery -A app.tasks.celery_app flower --port=5555

# Доступ
http://localhost:5555
```

---

## 🧪 Тестирование

### Backend тесты

**Файл:** `backend/tests/`

```bash
# Запустить все тесты
pytest

# С покрытием
pytest --cov=app

# Конкретный тест
pytest tests/test_papers.py -v
```

### Структура тестов

**Файл:** `tests/`

```
tests/
├── conftest.py                    # Фикстуры (test_db, client, sample_paper_data)
├── requirements.txt               # Тестовые зависимости
├── unit/
│   ├── test_auth.py              # Тесты авторизации (10 тестов)
│   ├── test_paper_service.py     # Тесты PaperService (16 тестов)
│   ├── test_analytics.py         # Тесты аналитики
│   ├── test_vector_search.py     # Тесты векторного поиска
│   └── parser/
│       ├── test_arxiv_client.py  # Тесты arXiv клиента
│       ├── test_arxiv_parser.py  # Тесты arXiv парсера
│       ├── test_core_client.py   # Тесты CORE клиента
│       └── test_core_parser.py   # Тесты CORE парсера
└── integration/
    ├── test_arxiv_client.py      # Integration тесты arXiv
    ├── test_core_client.py       # Integration тесты CORE
    └── test_paper_api.py         # Integration тесты API
```

### Фикстуры (conftest.py)

```python
# Тестовая БД в памяти (SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def test_db(engine) -> AsyncGenerator[AsyncSession, None]:
    """Создать тестовую сессию БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = async_sessionmaker(engine, class_=AsyncSession)
    
    async with async_session() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client(test_db) -> AsyncGenerator[AsyncClient, None]:
    """Создать тестовый HTTP клиент."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def sample_paper_data():
    """Пример данных статьи для тестов."""
    return {
        "title": "Nickel-based superalloys for high temperature applications",
        "authors": ["John Smith", "Jane Doe"],
        "publication_date": "2024-01-15",
        "journal": "Journal of Materials Science",
        "doi": "10.1234/test.2024.001",
        "abstract": "This paper studies nickel-based superalloys...",
        "full_text": "Full text of the paper...",
        "keywords": ["nickel", "superalloys", "high temperature"],
        "source": "CORE",
        "source_id": "123456",
        "url": "https://example.com/paper",
    }
```

### Тесты авторизации

**Файл:** `tests/unit/test_auth.py`

| Тест | Описание |
|------|----------|
| `test_register_user` | Регистрация нового пользователя |
| `test_register_duplicate_email` | Регистрация с дублирующимся email |
| `test_register_weak_password` | Регистрация со слабым паролем |
| `test_login_user` | Вход пользователя |
| `test_login_wrong_password` | Вход с неправильным паролем |
| `test_get_current_user` | Получение текущего пользователя |
| `test_get_current_user_unauthorized` | Доступ без авторизации |
| `test_logout` | Выход из системы |
| `test_jwt_token_format` | Проверка формата JWT токена |
| `test_register_invalid_email` | Регистрация с невалидным email |

### Тесты Paper Service

**Файл:** `tests/unit/test_paper_service.py`

| Тест | Описание |
|------|----------|
| `test_create_paper` | Создание статьи |
| `test_create_paper_duplicate_doi` | Создание дубликата (по DOI) |
| `test_get_by_id` | Получение по ID |
| `test_get_by_id_not_found` | Получение несуществующей |
| `test_get_by_doi` | Получение по DOI |
| `test_get_by_source_id` | Получение по source_id |
| `test_search_by_title` | Поиск по названию |
| `test_search_by_keyword` | Поиск по ключевому слову |
| `test_get_all` | Получение всех статей |
| `test_get_total_count` | Получение общего количества |
| `test_update_paper` | Обновление статьи |
| `test_update_paper_not_found` | Обновление несуществующей |
| `test_delete_paper` | Удаление статьи |
| `test_delete_paper_not_found` | Удаление несуществующей |

### Тесты парсеров

**Файл:** `tests/unit/parser/`

```python
# Пример теста парсера
@pytest.mark.asyncio
async def test_arxiv_parser_parse_entry():
    parser = ArxivParser()
    entry = {
        "title": "  Test Title  ",
        "authors": ["  Author 1  ", "  Author 2  "],
        "abstract": "Test abstract",
        "categories": ["cond-mat.mtrl-sci"],
    }
    paper = await parser.parse_search_results([entry])
    assert paper[0].title == "Test Title"
    assert len(paper[0].authors) == 2
```

### Запуск тестов

```bash
# Все тесты
pytest tests/ -v

# Unit тесты
pytest tests/unit/ -v

# Integration тесты
pytest tests/integration/ -v

# Тесты парсеров
pytest tests/unit/parser/ -v

# С покрытием
pytest --cov=app --cov-report=html

# Конкретный тест
pytest tests/unit/test_auth.py::test_login_user -v
```

### Тестовые зависимости

**Файл:** `tests/requirements.txt`

```
pytest==8.0.0
pytest-asyncio==0.23.3
httpx==0.26.0
aiosqlite==0.19.0
```

---

## 🔄 CI/CD

### GitHub Actions

**Файл:** `.github/workflows/tests.yml`

```yaml
name: Tests CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
      redis:
        image: redis:7
    
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest --cov=app
```

---

## � Скрипты запуска

### Backend скрипты

**Файл:** `run_backend.bat`

```batch
cd backend
python ..\shared\__init__.py
python start_server.py
```

**Файл:** `backend/start_server.py`

```python
import sys
from pathlib import Path

# Добавляем корень проекта и backend в PATH
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
```

**Файл:** `run_worker.bat`

```batch
cd backend
celery -A app.tasks.celery_app worker --loglevel=info
```

**Файл:** `run_all.bat`

```batch
start run_backend.bat
start run_worker.bat
```

### Скрипты миграций

**Файл:** `backend/apply_migrations.py`

```python
from alembic.config import Config
from alembic import command

def run_migrations():
    alembic_cfg = Config("alembic.ini")
    print("Применение миграций...")
    command.upgrade(alembic_cfg, "head")
    print("Миграции успешно применены!")

if __name__ == "__main__":
    run_migrations()
```

**Файл:** `backend/app/db/init_db.py`

```python
async def init_db():
    """Создать все таблицы в БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("База данных инициализирована")
```

### Shell скрипты

**Файл:** `activate.sh`

```bash
#!/bin/bash
# Активация виртуального окружения
source venv/bin/activate
```

**Файл:** `setup.ps1` (Windows PowerShell)

```powershell
# Установка зависимостей
pip install -r backend/requirements.txt
npm install --prefix frontend
```

---

## ⚙️ Конфигурационные файлы

### Pyproject.toml

**Файл:** `pyproject.toml`

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
select = ["E", "F", "W", "I", "N", "UP"]
ignore = ["E501"]

[tool.ruff.isort]
known-first-party = ["app", "shared"]

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
asyncio_mode = "auto"
```

### Alembic.ini

**Файл:** `backend/alembic.ini`

```ini
[alembic]
script_location = alembic
prepend_sys_path = .

# Для миграций используем синхронный драйвер psycopg2
sqlalchemy.url = postgresql://user:password@localhost:5432/nickelfront

[loggers]
keys = root,sqlalchemy,alembic
```

### Docker Compose

**Файл:** `backend/docker-compose.yml`

```yaml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: nickelfront
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d nickelfront"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  backend:
    build: .
    command: >
      sh -c "python -m app.db.init_db &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/nickelfront
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  worker:
    build: .
    command: celery -A app.tasks.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/nickelfront
      - REDIS_URL=redis://redis:6379/0

  flower:
    build: .
    command: celery -A app.tasks.celery_app flower --port=5555
    ports:
      - "5555:5555"

  celery_beat:
    build: .
    command: celery -A app.tasks.celery_app beat --loglevel=info
```

### Vite Config

**Файл:** `frontend/vite.config.js`

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

---

## �🔧 Troubleshooting

### Частые проблемы

#### 1. Ошибка подключения к PostgreSQL

```
Error: could not connect to database
```

**Решение:**
- Проверьте DATABASE_URL в .env
- Убедитесь, что PostgreSQL запущен
- Проверьте учётные данные

#### 2. ChromaDB не инициализируется

```
Error: ChromaDB not available
```

**Решение:**
```bash
pip install chromadb
# Проверьте права на запись в ./chroma_db
```

#### 3. Celery worker не запускается

```
Error: Redis connection refused
```

**Решение:**
- Запустите Redis: `redis-server`
- Проверьте CELERY_BROKER_URL

#### 4. Ошибка генерации эмбеддингов

```
Error: sentence-transformers not available
```

**Решение:**
```bash
pip install sentence-transformers
# Или отключите векторный поиск
```

#### 5. CORS ошибка на frontend

```
Access to fetch blocked by CORS policy
```

**Решение:**
- Добавьте URL frontend в CORS_ORIGINS
- Проверьте настройки CORS в backend

#### 6. Миграции не применяются

```
Error: Can't locate revision identified by
```

**Решение:**
```bash
cd backend
alembic downgrade base
alembic upgrade head
```

#### 7. ModuleNotFoundError: No module named 'app'

**Решение:**
```bash
# Добавьте backend в PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(pwd)/backend
# Или используйте start_server.py
python backend/start_server.py
```

**Решение:**
```bash
pip install chromadb
# Проверьте права на запись в ./chroma_db
```

#### 3. Celery worker не запускается

```
Error: Redis connection refused
```

**Решение:**
- Запустите Redis: `redis-server`
- Проверьте CELERY_BROKER_URL

#### 4. Ошибка генерации эмбеддингов

```
Error: sentence-transformers not available
```

**Решение:**
```bash
pip install sentence-transformers
# Или отключите векторный поиск
```

#### 5. CORS ошибка на frontend

```
Access to fetch blocked by CORS policy
```

**Решение:**
- Добавьте URL frontend в CORS_ORIGINS
- Проверьте настройки CORS в backend

---

## 💾 Хранение данных

### Где хранятся данные

#### 1. PostgreSQL (Основная БД)

**Файл:** `backend/app/db/models/paper.py`

**Таблица:** `papers`

| Поле | Тип | Описание | Хранение |
|------|-----|----------|----------|
| id | Integer | Primary key | DB |
| title | Text | Название статьи | DB |
| authors | JSON | Список авторов | DB |
| publication_date | DateTime | Дата публикации | DB |
| journal | String(500) | Журнал | DB |
| doi | String(200) | DOI (уникальный) | DB |
| **abstract** | Text | **Аннотация статьи** | DB |
| **full_text** | Text | **Полный текст статьи** | DB |
| keywords | JSON | Ключевые слова | DB |
| **embedding** | JSON | **Векторный эмбеддинг (384 float)** | DB |
| search_vector | TSVECTOR | FTS вектор | DB |
| source | String(50) | Источник (CORE, arXiv) | DB |
| source_id | String(200) | ID в источнике | DB |
| url | String(1000) | URL статьи | DB |
| created_at | DateTime | Дата создания | DB |
| updated_at | DateTime | Дата обновления | DB |

**Что хранится в PostgreSQL:**
- ✅ Аннотации (abstract) - Text поле
- ✅ Полные тексты (full_text) - Text поле
- ✅ Векторные эмбеддинги (embedding) - JSON массив float[384]
- ✅ Метаданные статей

**Подключение:**
```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/nickelfront
```

---

#### 2. ChromaDB (Векторный индекс)

**Директория:** `./chroma_db/`

**Коллекция:** `papers`

**Структура записи:**
```python
{
    "id": "paper_123",
    "embedding": [0.1, 0.2, ...],  # 384 float нормализованных
    "metadata": {
        "paper_id": 123,
        "title": "...",
        "source": "CORE",
        "doi": "10.1234/...",
        "publication_date": "2024-01-15",
        "journal": "..."
    },
    "document": "Title text for context"
}
```

**Что хранится:**
- ✅ Векторные эмбеддинги для семантического поиска
- ✅ Метаданные для фильтрации (source, date, doi)

**Файл:** `backend/app/services/vector_service.py`

```python
CHROMA_PERSIST_DIR = "./chroma_db"

def add_paper(self, paper_id: int, embedding: list[float], ...):
    self.collection.add(
        ids=[f"paper_{paper_id}"],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[title]
    )
```

---

#### 3. Redis (Кэш и брокер)

**Подключение:**
```
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

**Что хранится:**
- ✅ Очереди Celery задач
- ✅ Результаты выполнения задач
- ✅ Сессии Flower (мониторинг)

---

#### 4. Файловая система

| Директория | Что хранится |
|------------|--------------|
| `./logs/` | Логи приложения (app_YYYY-MM-DD.log) |
| `./chroma_db/` | ChromaDB персистентное хранилище |
| `backend/logs/` | Логи backend |
| `report/` | Сгенерированные отчёты (временные) |

---

### PDF файлы

**Важно:** PDF файлы **НЕ хранятся** в системе постоянно.

#### Генерация PDF отчётов

**Файл:** `backend/app/api/v1/endpoints/reports.py`

```python
@router.get("/paper/{paper_id}/pdf")
async def export_paper_pdf(paper_id: int, db: AsyncSession):
    # 1. Получаем статью из БД
    paper = await paper_service.get_by_id(paper_id)
    
    # 2. Конвертируем в dict
    paper_dict = {
        "id": paper.id,
        "title": paper.title,
        "abstract": paper.abstract,      # Из БД
        "full_text": paper.full_text,    # Из БД
        "keywords": paper.keywords,      # Из БД
        ...
    }
    
    # 3. Генерируем PDF в памяти (ReportLab)
    pdf_bytes = generate_paper_pdf(paper_dict)
    
    # 4. Возвращаем без сохранения на диск
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=paper_{paper_id}_report.pdf"}
    )
```

**Процесс:**
1. Пользователь запрашивает `/api/v1/reports/paper/{id}/pdf`
2. Данные берутся из PostgreSQL (abstract, full_text, keywords)
3. PDF генерируется в памяти через ReportLab
4. PDF возвращается как Response
5. **PDF не сохраняется на диск**

---

#### PDF из arXiv

**Файл:** `parsers_pkg/arxiv/client.py`

```python
async def get_full_text(self, item_id: str) -> Optional[str]:
    """Получить URL на PDF статьи."""
    clean_id = item_id.split('v')[0].split('/')[-1]
    return f"https://arxiv.org/pdf/{clean_id}.pdf"
```

**Процесс:**
- Парсер arXiv возвращает **URL** на PDF
- Сам PDF **не загружается**, только ссылка
- Пользователь может скачать PDF по ссылке

---

### Поток данных от парсера до БД

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Parser        │     │   Pipeline      │     │   Database      │
│   (arXiv/CORE)  │ ──▶ │   (ETL)         │ ──▶ │   (PostgreSQL)  │
│                 │     │                 │     │                 │
│ - title         │     │ - Cleaning      │     │ - abstract      │
│ - authors       │     │ - Validation    │     │ - full_text     │
│ - abstract      │     │ - Deduplication │     │ - embedding     │
│ - full_text     │     │ - Enrichment    │     │ - metadata      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                              ┌─────────────────┐
                                              │   ChromaDB      │
                                              │   (Vector)      │
                                              │                 │
                                              │ - embedding     │
                                              │ - metadata      │
                                              └─────────────────┘
```

**Файл:** `backend/app/tasks/parse_tasks.py`

```python
# 1. Парсинг
search_results = await client.search(query=query, limit=limit)
papers = await parser.parse_search_results(search_results)

# 2. Сохранение в БД
paper_create = PaperCreate(
    title=paper.title,
    authors=paper.authors,
    abstract=paper.abstract,      # <-- Аннотация
    full_text=paper.full_text,    # <-- Полный текст
    keywords=paper.keywords,
    ...
)
saved_paper = await paper_service.create_paper(paper_create)

# 3. Генерация эмбеддинга
embedding_text = embedding_service.get_paper_embedding_text(
    title=saved_paper.title,
    abstract=saved_paper.abstract,
    keywords=saved_paper.keywords,
)
embedding = embedding_service.get_embedding(embedding_text)

# 4. Сохранение эмбеддинга в БД
await paper_service.update_paper(saved_paper.id, embedding=embedding)

# 5. Добавление в ChromaDB
vector_service.add_paper(
    paper_id=saved_paper.id,
    embedding=embedding,
    title=saved_paper.title,
    ...
)
```

---

## 📡 API Endpoint (сводная таблица)

### Auth (Авторизация)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| POST | `/api/v1/auth/register` | `auth.py` | Регистрация |
| POST | `/api/v1/auth/login` | `auth.py` | Вход (JWT) |
| POST | `/api/v1/auth/logout` | `auth.py` | Выход |
| GET | `/api/v1/auth/me` | `auth.py` | Текущий пользователь |

### Papers (Статьи)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| GET | `/api/v1/papers` | `parse.py` | Список статей |
| GET | `/api/v1/papers/count` | `parse.py` | Количество |
| GET | `/api/v1/papers/id/{id}` | `parse.py` | Статья по ID |
| POST | `/api/v1/papers/search` | `parse.py` | Поиск в БД |
| POST | `/api/v1/papers/parse` | `parse.py` | Парсинг (запрос) |
| POST | `/api/v1/papers/parse-all` | `parse.py` | Массовый парсинг |
| DELETE | `/api/v1/papers/id/{id}` | `parse.py` | Удаление |

### Search (Полнотекстовый поиск)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| POST | `/api/v1/search/fulltext` | `search.py` | FTS поиск |
| GET | `/api/v1/search/suggest` | `search.py` | Автодополнение |
| POST | `/api/v1/search/keywords` | `search.py` | Поиск по keywords |
| GET | `/api/v1/search/stats` | `search.py` | Статистика поиска |
| GET | `/api/v1/search/highlight/{id}` | `search.py` | Подсветка |

### Vector Search (Векторный поиск)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| POST | `/api/v1/vector/search` | `vector.py` | Семантический поиск |
| GET | `/api/v1/vector/stats` | `vector.py` | Статистика |
| POST | `/api/v1/vector/rebuild` | `vector.py` | Перестройка индекса |

### Analytics (Аналитика)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| GET | `/api/v1/analytics/metrics/summary` | `analytics.py` | Сводная статистика |
| GET | `/api/v1/analytics/metrics/trend` | `analytics.py` | Тренд публикаций |
| GET | `/api/v1/analytics/metrics/top` | `analytics.py` | Топ элементов |
| GET | `/api/v1/analytics/metrics/source-distribution` | `analytics.py` | Распределение |
| GET | `/api/v1/analytics/metrics/quality-report` | `analytics.py` | Отчёт о качестве |

### Reports (Отчёты)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| GET | `/api/v1/reports/paper/{id}/pdf` | `reports.py` | Экспорт PDF |
| GET | `/api/v1/reports/paper/{id}/docx` | `reports.py` | Экспорт DOCX |
| GET | `/api/v1/reports/paper/{id}` | `reports.py` | Отчёт JSON |

### Tasks (Задачи)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| POST | `/api/v1/tasks` | `tasks.py` | Создать задачу |
| GET | `/api/v1/tasks/{id}` | `tasks.py` | Статус задачи |
| GET | `/api/v1/tasks/celery/{task_id}/status` | `tasks.py` | Статус Celery |

### Monitoring (Мониторинг)

| Метод | Endpoint | Файл | Описание |
|-------|----------|------|----------|
| GET | `/api/v1/monitoring/celery/status` | `monitoring.py` | Статус Celery |
| GET | `/api/v1/monitoring/celery/workers` | `monitoring.py` | Воркеры |
| GET | `/api/v1/monitoring/celery/tasks` | `monitoring.py` | Задачи |
| GET | `/api/v1/monitoring/celery/queues` | `monitoring.py` | Очереди |
| GET | `/api/v1/monitoring/celery/scheduled-tasks` | `monitoring.py` | Расписание |

---

