"""Request security helpers for mutable qwen_service endpoints."""

from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


def create_service_security() -> HTTPBearer:
    """Create optional bearer security dependency for service endpoints."""
    return HTTPBearer(auto_error=False)


def _normalized_api_key(api_key: str | None) -> str:
    return str(api_key or "").strip()


def _provided_bearer(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or not credentials.credentials:
        return ""
    return credentials.credentials.strip()


def verify_service_token(
    credentials: HTTPAuthorizationCredentials | None,
    api_key: str | None,
    *,
    allow_unauth_without_api_key: bool = False,
) -> bool:
    """Return whether a request is allowed to call protected service endpoints.

    Empty ``QWEN_API_KEY`` no longer means "allow everyone" by accident.  For
    local diagnostics without a service key, set
    ``QWEN_ALLOW_UNAUTH_WITHOUT_API_KEY=true`` explicitly.
    """
    expected = _normalized_api_key(api_key)
    if not expected:
        return bool(allow_unauth_without_api_key)
    provided = _provided_bearer(credentials)
    if not provided:
        return False
    return compare_digest(provided, expected)


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None,
    api_key: str | None,
    *,
    allow_unauth_without_api_key: bool = False,
) -> None:
    """Raise 401 when the qwen_service API key is missing or does not match."""
    expected = _normalized_api_key(api_key)
    if verify_service_token(
        credentials,
        expected,
        allow_unauth_without_api_key=allow_unauth_without_api_key,
    ):
        return
    if not expected:
        raise HTTPException(
            status_code=401,
            detail=(
                "QWEN_API_KEY не настроен. Укажите ключ в .env или явно включите "
                "QWEN_ALLOW_UNAUTH_WITHOUT_API_KEY=true только для локальной диагностики."
            ),
        )
    raise HTTPException(status_code=401, detail="Неверный API ключ")
