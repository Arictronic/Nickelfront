from app.core.config import settings
from redis import Redis

CANCEL_TTL_SECONDS = 24 * 60 * 60


def _cancel_key(task_id: str) -> str:
    return f"celery:cancel:{task_id}"


def _get_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL)


def set_cancel_flag(task_id: str) -> None:
    try:
        _get_client().setex(_cancel_key(task_id), CANCEL_TTL_SECONDS, "1")
    except Exception:
        # If Redis is unavailable, do not break API calls
        pass


def clear_cancel_flag(task_id: str) -> None:
    try:
        _get_client().delete(_cancel_key(task_id))
    except Exception:
        pass


def is_cancelled(task_id: str) -> bool:
    try:
        return _get_client().exists(_cancel_key(task_id)) == 1
    except Exception:
        return False
