import os
import sys
from pathlib import Path

from celery import Celery
from celery.signals import task_postrun, task_prerun
from loguru import logger


ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "shared"))

from app.core.config import settings
from app.core.logging import setup_logging


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_celery_cli_process() -> bool:
    """True only for real Celery worker/beat/flower CLI processes."""
    argv = " ".join(str(arg).lower() for arg in sys.argv)
    return "celery" in argv


def _worker_service_name() -> str:
    explicit = (os.getenv("NICKELFRONT_SERVICE_NAME") or "").strip()
    if explicit:
        return explicit
    if _env_bool("QWEN_GATEWAY_WORKER"):
        return "qwen_worker"
    if (os.getenv("NICKELFRONT_WORKER_ROLE") or "").strip().lower() == "content":
        return "content_worker"
    if not _is_celery_cli_process():


        return "backend_api"
    return "celery_worker"


IS_QWEN_GATEWAY_WORKER = _env_bool("QWEN_GATEWAY_WORKER")
SERVICE_NAME = _worker_service_name()
if _is_celery_cli_process():
    setup_logging(service_name=SERVICE_NAME)




if IS_QWEN_GATEWAY_WORKER:
    TASK_MODULES = [
        "app.tasks.qwen_tasks",
    ]
else:
    TASK_MODULES = [
        "app.tasks.tasks",
        "app.tasks.parse_tasks",
        "app.tasks.content_tasks",
        "app.tasks.dashboard_actions",
        "app.tasks.alloy_analysis_tasks",
        "app.tasks.qwen_tasks",

        "app.tasks.translation_tasks",
    ]

celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=TASK_MODULES,
)


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,

    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3300,



    resultrepr_maxsize=512,


    task_send_task_events=True,
    worker_send_task_events=True,


    beat_schedule_filename=settings.resolve_path(settings.CELERY_BEAT_SCHEDULE_FILENAME),
    beat_schedule={},
    task_routes={

        "app.tasks.parse_tasks.parse_papers_task": {"queue": "celery"},
        "app.tasks.parse_tasks.parse_multiple_queries_task": {"queue": "celery"},
        "app.tasks.parse_tasks.parse_all_sources_task": {"queue": "celery"},
        "app.tasks.qwen.send_message": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.qwen.markdown": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.qwen.ru_analysis": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.qwen.keywords": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.qwen.regenerate_markdown_part": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.qwen.ai_ocr_document": {"queue": settings.QWEN_QUEUE_NAME},
        "app.tasks.content_tasks.process_paper_content_task": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.content_tasks.download_pdf_task": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.content_tasks.extract_pdf_text_task": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.content_tasks.build_embedding_task": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.content_tasks.finalize_paper_processing_task": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.process_pdf_backlog": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.retry_failed_content": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.rebuild_embeddings": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.reindex_vector_store": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.rebuild_vector_store_full": {"queue": settings.CONTENT_QUEUE_NAME},
        "app.tasks.dashboard.rebuild_rag_index": {"queue": settings.CONTENT_QUEUE_NAME},
    },
)

if _is_celery_cli_process():
    logger.info(
        "Celery app configured: service={}, qwen_gateway={}, modules={}, broker={}, result_backend={}",
        SERVICE_NAME,
        IS_QWEN_GATEWAY_WORKER,
        TASK_MODULES,
        settings.CELERY_BROKER_URL,
        settings.CELERY_RESULT_BACKEND,
    )
else:
    logger.debug(
        "Celery app imported by non-Celery process: service={}, modules={}",
        SERVICE_NAME,
        TASK_MODULES,
    )


def _short_task_id(task_id: str | None) -> str:
    if not task_id:
        return "unknown"
    return str(task_id)[:8]


@task_prerun.connect
def task_prerun_handler(task_id=None, task=None, *args, **kwargs):
    task_name = getattr(task, "name", "unknown")
    logger.info("Celery task started: name={} id={}", task_name, _short_task_id(task_id))


@task_postrun.connect
def task_postrun_handler(task_id=None, task=None, *args, **kwargs):
    task_name = getattr(task, "name", "unknown")
    state = kwargs.get("state") or "unknown"
    logger.info("Celery task finished: name={} id={} state={}", task_name, _short_task_id(task_id), state)
