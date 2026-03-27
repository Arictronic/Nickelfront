# Nickelfront

Платформа для парсинга и анализа научных статей и патентов в области материаловедения (никелевые сплавы, жаропрочные сплавы, суперсплавы).

[![Tests CI](https://github.com/your-org/nickelfront/actions/workflows/tests.yml/badge.svg)](https://github.com/your-org/nickelfront/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/node-18+-green.svg)](https://nodejs.org/)

---

## 📋 Оглавление

- [О проекте](#о-проекте)
- [Возможности](#возможности)
- [Быстрый старт](#быстрый-старт)
- [Документация](#документация)
- [Архитектура](#архитектура)
- [Разработка](#разработка)
- [Тестирование](#тестирование)
- [Вклад](#вклад)
- [Лицензия](#лицензия)

---

## 📖 О проекте

Nickelfront — это полнофункциональная платформа для:
- 📥 Парсинга научных статей из arXiv, CORE, ScienceDirect, ResearchGate
- 🔍 Полнотекстового и векторного поиска
- 📊 Анализа метрик и генерации отчётов
- 📑 Экспорта отчётов в PDF/DOCX
- 📈 Мониторинга Celery задач
- 🔐 Авторизации и управления пользователями

**Статус:** ✅ Готово к использованию (v1.0.0)

---

## ✨ Возможности

### Backend
- ✅ **FastAPI** REST API с Swagger документацией
- ✅ **PostgreSQL** + SQLAlchemy (async)
- ✅ **Celery** + Redis для фоновых задач
- ✅ **JWT** авторизация
- ✅ **Векторный поиск** (ChromaDB + sentence-transformers)
- ✅ **Полнотекстовый поиск** (PostgreSQL FTS)
- ✅ **Аналитика** и метрики
- ✅ **Отчёты** (PDF/DOCX экспорт)

### Frontend
- ✅ **React 18** + Vite + TypeScript
- ✅ **Recharts** для графиков
- ✅ **Zustand** для state management
- ✅ **Темная тема**
- ✅ **Toast уведомления**
- ✅ **Экспорт CSV/Excel**
- ✅ **Расширенные фильтры**

### Парсеры
- ✅ **arXiv** API парсер
- ✅ **CORE** API парсер
- ✅ **ScienceDirect** Selenium парсер
- ✅ **ResearchGate** парсер
- ✅ **Patents** (Google Patents, Espacenet)

---

## 🚀 Быстрый старт

### Требования
- **Python** 3.9+
- **Node.js** 18+
- **PostgreSQL** 16+ (порт 5433)
- **Redis** (порт 6380)

### Установка и запуск

#### Вариант 1: Автоматический запуск (рекомендуется)

```bat
# Из корня проекта (CMD)
run_all.bat
```

Скрипт автоматически:
- ✅ Запустит Redis (run_redis.bat)
- ✅ Запустит Backend (FastAPI, порт 8001)
- ✅ Запустит Celery Worker
- ✅ Запустит Flower (Celery monitoring)
- ✅ Запустит Frontend (Vite, порт 5173)

Примечание: PostgreSQL должен быть запущен как сервис (порт 5433).

**После запуска:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8001
- Swagger UI: http://localhost:8001/docs
- Flower: http://localhost:5555

#### Вариант 2: Покомпонентный запуск

```bat
# 1. Запуск Redis (в отдельном окне)
run_redis.bat

# 2. Запуск Backend (в отдельном окне)
run_backend.bat

# 3. Запуск Celery Worker (в отдельном окне)
run_worker.bat

# 4. Запуск Flower (в отдельном окне)
run_flower.bat

# 5. Запуск Frontend (в отдельном окне)
run_frontend.bat
```

#### Вариант 3: Ручная установка (первый запуск)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

cd frontend
npm install
```
### Первая регистрация

1. Откройте http://localhost:5173
2. Нажмите **"Регистрация"**
3. Введите данные:
   - Email: ваш@email.com
   - Пароль: `MyPassword123` (минимум 8 символов, заглавная + строчная буква + цифра)
   - Подтверждение пароля
4. Нажмите **"Зарегистрироваться"**

### Документация

- 📖 **Полная инструкция:** [STARTUP.md](STARTUP.md)
- 🏗️ **Архитектура:** [ARCHITECTURE.md](ARCHITECTURE.md)
- 📚 **API Docs:** http://localhost:8001/docs

---

## 📚 Документация

| Документ | Описание |
|----------|----------|
| [API Documentation](./docs/API_DOCUMENTATION.md) | Полная документация API с примерами |
| [Developer Guide](./docs/DEVELOPER_GUIDE.md) | Руководство для разработчиков |
| [User Guide](./docs/USER_GUIDE.md) | Руководство пользователя |
| [CHANGELOG](./CHANGELOG.md) | История изменений |

---

## 🏗️ Архитектура

```
Nickelfront/
├── backend/              # FastAPI + Celery + SQLAlchemy
│   ├── app/
│   │   ├── api/         # API endpoints
│   │   ├── core/        # Конфигурация, security
│   │   ├── db/          # Модели БД
│   │   ├── services/    # Бизнес-логика
│   │   └── tasks/       # Celery задачи
│   ├── alembic/         # Миграции БД
│   └── tests/           # Тесты
├── frontend/            # React + Vite + TypeScript
│   ├── src/
│   │   ├── api/        # API клиенты
│   │   ├── components/ # UI компоненты
│   │   ├── pages/      # Страницы
│   │   └── store/      # Zustand store
│   └── tests/          # Тесты
├── parsers_pkg/        # Парсеры статей
├── analytics/          # Аналитика и метрики
├── shared/             # Общие Pydantic схемы
└── docs/               # Документация
```

---

## 💻 Разработка

### Добавление endpoint

**Backend:**
```python
# backend/app/api/v1/endpoints/my_module.py
from fastapi import APIRouter

router = APIRouter(prefix="/my-module", tags=["my-module"])

@router.get("/")
async def get_items():
    return {"items": []}
```

**Подключение:**
```python
# backend/app/main.py
from app.api.v1.endpoints import my_module as my_module_router

app.include_router(my_module_router.router, prefix="/api/v1")
```

### Добавление модели БД

```python
# backend/app/db/models/my_model.py
from sqlalchemy import Column, Integer, String
from app.db.base import Base

class MyModel(Base):
    __tablename__ = "my_models"
    id = Column(Integer, primary_key=True)
    name = Column(String)
```

**Миграция:**
```bash
cd backend
alembic revision -m "create my_models"
alembic upgrade head
```

---

## 🧪 Тестирование

### Backend тесты
```bash
cd backend
pytest                    # Запустить все тесты
pytest --cov=app         # С покрытием
pytest tests/unit/ -v    # Unit тесты
```

### Frontend тесты
```bash
cd frontend
npm test                 # Запустить тесты
npm run test:e2e         # E2E тесты
```

### CI/CD
Тесты запускаются автоматически при push и pull request.

---

## 🤝 Вклад

### Pull Request процесс

1. Fork репозиторий
2. Создать feature branch (`git checkout -b feature/amazing-feature`)
3. Commit (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing-feature`)
5. Открыть Pull Request

### Code Style

**Backend:**
- Black для форматирования
- Flake8 для linting
- Type hints для функций

**Frontend:**
- ESLint + Prettier
- TypeScript strict mode

---

## 📊 Статистика проекта

| Модуль | Задач | Выполнено | Готовность |
|--------|-------|-----------|------------|
| Backend API | 15 | 15 | 100% |
| Frontend UI | 18 | 18 | 100% |
| Парсеры | 6 | 6 | 100% |
| База данных | 5 | 5 | 100% |
| Очередь задач | 5 | 5 | 100% |
| Авторизация | 10 | 10 | 100% |
| Векторный поиск | 7 | 7 | 100% |
| Аналитика | 10 | 10 | 100% |
| Отчёты | 5 | 5 | 100% |
| Мониторинг | 4 | 4 | 100% |
| Тесты | 6 | 6 | 100% |
| Документация | 5 | 5 | 100% |
| **ИТОГО** | **96** | **96** | **100%** |

---

## 📄 Лицензия

MIT License — см. [LICENSE](LICENSE) файл.

---

## 📞 Контакты

- **Issues:** https://github.com/your-org/nickelfront/issues
- **Email:** support@nickelfront.com

---

**Версия:** 1.0.0
**Дата:** Март 2026


