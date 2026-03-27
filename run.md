# Backend Run Report (2026-03-27)

## Summary
- Switched backend configuration to load environment variables only from the root `.env`.
- Wired Celery broker/result backend to `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` from `.env`.
- Routed vector search, embedding, and logging settings through `.env`.
- Added a root `run_backend.bat` to start the backend from the project root with optional venv activation.

## Changes Made
- `backend/app/core/config.py`
  - `env_file` now points to the root `.env`.
  - Added `DEBUG`, `CHROMA_DB_PATH`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `LOG_LEVEL`, `LOG_FILE`.
  - Added `resolve_path()` helper for relative paths.
- `backend/app/tasks/celery_app.py`
  - Celery now uses `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`.
  - Beat schedule filename resolved via `resolve_path()`.
- `backend/app/core/logging.py`
  - Console and file logging now honor `LOG_LEVEL` and `LOG_FILE`.
- `backend/app/services/vector_service.py`
  - ChromaDB path now reads `CHROMA_DB_PATH`.
- `backend/app/services/embedding_service.py`
  - Embedding model and dimension now read `EMBEDDING_MODEL` and `EMBEDDING_DIM`.
- `backend/start_server.py`
  - `reload` now respects `DEBUG`.
- `run_backend.bat`
  - Starts backend from repo root, activates `venv` if present.

## How To Run (Windows)
1. Install dependencies once:
   `pip install -r requirements.txt`
2. Update values in the root `.env` as needed.
3. Start the backend:
   `run_backend.bat`

## Notes
- Tests were not executed in this pass.

# Celery Worker Run Report (2026-03-27)

## Summary
- Added a root `run_worker.bat` to start the Celery worker using root `.env`.

## Changes Made
- `run_worker.bat`
  - Activates `venv` if present, then runs `celery -A app.tasks.celery_app worker --loglevel=info` from `backend`.

## How To Run (Windows)
1. Install dependencies once:
   `pip install -r requirements.txt`
2. Update values in the root `.env` as needed.
3. Start the worker:
   `run_worker.bat`

## Notes
- Tests were not executed in this pass.

# Flower Run Report (2026-03-28)

## Summary
- Added a root `run_flower.bat` to start Flower (Celery monitoring UI/API).

## Changes Made
- `run_flower.bat`
  - Activates `venv` if present, then runs `celery -A app.tasks.celery_app flower --port=5555` from `backend`.
- `.env`
  - Added `FLOWER_UNAUTHENTICATED_API=true` to allow API access from backend monitoring.

## How To Run (Windows)
1. Install dependencies once:
   `pip install -r requirements.txt`
2. Start Flower:
   `run_flower.bat`

## Notes
- Flower powers `/api/v1/monitoring/celery/*` endpoints that returned 503.
- If Flower API returns 401, set `FLOWER_UNAUTHENTICATED_API=true` in `.env` and restart `run_flower.bat`.

# Runtime Fixes (2026-03-28)

## Summary
- Added a unique Celery worker nodename to avoid duplicate node warnings.
- Switched Polars dependency to `polars[rtcompat]` for CPUs without AVX2/FMA features.

## Changes Made
- `run_worker.bat`
  - Adds `-n worker@%COMPUTERNAME%-%RANDOM%`.
- `requirements.txt`
  - Unified backend/test dependencies.

## How To Apply
1. Reinstall deps:
   `pip install -r requirements.txt`

# Redis Run Report (2026-03-27)

## Summary
- Added a root `run_redis.bat` to start Redis natively on Windows.
- Downloaded Redis for Windows binaries into `redis/` (project-local).

## Changes Made
- `run_redis.bat`
  - Uses `redis/redis-server.exe` in the project root.
  - Reads port from root `.env` `REDIS_URL` (default `6380`).
  - Stores data in `redis` at repo root.
  - If Redis is already listening on the port, it stops that Redis instance and starts a new one in the same console.
- `redis/`
  - Added Redis for Windows binaries.

## How To Run (Windows)
1. Start Redis:
   `run_redis.bat`

## Notes
- Script runs Redis in the foreground; keep the window open while using it.
- `backend/docker-compose.yml` still uses inline environment values for containers (left unchanged to avoid breaking Docker defaults).

# Frontend Run Report (2026-03-27)

## Summary
- Configured Vite to load environment variables only from the root `.env`.
- Proxy target now derives from `VITE_API_URL` (origin), keeping API routing consistent.
- Added a root `run_frontend.bat` for a clean Windows start.

## Changes Made
- `frontend/vite.config.js`
  - Uses root `.env` via `envDir`.
  - Loads `VITE_API_URL` to compute dev proxy target.
- `run_frontend.bat`
  - Starts the frontend dev server from `frontend`.

## How To Run (Windows)
1. Install dependencies once:
   `pip install -r requirements.txt`
2. Update values in the root `.env` as needed.
3. Start the frontend:
   `run_frontend.bat`

## Notes
- Tests were not executed in this pass.

# All Services Run Report (2026-03-28)

## Summary
- Added `run_all.bat` to start Redis, Backend, Worker, Flower, and Frontend with delays.

## Changes Made
- `run_all.bat`
  - Starts services in order with pauses (2s/3s/3s/2s).

## How To Run (Windows)
1. Ensure PostgreSQL service is running (port 5433).
2. Start all services:
   `run_all.bat`
