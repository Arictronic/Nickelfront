# Nickelfront Frontend

Frontend часть проекта Nickelfront на `React + Vite + TypeScript`.

## Что реализовано

- Главная (демо) (`/`)
- Dashboard парсинга (`/dashboard`)
- Каталог статей (`/papers`)
- Карточка статьи и отчет (`/papers/:id`, `/papers/:id/report`)
- Векторный поиск UI (`/vector-search`, fallback на `/papers/search`)
- Статус парсинга (`/jobs`, эвристика)
- Доступные данные/таблицы (`/database`)
- Авторизация и регистрация (`/login`, `/register`) — UI, backend auth endpoints пока отсутствуют

## Технологии

- React 18
- React Router
- Zustand
- Axios
- Recharts
- Vite

## Запуск

```bash
cd frontend
npm install
npm run dev
```

Приложение будет доступно на `http://localhost:3000`.

## Production build

```bash
npm run build
```

## Связь с backend

- В `vite.config.js` настроен proxy:
  - `/api` -> `http://localhost:8000`
- Используемые backend endpoints:
  - `GET    /api/v1/papers?limit&offset&source`
  - `GET    /api/v1/papers/count?source`
  - `GET    /api/v1/papers/id/{id}`
  - `POST   /api/v1/papers/search`
  - `POST   /api/v1/papers/parse?query&limit&source`
  - `POST   /api/v1/papers/parse-all?limit_per_query&source`
  - `DELETE /api/v1/papers/id/{id}`

## Ограничения по интеграции

В текущем backend есть эндпоинты только для парсинга и управления **papers**:
- поэтому таблицы/карточки на фронте работают с реальными данными из `/api/v1/papers/...`;
- для “vector search” и ML-метрик сейчас используется текущий `/papers/search` как fallback, а сами метрики/отчет формируются на фронте (эвристики) до появления ML-endpoint-ов.

Авторизация/регистрация в текущем проекте не подкреплена backend auth-эндпоинтами, поэтому UI хранит состояние локально.

Где менять для настоящей авторизации:
- backend: добавить endpoints auth (например, JWT)
- frontend: заменить `src/api/auth.ts`, `src/hooks/useAuth.ts` и `src/store/authStore.ts` под контракт auth.

## Ключевые функции (live data)

- `/dashboard`: запуск парсинга (`/api/v1/papers/parse` и `/api/v1/papers/parse-all`) + KPI (кол-во статей) + список последних добавленных
- `/papers`: каталог статей из БД (`GET /api/v1/papers`) + поиск (`POST /api/v1/papers/search`), сортировка на клиенте, удаление (`DELETE /api/v1/papers/id/{id}`), экспорт CSV текущей выборки
- `/papers/:id`: карточка статьи (`GET /api/v1/papers/id/{id}`) + разбиение `full_text/abstract` на части по настройке токенов
- `/papers/:id/report`: страница отчета по частям (сейчас формируется на фронте до появления ML-endpoint-ов)
- `/vector-search`: поисковый экран (fallback через `POST /api/v1/papers/search`)
- `/jobs`: статус ваших парсинг-задач (эвристика, так как endpoint celery-status отсутствует)
- `/database`: просмотр доступных таблиц/сущностей в текущем бэкенде (по фактическим endpoint-ам)

## Примечания

- Интерфейс сделан без градиентов.
- Emoji удалены из UI.
