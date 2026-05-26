"""Utilities for Qwen token diagnostics and HAR token extraction.

The functions in this module never log or return token values unless the caller
explicitly asks for the token field. API endpoints must redact it from responses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

QWEN_TOKEN_EXPIRED_MARKERS = (
    "token has expired",
    "please log in again",
    "login again",
    "token expired",
    "qwen_token_expired",
    "unauthorized",
    "not logged in",
    "登录",
)

QWEN_TOKEN_INVALID_MARKERS = (
    "invalid token",
    "bad token",
    "authentication failed",
    "forbidden",
)


def normalize_token(raw: str | None) -> str:
    text = str(raw or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return "".join(text.split())


def mask_token(token: str | None) -> str:
    normalized = normalize_token(token)
    if not normalized:
        return ""
    if len(normalized) <= 12:
        return "***"
    return f"{normalized[:6]}...{normalized[-6:]}"


def is_qwen_auth_expired_message(message: str | None) -> bool:
    value = str(message or "").lower()
    return any(marker in value for marker in QWEN_TOKEN_EXPIRED_MARKERS)


def is_qwen_auth_invalid_message(message: str | None) -> bool:
    value = str(message or "").lower()
    return any(marker in value for marker in QWEN_TOKEN_INVALID_MARKERS)


def classify_qwen_auth_message(message: str | None) -> str | None:
    if is_qwen_auth_expired_message(message):
        return "expired"
    if is_qwen_auth_invalid_message(message):
        return "invalid"
    return None


def qwen_auth_status_from_error(message: str | None) -> dict[str, Any]:
    code = classify_qwen_auth_message(message) or "error"
    return {
        "status": code,
        "valid": False,
        "expired": code == "expired",
        "token_configured": True,
        "message": "Токен Qwen истёк. Обновите QWEN_TOKEN." if code == "expired" else str(message or "Ошибка проверки Qwen токена"),
    }


def _is_qwen_url(url: str) -> bool:
    try:
        host = str(urlparse(str(url or "")).netloc or "").lower()
    except Exception:
        return False
    return "chat.qwen.ai" in host


def _extract_bearer(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw.lower().startswith("bearer "):
        return ""
    return normalize_token(raw[7:])


def _extract_cookie_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for part in raw.split(";"):
        chunk = str(part or "").strip()
        if "=" not in chunk:
            continue
        key, val = chunk.split("=", 1)
        if str(key or "").strip().lower() != "token":
            continue
        token = normalize_token(val)
        if token:
            return token
    return ""


def _iter_entries(har_data: dict[str, Any]) -> list[dict[str, Any]]:
    entries = ((har_data.get("log") or {}).get("entries") or [])
    return entries if isinstance(entries, list) else []


@dataclass(frozen=True)
class QwenHarTokenCandidate:
    index: int
    started_at: str
    url: str
    token: str
    source: str

    def public_payload(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "started_at": self.started_at,
            "url": self.url,
            "source": self.source,
            "token_preview": mask_token(self.token),
        }


def find_qwen_tokens_in_har(har_data: dict[str, Any]) -> list[QwenHarTokenCandidate]:
    candidates: list[QwenHarTokenCandidate] = []

    for idx, entry in enumerate(_iter_entries(har_data)):
        if not isinstance(entry, dict):
            continue

        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url = str(request.get("url") or "")
        started_at = str(entry.get("startedDateTime") or "")

        if not _is_qwen_url(url):
            continue

        headers = request.get("headers") or []
        if isinstance(headers, list):
            for header in headers:
                if not isinstance(header, dict):
                    continue
                name = str(header.get("name") or "").lower()
                if name == "authorization":
                    token = _extract_bearer(header.get("value"))
                    if token:
                        candidates.append(QwenHarTokenCandidate(idx, started_at, url, token, "request.authorization"))
                elif name == "cookie":
                    token = _extract_cookie_token(header.get("value"))
                    if token:
                        candidates.append(QwenHarTokenCandidate(idx, started_at, url, token, "request.cookie.token"))

        response_headers = response.get("headers") or []
        if isinstance(response_headers, list):
            for header in response_headers:
                if not isinstance(header, dict):
                    continue
                if str(header.get("name") or "").lower() != "set-cookie":
                    continue
                token = _extract_cookie_token(header.get("value"))
                if token:
                    candidates.append(QwenHarTokenCandidate(idx, started_at, url, token, "response.set-cookie.token"))

        content = (response.get("content") or {}).get("text")
        if isinstance(content, str) and content.strip():
            try:
                body = json.loads(content)
            except Exception:
                body = None
            parsed_path = str(urlparse(url).path or "")
            if isinstance(body, dict) and parsed_path.startswith("/api/v1/auths"):
                token = normalize_token(body.get("token"))
                if token:
                    candidates.append(QwenHarTokenCandidate(idx, started_at, url, token, "response.auths.token"))

    return candidates


def pick_latest_qwen_token(candidates: list[QwenHarTokenCandidate]) -> QwenHarTokenCandidate | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.index)


def load_har_from_bytes(content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("HAR файл пустой")
    try:
        return json.loads(content.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать HAR JSON: {exc}") from exc


def extract_latest_qwen_token_from_har_bytes(content: bytes) -> tuple[str, dict[str, Any]]:
    har_data = load_har_from_bytes(content)
    candidates = find_qwen_tokens_in_har(har_data)
    latest = pick_latest_qwen_token(candidates)
    if latest is None:
        raise ValueError("Qwen токен не найден в HAR файле")
    unique_count = len(dict.fromkeys(item.token for item in candidates))
    meta = latest.public_payload()
    meta.update({"candidates_count": len(candidates), "unique_tokens_count": unique_count})
    return latest.token, meta
