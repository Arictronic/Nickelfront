import sys
from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun, task_prerun
from loguru import logger

# Добавляем корень проекта и shared в PATH
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "shared"))

from app.core.config import settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402

setup_logging(service_name="celery_worker")

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.tasks",
        "app.tasks.parse_tasks",
        "app.tasks.content_tasks",
    ],
)

# Настройки Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 час максимум на задачу
    task_soft_time_limit=3300,  # 55 минут мягкий лимит

    # Настройки для Flower (мониторинг задач)
    task_send_task_events=True,  # Отправлять события задач
    worker_send_task_events=True,  # Отправлять события воркера

    # Настройки Celery Beat для периодических задач
    beat_schedule_filename=settings.resolve_path(settings.CELERY_BEAT_SCHEDULE_FILENAME),
    beat_schedule={
        # Ежедневный парсинг по всем запросам (каждый день в 00:00)
        "daily-parse-all-sources": {
            "task": "app.tasks.parse_tasks.parse_all_sources_task",
            "schedule": crontab(hour=0, minute=0),  # Каждый день в полночь
            "kwargs": {
                "limit_per_query": settings.PARSE_LIMIT_PER_RUN,
            },
        },
        # Еженедельный полный парсинг (каждое воскресенье в 00:00)
        "weekly-parse-all-sources": {
            "task": "app.tasks.parse_tasks.parse_all_sources_task",
            "schedule": crontab(hour=0, minute=0, day_of_week=0),  # Каждое воскресенье
            "kwargs": {
                "limit_per_query": settings.PARSE_LIMIT_PER_RUN * 2,  # Увеличенный лимит
            },
        },
        # Парсинг по расписанию (каждый час)
        "hourly-parse-core": {
            "task": "app.tasks.parse_tasks.parse_multiple_queries_task",
            "schedule": crontab(minute=0),  # Каждый час
            "kwargs": {
                "queries": settings.get_parse_queries(),
                "limit_per_query": settings.PARSE_LIMIT_PER_RUN // 2,
                "source": "CORE",
            },
        },
    },
)


@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    logger.info(f"Задача {task.name}[{task_id}] началась")


@task_postrun.connect
def task_postrun_handler(task_id, task, *args, **kwargs):
    logger.info(f"Задача {task.name}[{task_id}] завершена")
