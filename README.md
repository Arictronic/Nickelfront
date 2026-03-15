# Nickelfront

Платформа для парсинга и анализа патентов с использованием ML.

## Структура проекта

```
├── backend/              # Бэкенд на FastAPI
│   ├── app/              # Основное приложение
│   │   ├── api/          # REST API endpoints (маршруты, роутеры)
│   │   ├── core/         # Ядро: конфиг, безопасность, логирование
│   │   ├── db/           # База данных: SQLAlchemy модели, сессии
│   │   ├── services/     # Бизнес-логика и сервисы
│   │   └── tasks/        # Celery задачи (очередь задач)
│   └── alembic/          # Миграции БД (версионирование схемы)
│
├── frontend/             # Фронтенд на React + Vite
│   ├── src/
│   │   ├── components/   # UI компоненты (кнопки, формы, таблицы)
│   │   ├── pages/        # Страницы (дашборды, списки патентов)
│   │   ├── hooks/        # Custom React hooks
│   │   ├── store/        # Управление состоянием (Zustand)
│   │   └── api/          # API клиент для запросов к бэкенду
│   └── public/           # Статические файлы (favicon, index.html)
│
├── parser/               # Парсер патентов
│   ├── spiders/          # BeautifulSoup spiders для статических страниц
│   ├── selenium/         # Selenium скрипты для динамических сайтов
│   └── pipelines/        # Конвейеры обработки спаршенных данных
│
├── ml/                   # Машинное обучение
│   ├── models/           # Обученные модели (.pth, .pkl)
│   ├── training/         # Скрипты обучения моделей
│   ├── features/         # Извлечение признаков (PDF, текст)
│   └── notebooks/        # Jupyter ноутбуки для экспериментов
│
├── analytics/            # Аналитика и отчёты
│   ├── reports/          # Генерация отчётов (Polars/pandas)
│   ├── metrics/          # Ключевые метрики (тренды, лидеры)
│   └── validation/       # Валидация данных после парсинга
│
├── tests/                # Тесты (все модули)
│   ├── unit/             # Unit-тесты (backend, parser, ml)
│   ├── integration/      # Интеграционные тесты
│   └── e2e/              # E2E тесты (критические пути фронтенда)
│
└── shared/               # Общие модули (используются везде)
    ├── schemas/          # Pydantic схемы (валидация данных)
    └── utils/            # Общие утилиты и хелперы
```

## Быстрый старт

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

## Распределение задач

| Ветка | Ответственный | Папки |
|-------|--------------|-------|
| `feature/db` | Артем + Серега | `backend/app/db/`, `alembic/` |
| `feature/backend` | Ваня | `backend/app/api/`, `services/`, `tasks/` |
| `feature/frontend` | Тамерлан | `frontend/` |
| `feature/parser` | — | `parser/` |
| `feature/ml` | Паша + Серега | `ml/` |
| `feature/analytics` | Паша | `analytics/` |
| `feature/tests` | Тамерлан | `tests/` |

## Workflow

1. Создать ветку от `main`: `git checkout -b feature/your-feature`
2. Реализовать задачу в своей папке
3. Создать PR в `main`
4. После ревью — мердж
