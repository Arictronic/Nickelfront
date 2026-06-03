"""Qwen HAR token scanner.

This module belongs to qwen_service because HAR parsing and QWEN_TOKEN
application are part of Qwen provider authentication, not backend business
logic. It never logs token values by default; callers should return only masked
previews.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import set_key


QWEN_HAR_EXPORT_INSTRUCTIONS = """
Как получить HAR-файл с актуальным Qwen token и browser-session headers:

1. Откройте https://chat.qwen.ai.
2. Выйдите из аккаунта Qwen, если уже авторизованы.
3. Откройте инструменты разработчика в браузере:
   - Chrome / Edge: F12 или Ctrl+Shift+I.
4. Перейдите во вкладку Network / Сеть.
5. Включите Preserve log / Сохранять журнал, если такая опция есть.
6. Не закрывая вкладку Network, войдите в аккаунт Qwen.
7. После успешного входа нажмите правой кнопкой по списку запросов во вкладке Network.
8. Выберите Save all as HAR with content / Сохранить все как HAR с содержимым.
9. Для файлового pipeline ОБЯЗАТЕЛЬНО загрузите маленький .txt/.pdf файл
   прямо на сайте Qwen и дождитесь завершения обработки файла.
10. Проверьте, что в HAR есть запросы /api/v2/files/getstsToken,
   /api/v2/files/parse или /api/v2/files/parse/status.
   HAR только с /api/v2/chats/* подходит для текста, но не для загрузки файлов.
10. Передайте этот .har файл в qwen_service/har_token_scanner.py или загрузите его в настройках Nickelfront.

Важно:
- HAR может содержать cookies и токены авторизации. Не отправляйте его посторонним.
- После обновления токена храните HAR как секрет или удалите файл.
""".strip()


def print_har_export_instructions() -> None:
    print(QWEN_HAR_EXPORT_INSTRUCTIONS)


def normalize_token(raw: Any) -> str:
    text = str(raw or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return "".join(text.split())


def mask_token(token: Any) -> str:
    value = normalize_token(token)
    if not value:
        return ""
    if len(value) <= 14:
        return "***"
    return f"{value[:8]}...{value[-6:]}"


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


def _headers_list_to_dict(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(headers, list):
        return result
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name") or "").strip().lower()
        value = str(header.get("value") or "").strip()
        if name and value:
            result[name] = value
    return result


def _compact_json(value: Any, *, max_chars: int = 12000) -> str:
    """Serialize small HAR-derived templates for runtime env/config storage."""
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""
    if len(text) > max_chars:
        return ""
    return text


def _extract_json_post_data(request: dict[str, Any]) -> Any:
    post_data = request.get("postData") or {}
    if not isinstance(post_data, dict):
        return None
    text = post_data.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if not (raw.startswith("{") or raw.startswith("[")):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


_FILE_EXTRA_HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "priority",
    "x-request-id",
    "x-requested-with",
    "x-platform",
    "x-client",
    "x-client-type",
    "x-device-id",
    "x-app-id",
    "x-app-version",
}

_FILE_EXTRA_HEADER_DENYLIST = {
    "authorization",
    "cookie",
    "host",
    "content-length",
    "connection",
    "x-xsrf-token",
    "bx-ua",
    "bx-umidtoken",
    "bx-v",
    "user-agent",
}

_OSS_PUT_HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
    "cache-control",
    "content-disposition",
    "content-encoding",
    "content-language",
    "content-md5",
    "content-type",
    "expires",
    "origin",
    "pragma",
    "referer",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
}

_OSS_PUT_HEADER_DENYLIST = {
    "authorization",
    "cookie",
    "host",
    "content-length",
    "connection",
    "proxy-authorization",
}


def _safe_file_extra_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return non-secret browser headers that can matter for Qwen file API."""
    result: dict[str, str] = {}
    for name, value in (headers or {}).items():
        key = str(name or "").strip().lower()
        val = str(value or "").strip()
        if not key or not val:
            continue
        if key in _FILE_EXTRA_HEADER_DENYLIST:
            continue
        if key in _FILE_EXTRA_HEADER_ALLOWLIST or key.startswith("sec-") or key.startswith("x-"):
            result[key] = val
    return result


def _safe_oss_put_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a non-secret OSS PUT header template captured from the browser.

    Aliyun pre-signed PUT URLs can be sensitive to the exact browser request
    shape. We keep only stable, non-secret headers and let qwen_api remove
    any query-duplicated x-oss-* headers for the fresh signed URL.
    """
    result: dict[str, str] = {}
    for name, value in (headers or {}).items():
        key = str(name or "").strip().lower()
        val = str(value or "").strip()
        if not key or not val:
            continue
        if key in _OSS_PUT_HEADER_DENYLIST:
            continue
        if key in _OSS_PUT_HEADER_ALLOWLIST or key.startswith("x-oss-") or key.startswith("sec-"):
            result[key] = val
    return result


def _is_oss_put_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        host = str(parsed.netloc or "").lower()
    except Exception:
        return False
    return bool(host and "aliyuncs.com" in host and ".oss" in host)


def _is_qwen_file_sts_path(url: str) -> bool:
    try:
        path = str(urlparse(str(url or "")).path or "")
    except Exception:
        return False
    return path.endswith("/api/v2/files/getstsToken") or path.endswith("/files/getstsToken")


def _is_qwen_file_parse_path(url: str) -> bool:
    try:
        path = str(urlparse(str(url or "")).path or "")
    except Exception:
        return False
    return path.endswith("/api/v2/files/parse") or path.endswith("/files/parse")


def _is_qwen_file_parse_status_path(url: str) -> bool:
    try:
        path = str(urlparse(str(url or "")).path or "")
    except Exception:
        return False
    return path.endswith("/api/v2/files/parse/status") or path.endswith("/files/parse/status")


def _is_file_relevant_path(url: str) -> bool:
    try:
        path = str(urlparse(str(url or "")).path or "")
    except Exception:
        return False
    return any(
        marker in path
        for marker in (
            "/api/v2/files/",
            "/api/v2/chat/completions",
            "/api/v2/chats",
            "/api/user",
            "/api/models",
        )
    )


def _is_qwen_file_api_path(url: str) -> bool:
    try:
        path = str(urlparse(str(url or "")).path or "")
    except Exception:
        return False
    return "/api/v2/files/" in path


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

    def public_meta(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "started_at": self.started_at,
            "url": self.url,
            "source": self.source,
            "token_preview": mask_token(self.token),
        }


@dataclass(frozen=True)
class QwenHarSessionCandidate:
    index: int
    started_at: str
    url: str
    token: str = ""
    cookie: str = ""
    bx_ua: str = ""
    bx_umidtoken: str = ""
    bx_v: str = ""
    user_agent: str = ""
    file_api_extra_headers_json: str = ""
    file_sts_payload_template_json: str = ""
    file_sts_url: str = ""
    file_parse_payload_template_json: str = ""
    file_parse_url: str = ""
    file_parse_status_payload_template_json: str = ""
    file_parse_status_url: str = ""
    source: str = "request.headers"

    def score(self) -> int:
        score = 0
        for value in (self.cookie, self.bx_ua, self.bx_umidtoken, self.bx_v):
            if value:
                score += 10
        if self.token:
            score += 3
        if "/api/v2/files/" in self.url:
            score += 50
        elif "/api/v2/chat/completions" in self.url:
            score += 8
        return score

    def public_meta(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "started_at": self.started_at,
            "url": self.url,
            "source": self.source,
            "score": self.score(),
            "has_token": bool(self.token),
            "has_cookie": bool(self.cookie),
            "has_bx_ua": bool(self.bx_ua),
            "has_bx_umidtoken": bool(self.bx_umidtoken),
            "has_bx_v": bool(self.bx_v),
            "has_user_agent": bool(self.user_agent),
            "user_agent_len": len(self.user_agent or ""),
            "has_file_api_extra_headers": bool(self.file_api_extra_headers_json),
            "has_file_sts_payload_template": bool(self.file_sts_payload_template_json),
            "has_file_sts_url": bool(self.file_sts_url),
            "has_file_parse_payload_template": bool(self.file_parse_payload_template_json),
            "has_file_parse_url": bool(self.file_parse_url),
            "has_file_parse_status_payload_template": bool(self.file_parse_status_payload_template_json),
            "has_file_parse_status_url": bool(self.file_parse_status_url),
            "is_file_api_request": _is_qwen_file_api_path(self.url),
            "token_preview": mask_token(self.token),
        }

    def values(self) -> dict[str, str]:
        return {
            "token": self.token,
            "cookie": self.cookie,
            "bx_ua": self.bx_ua,
            "bx_umidtoken": self.bx_umidtoken,
            "bx_v": self.bx_v,
            "user_agent": self.user_agent,
            "file_api_extra_headers_json": self.file_api_extra_headers_json,
            "file_sts_payload_template_json": self.file_sts_payload_template_json,
            "file_sts_url": self.file_sts_url,
            "file_parse_payload_template_json": self.file_parse_payload_template_json,
            "file_parse_url": self.file_parse_url,
            "file_parse_status_payload_template_json": self.file_parse_status_payload_template_json,
            "file_parse_status_url": self.file_parse_status_url,
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

            if isinstance(body, dict):
                parsed_path = str(urlparse(url).path or "")
                if parsed_path.startswith("/api/v1/auths"):
                    token = normalize_token(body.get("token"))
                    if token:
                        candidates.append(QwenHarTokenCandidate(idx, started_at, url, token, "response.auths.token"))

    return candidates


def _extract_latest_file_request_template(har_data: dict[str, Any], predicate) -> dict[str, Any]:
    """Extract the newest browser file endpoint request template from HAR."""
    best: dict[str, Any] = {}
    for idx, entry in enumerate(_iter_entries(har_data)):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        if not isinstance(request, dict):
            continue
        url = str(request.get("url") or "")
        if not _is_qwen_url(url) or not predicate(url):
            continue
        headers = _headers_list_to_dict(request.get("headers") or [])
        payload = _extract_json_post_data(request)
        best = {
            "index": idx,
            "started_at": str(entry.get("startedDateTime") or ""),
            "url": url,
            "payload": payload if isinstance(payload, dict) else {},
            "extra_headers": _safe_file_extra_headers(headers),
        }
    return best


def _extract_latest_file_sts_template(har_data: dict[str, Any]) -> dict[str, Any]:
    return _extract_latest_file_request_template(har_data, _is_qwen_file_sts_path)


def _extract_latest_file_parse_template(har_data: dict[str, Any]) -> dict[str, Any]:
    return _extract_latest_file_request_template(har_data, _is_qwen_file_parse_path)


def _extract_latest_file_parse_status_template(har_data: dict[str, Any]) -> dict[str, Any]:
    return _extract_latest_file_request_template(har_data, _is_qwen_file_parse_status_path)


def _extract_latest_oss_put_template(har_data: dict[str, Any]) -> dict[str, Any]:
    """Extract the newest browser OSS PUT request headers from HAR."""
    best: dict[str, Any] = {}
    for idx, entry in enumerate(_iter_entries(har_data)):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        if not isinstance(request, dict):
            continue
        if str(request.get("method") or "").upper() != "PUT":
            continue
        url = str(request.get("url") or "")
        if not _is_oss_put_url(url):
            continue
        headers = _headers_list_to_dict(request.get("headers") or [])
        best = {
            "index": idx,
            "started_at": str(entry.get("startedDateTime") or ""),
            "url": url,
            "headers": _safe_oss_put_headers(headers),
        }
    return best


def find_qwen_sessions_in_har(
    har_data: dict[str, Any],
    *,
    require_file_api: bool = False,
) -> list[QwenHarSessionCandidate]:
    """Find browser-session header bundles required by Qwen file endpoints."""
    candidates: list[QwenHarSessionCandidate] = []
    sts_template = _extract_latest_file_sts_template(har_data)
    parse_template = _extract_latest_file_parse_template(har_data)
    parse_status_template = _extract_latest_file_parse_status_template(har_data)
    oss_put_template = _extract_latest_oss_put_template(har_data)


    merged_headers = {}
    for template in (parse_status_template, parse_template, sts_template):
        merged_headers.update(template.get("extra_headers") or {})
    sts_headers_json = _compact_json(merged_headers)
    sts_payload_json = _compact_json(sts_template.get("payload") or {})
    sts_url = str(sts_template.get("url") or "")
    parse_payload_json = _compact_json(parse_template.get("payload") or {})
    parse_url = str(parse_template.get("url") or "")
    parse_status_payload_json = _compact_json(parse_status_template.get("payload") or {})
    parse_status_url = str(parse_status_template.get("url") or "")
    for idx, entry in enumerate(_iter_entries(har_data)):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        url = str(request.get("url") or "")
        started_at = str(entry.get("startedDateTime") or "")
        if not _is_qwen_url(url) or not _is_file_relevant_path(url):
            continue
        if require_file_api and not _is_qwen_file_api_path(url):
            continue
        headers = _headers_list_to_dict(request.get("headers") or [])
        auth = headers.get("authorization") or ""
        token = _extract_bearer(auth) or _extract_cookie_token(headers.get("cookie"))
        extra_headers = _safe_file_extra_headers(headers)
        candidate = QwenHarSessionCandidate(
            index=idx,
            started_at=started_at,
            url=url,
            token=token,
            cookie=headers.get("cookie", ""),
            bx_ua=headers.get("bx-ua", ""),
            bx_umidtoken=headers.get("bx-umidtoken", ""),
            bx_v=headers.get("bx-v", ""),
            user_agent=headers.get("user-agent", ""),
            file_api_extra_headers_json=sts_headers_json or _compact_json(extra_headers),
            file_sts_payload_template_json=sts_payload_json,
            file_sts_url=sts_url,
            file_parse_payload_template_json=parse_payload_json,
            file_parse_url=parse_url,
            file_parse_status_payload_template_json=parse_status_payload_json,
            file_parse_status_url=parse_status_url,
        )
        if candidate.score() > 0:
            candidates.append(candidate)
    return candidates


def pick_latest_qwen_token(candidates: list[QwenHarTokenCandidate]) -> QwenHarTokenCandidate | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.index)


def pick_best_qwen_session(candidates: list[QwenHarSessionCandidate]) -> QwenHarSessionCandidate | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.score(), item.index))


def load_har_from_bytes(content: bytes) -> dict[str, Any]:
    if not content:
        raise ValueError("HAR-файл пустой.")
    try:
        return json.loads(content.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise ValueError(f"Ошибка чтения HAR: {exc}") from exc


def load_har_from_file(path: str | Path) -> dict[str, Any]:
    har_path = Path(path).expanduser()
    if not har_path.exists() or not har_path.is_file():
        raise ValueError(f"HAR-файл не найден: {har_path}")
    return load_har_from_bytes(har_path.read_bytes())


def extract_latest_qwen_token_from_har(har_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates = find_qwen_tokens_in_har(har_data)
    latest = pick_latest_qwen_token(candidates)
    if not latest:
        raise ValueError("Qwen токен не найден в HAR-файле.")

    unique_count = len(dict.fromkeys(item.token for item in candidates))
    meta = latest.public_meta()
    meta.update({"candidates_count": len(candidates), "unique_tokens_count": unique_count})
    return latest.token, meta


def extract_latest_qwen_session_from_har(
    har_data: dict[str, Any],
    *,
    require_file_api: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Extract token + browser session headers from a HAR.

    Returns values keyed as token/cookie/bx_ua/bx_umidtoken/bx_v/user_agent. At least one
    Qwen token or session header must be present; callers decide whether partial
    data is acceptable. For file upload, set require_file_api=True so a chat-only
    HAR is rejected instead of producing headers that pass /health but fail on
    /api/v2/files/getstsToken.
    """
    token_candidates = find_qwen_tokens_in_har(har_data)
    all_session_candidates = find_qwen_sessions_in_har(har_data)
    file_session_candidates = [item for item in all_session_candidates if _is_qwen_file_api_path(item.url)]
    session_candidates = file_session_candidates if require_file_api else all_session_candidates
    latest_token = pick_latest_qwen_token(token_candidates)
    best_session = pick_best_qwen_session(session_candidates)
    if require_file_api and not best_session:
        raise ValueError(
            "HAR-файл не содержит request headers от файловых endpoints Qwen. "
            "Откройте обычный Chrome, загрузите маленький файл на chat.qwen.ai, "
            "дождитесь обработки и экспортируйте HAR с запросами /api/v2/files/*."
        )
    if not latest_token and not best_session:
        raise ValueError("Qwen token/session headers не найдены в HAR-файле.")

    values = best_session.values() if best_session else {"token": "", "cookie": "", "bx_ua": "", "bx_umidtoken": "", "bx_v": "", "user_agent": "", "file_api_extra_headers_json": "", "file_sts_payload_template_json": "", "file_sts_url": "", "file_parse_payload_template_json": "", "file_parse_url": "", "file_parse_status_payload_template_json": "", "file_parse_status_url": ""}
    if latest_token and latest_token.token:
        values["token"] = latest_token.token
    meta = best_session.public_meta() if best_session else {}
    meta.update(
        {
            "session_candidates_count": len(all_session_candidates),
            "file_session_candidates_count": len(file_session_candidates),
            "selected_session_candidates_count": len(session_candidates),
            "token_candidates_count": len(token_candidates),
            "has_file_api_session": bool(file_session_candidates),
            "has_full_file_browser_session": bool(
                values.get("cookie") and values.get("bx_ua") and values.get("bx_umidtoken") and values.get("bx_v")
            ),
            "has_user_agent": bool(values.get("user_agent")),
            "user_agent_len": len(str(values.get("user_agent") or "")),
            "has_file_api_extra_headers": bool(values.get("file_api_extra_headers_json")),
            "file_api_extra_header_names": sorted((json.loads(values.get("file_api_extra_headers_json") or "{}") or {}).keys())
            if values.get("file_api_extra_headers_json")
            else [],
            "has_file_sts_payload_template": bool(values.get("file_sts_payload_template_json")),
            "file_sts_payload_keys": sorted((json.loads(values.get("file_sts_payload_template_json") or "{}") or {}).keys())
            if values.get("file_sts_payload_template_json")
            else [],
            "has_file_sts_url": bool(values.get("file_sts_url")),
            "has_file_parse_payload_template": bool(values.get("file_parse_payload_template_json")),
            "file_parse_payload_keys": sorted((json.loads(values.get("file_parse_payload_template_json") or "{}") or {}).keys())
            if values.get("file_parse_payload_template_json")
            else [],
            "has_file_parse_url": bool(values.get("file_parse_url")),
            "has_file_parse_status_payload_template": bool(values.get("file_parse_status_payload_template_json")),
            "file_parse_status_payload_keys": sorted((json.loads(values.get("file_parse_status_payload_template_json") or "{}") or {}).keys())
            if values.get("file_parse_status_payload_template_json")
            else [],
            "has_file_parse_status_url": bool(values.get("file_parse_status_url")),
            "token_source": latest_token.public_meta() if latest_token else None,
        }
    )
    return values, meta


def extract_latest_qwen_token_from_har_bytes(content: bytes) -> tuple[str, dict[str, Any]]:
    return extract_latest_qwen_token_from_har(load_har_from_bytes(content))


def extract_latest_qwen_session_from_har_bytes(
    content: bytes,
    *,
    require_file_api: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    return extract_latest_qwen_session_from_har(load_har_from_bytes(content), require_file_api=require_file_api)


def extract_latest_qwen_token_from_har_file(path: str | Path) -> tuple[str, dict[str, Any]]:
    return extract_latest_qwen_token_from_har(load_har_from_file(path))


def extract_latest_qwen_session_from_har_file(
    path: str | Path,
    *,
    require_file_api: bool = False,
) -> tuple[dict[str, str], dict[str, Any]]:
    return extract_latest_qwen_session_from_har(load_har_from_file(path), require_file_api=require_file_api)


def update_env_token(env_path: str | Path, token: str) -> None:
    normalized = normalize_token(token)
    if not normalized:
        raise ValueError("Qwen токен пустой.")
    path = Path(env_path).expanduser()
    if not path.exists():
        path.touch()
    set_key(str(path), "QWEN_TOKEN", normalized)


def update_env_session(env_path: str | Path, values: dict[str, str]) -> None:
    path = Path(env_path).expanduser()
    if not path.exists():
        path.touch()
    mapping = {
        "token": "QWEN_TOKEN",
        "cookie": "QWEN_COOKIE",
        "bx_ua": "QWEN_BX_UA",
        "bx_umidtoken": "QWEN_BX_UMIDTOKEN",
        "bx_v": "QWEN_BX_V",
        "user_agent": "QWEN_USER_AGENT",
        "file_api_extra_headers_json": "QWEN_FILE_API_EXTRA_HEADERS_JSON",
        "file_sts_payload_template_json": "QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON",
        "file_sts_url": "QWEN_FILE_STS_URL",
        "file_parse_payload_template_json": "QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON",
        "file_parse_url": "QWEN_FILE_PARSE_URL",
        "file_parse_status_payload_template_json": "QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON",
        "file_parse_status_url": "QWEN_FILE_PARSE_STATUS_URL",
    }
    for key, env_name in mapping.items():
        value = str(values.get(key) or "").strip()
        if not value:
            continue
        if key == "token":
            value = normalize_token(value)
        set_key(str(path), env_name, value)


def push_token_to_service(
    token: str,
    *,
    base_url: str = "http://127.0.0.1:8767",
    api_key: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    normalized = normalize_token(token)
    if not normalized:
        raise ValueError("Qwen токен пустой.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.post(f"{base_url.rstrip('/')}/config/token", headers=headers, json={"token": normalized})
        response.raise_for_status()
        return response.json()


def check_service_token_status(
    *,
    base_url: str = "http://127.0.0.1:8767",
    api_key: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.get(f"{base_url.rstrip('/')}/auth/status", headers=headers)
        response.raise_for_status()
        return response.json()


def _build_service_url() -> str:
    return f"http://{os.getenv('QWEN_SERVICE_HOST', '127.0.0.1')}:{os.getenv('QWEN_SERVICE_PORT', '8767')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract and apply Qwen token from chat.qwen.ai HAR file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=QWEN_HAR_EXPORT_INSTRUCTIONS,
    )
    parser.add_argument("har", nargs="?", help="Path to chat.qwen.ai HAR file")
    parser.add_argument("--apply", action="store_true", help="Write extracted token/session headers to .env")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / ".env"), help="Path to .env")
    parser.add_argument("--push-service", action="store_true", help="Apply token to running qwen_service via /config/token")
    parser.add_argument("--validate", action="store_true", help="Validate token through qwen_service /auth/status after update")
    parser.add_argument("--service-url", default=_build_service_url(), help="Qwen service URL")
    parser.add_argument("--api-key", default=os.getenv("QWEN_API_KEY", ""), help="Qwen service API key")
    parser.add_argument("--print-token", action="store_true", help="Print full token. Avoid using this in shared logs.")
    parser.add_argument("--instructions", action="store_true", help="Show instructions for exporting HAR from chat.qwen.ai and exit")
    parser.add_argument("--no-instructions", action="store_true", help="Do not print instructions before interactive path prompt")
    parser.add_argument("--require-file-api", action="store_true", help="Reject HAR files without /api/v2/files/* requests")
    args = parser.parse_args(argv)

    if args.instructions:
        print_har_export_instructions()
        return 0

    if not args.har and not args.no_instructions:
        print_har_export_instructions()
        print()

    har_path = args.har or input("Введите путь к HAR-файлу: ").strip().strip('"')
    if not har_path:
        print("Ошибка: путь не указан.")
        return 1

    try:
        values, meta = extract_latest_qwen_session_from_har_file(har_path, require_file_api=args.require_file_api)
        token = values.get("token", "")
    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 2

    print("Qwen token/session данные найдены.")
    print(f"Токен: {token if args.print_token else mask_token(token)}")
    print(f"Источник: {meta.get('source')}")
    print(f"URL: {meta.get('url')}")
    print(f"Время: {meta.get('started_at')}")
    print(f"Кандидатов token: {meta.get('token_candidates_count')}")
    print(f"Кандидатов session: {meta.get('session_candidates_count')}")
    print(f"Кандидатов file session: {meta.get('file_session_candidates_count')}")
    print(f"Cookie: {'есть' if values.get('cookie') else 'нет'}")
    print(f"bx-ua: {'есть' if values.get('bx_ua') else 'нет'}")
    print(f"bx-umidtoken: {'есть' if values.get('bx_umidtoken') else 'нет'}")
    print(f"bx-v: {'есть' if values.get('bx_v') else 'нет'}")
    print(f"User-Agent: {'есть' if values.get('user_agent') else 'нет'}")

    if args.apply:
        try:
            update_env_session(args.env, values)
            print(f"QWEN_TOKEN/QWEN_COOKIE/QWEN_BX_*/QWEN_USER_AGENT/QWEN_FILE_* обновлены в {Path(args.env).expanduser()}")
        except Exception as exc:
            print(f"Ошибка записи .env: {exc}")
            return 3

    if args.push_service:
        try:
            result = push_token_to_service(token, base_url=args.service_url, api_key=args.api_key)
            print(f"Токен применён в qwen_service: {result.get('status', 'ok')}")
        except Exception as exc:
            print(f"Ошибка применения токена в qwen_service: {exc}")
            return 4

    if args.validate:
        try:
            status = check_service_token_status(base_url=args.service_url, api_key=args.api_key)
            print(f"Проверка токена: {status.get('status')} — {status.get('message')}")
            return 0 if status.get("valid") else 5
        except Exception as exc:
            print(f"Ошибка проверки токена: {exc}")
            return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
