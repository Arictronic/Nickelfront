import sys
from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun, task_prerun
from loguru import logger

# Add project root and shared to PATH
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

# Celery settings
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Requeue task when worker process is lost/restarted mid-run.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,  # 1 hour hard limit
    task_soft_time_limit=3300,  # 55 minutes soft limit

    # Flower monitoring
    task_send_task_events=True,
    worker_send_task_events=True,

    # Celery Beat periodic tasks
    beat_schedule_filename=settings.resolve_path(settings.CELERY_BEAT_SCHEDULE_FILENAME),
    beat_schedule={
        # Daily all-sources parse (00:00)
        "daily-parse-all-sources": {
            "task": "app.tasks.parse_tasks.parse_all_sources_task",
            "schedule": crontab(hour=0, minute=0),
            "kwargs": {
                "limit_per_query": settings.PARSE_LIMIT_PER_RUN,
            },
        },
        # Weekly full parse (Sunday 00:00)
        "weekly-parse-all-sources": {
            "task": "app.tasks.parse_tasks.parse_all_sources_task",
            "schedule": crontab(hour=0, minute=0, day_of_week=0),
            "kwargs": {
                "limit_per_query": settings.PARSE_LIMIT_PER_RUN * 2,
            },
        },
        # Hourly CORE parse
        "hourly-parse-core": {
            "task": "app.tasks.parse_tasks.parse_multiple_queries_task",
            "schedule": crontab(minute=0),
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
