"""
Autonomous Qwen API Client - No external dependencies
Fully self-contained implementation for qwen_service
"""

from __future__ import annotations

import json
import hashlib
import hmac
import mimetypes
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, urlparse
from uuid import uuid4

import requests


class QwenProviderError(RuntimeError):
    """Base provider-level error for Qwen chat API."""


class QwenRequestEndedError(QwenProviderError):
    """Raised when provider reports that the stream/request is already ended."""


class QwenChatInProgressError(QwenProviderError):
    """Raised when provider reports the chat is still in progress."""


class QwenInternalStreamError(QwenProviderError):
    """Raised when provider reports internal stream error."""



def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def _env_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on", "вкл"}:
        return True
    if value in {"0", "false", "no", "off", "выкл"}:
        return False
    return default


def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _env_json_dict(name: str) -> dict[str, Any]:
    raw = _env_str(name)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}





@dataclass
class StreamCallbacks:
    on_parts: Callable[[str, str], None] | None = None
    on_meta: Callable[[dict[str, Any]], None] | None = None
    on_complete_parts: Callable[[str, str], None] | None = None
    on_error: Callable[[str], None] | None = None


@dataclass
class SendRequest:
    session_id: str
    prompt: str
    ref_file_ids: list[str] = field(default_factory=list)
    thinking_enabled: bool = False
    search_enabled: bool = False
    preempt: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ContinueRequest:
    session_id: str
    message_id: int
    fallback_to_resume: bool = True






class QwenSseParser:
    """Parser for Qwen SSE stream responses"""

    @staticmethod
    def _extract_thinking_text(delta: dict[str, Any]) -> str:
        extra = delta.get("extra") or {}
        if not isinstance(extra, dict):
            return ""

        thought = extra.get("summary_thought") or {}
        if not isinstance(thought, dict):
            return ""

        content = thought.get("content")
        if isinstance(content, list):
            return " ".join(str(part) for part in content if part).strip()
        if isinstance(content, str):
            return content.strip()
        return ""

    def parse(
        self,
        resp: requests.Response,
        thinking_enabled: bool,
        on_parts: Callable[[str, str], None] | None = None,
        on_complete_parts: Callable[[str, str], None] | None = None,
        on_meta: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        def _raise_provider_error_payload(data: dict[str, Any]) -> None:
            if not isinstance(data, dict):
                return


            error_text = str(data.get("error") or "").strip()
            if error_text:
                lower = error_text.lower()
                if "request is ended" in lower:
                    raise QwenRequestEndedError(error_text)
                if "in progress" in lower or "chat is in progress" in lower:
                    raise QwenChatInProgressError(error_text)
                if "internal error" in lower:
                    raise QwenInternalStreamError(error_text)
                raise QwenProviderError(error_text)


            if data.get("success") is False:
                details_obj = data.get("data") or {}
                details = str(details_obj.get("details") or details_obj.get("message") or "").strip()
                code = str(details_obj.get("code") or "").strip()
                msg = details or code or "provider returned unsuccessful response"
                lower = msg.lower()
                if "request is ended" in lower:
                    raise QwenRequestEndedError(msg)
                if "in progress" in lower or "chat is in progress" in lower:
                    raise QwenChatInProgressError(msg)
                if "internal error" in lower:
                    raise QwenInternalStreamError(msg)
                raise QwenProviderError(msg)

        think_parts: list[str] = []
        response_parts: list[str] = []
        meta: dict[str, Any] = {}
        response_id: str | None = None
        response_status: str = "FINISHED"

        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8", errors="ignore").strip()
                data_str = line_str[5:].strip() if line_str.startswith("data:") else line_str
                if not data_str or data_str == "[DONE]":
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                _raise_provider_error_payload(data)


                if "id" in data and not response_id:
                    response_id = data["id"]
                created_meta = data.get("response.created")
                if isinstance(created_meta, dict):
                    response_id = response_id or created_meta.get("response_id")
                    parent_id = created_meta.get("parent_id")
                    if parent_id:
                        meta["parent_id"] = parent_id


                choices = data.get("choices") or []
                for choice in choices:
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    phase = str(delta.get("phase") or "")


                    reasoning = delta.get("reasoning_content")
                    if not reasoning and phase.startswith("thinking"):
                        reasoning = self._extract_thinking_text(delta) or content
                    if reasoning:
                        think_parts.append(reasoning)
                        if on_parts:
                            on_parts("\n\n".join(think_parts), "".join(response_parts))

                    if content and not phase.startswith("thinking"):
                        response_parts.append(content)
                        if on_parts:
                            on_parts("\n\n".join(think_parts), "".join(response_parts))


                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        response_status = "FINISHED" if finish_reason == "stop" else finish_reason


                if "usage" in data:
                    meta["usage"] = data["usage"]
                if "thinking_enabled" in data:
                    meta["thinking_enabled"] = data["thinking_enabled"]

            meta["response_id"] = response_id
            meta["response_status"] = response_status
            meta["can_continue"] = response_status == "length"


            final_think = "\n\n".join(think_parts).strip()
            final_response = "".join(response_parts).strip()

            if on_meta:
                on_meta(meta)

            if on_complete_parts:
                on_complete_parts(final_think, final_response)

        except Exception as e:
            if on_error:
                on_error(f"SSE parsing error: {e}")
            raise

        return final_think, final_response, meta






class QwenTransport:
    """HTTP transport for Qwen API"""

    BASE_URL = "https://chat.qwen.ai/api/v2"
    CHAT_URL = f"{BASE_URL}/chat/completions"
    CHATS_URL = f"{BASE_URL}/chats"
    CHATS_NEW_URL = f"{CHATS_URL}/new"
    FILE_STS_URL = f"{BASE_URL}/files/getstsToken"
    FILE_PARSE_URL = f"{BASE_URL}/files/parse"
    FILE_PARSE_STATUS_URL = f"{BASE_URL}/files/parse/status"

    def __init__(
        self,
        token: str,
        logger: Callable[[str], None] | None = None,
        proxy_config: dict[str, Any] | None = None,
        user_agent: str | None = None,
        connect_timeout: float = 30.0,
        stream_read_timeout: float = 300.0,
    ):
        self.token = token.strip()
        self.logger = logger
        self.proxy_config = proxy_config
        self.user_agent = user_agent or _env_str(
            "QWEN_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        self.connect_timeout = float(connect_timeout)
        self.stream_read_timeout = float(stream_read_timeout)
        self.session = requests.Session()
        self.session.headers.update(self._get_headers())

        if proxy_config:
            self._setup_proxy(proxy_config)

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://chat.qwen.ai",
            "Referer": "https://chat.qwen.ai/",
            "User-Agent": self.user_agent,
            "X-Xsrf-Token": self.token,
            "Authorization": f"Bearer {self.token}",
        }
        return headers

    def _get_browser_session_headers(self) -> dict[str, str]:
        """Browser-session headers required by Qwen file endpoints.

        Text chat can work with Bearer/XSRF only, while the file pipeline is
        guarded by the browser session layer. Values are intentionally read from
        os.environ at request time so Playwright/HAR refresh can update them
        without recreating every QwenAPI object first.
        """
        mapping = {
            "Cookie": _env_str("QWEN_COOKIE"),
            "bx-ua": _env_str("QWEN_BX_UA"),
            "bx-umidtoken": _env_str("QWEN_BX_UMIDTOKEN"),
            "bx-v": _env_str("QWEN_BX_V"),
        }
        return {key: value for key, value in mapping.items() if value}

    def _get_file_api_extra_headers(self) -> dict[str, str]:
        """Non-secret browser headers captured from the HAR file endpoint."""
        raw = _env_json_dict("QWEN_FILE_API_EXTRA_HEADERS_JSON")
        result: dict[str, str] = {}
        deny = {"authorization", "cookie", "host", "content-length", "connection", "x-xsrf-token", "bx-ua", "bx-umidtoken", "bx-v", "user-agent"}
        for name, value in raw.items():
            key = str(name or "").strip()
            val = str(value or "").strip()
            if not key or not val:
                continue
            if key.lower() in deny:
                continue
            result[key] = val
        return result

    def has_browser_session_headers(self) -> bool:
        headers = self._get_browser_session_headers()
        return all(headers.get(name) for name in ("Cookie", "bx-ua", "bx-umidtoken", "bx-v"))

    def _file_header_summary(self, headers: dict[str, str] | None = None) -> dict[str, Any]:
        values = headers or self._get_file_api_headers()
        return {
            "has_cookie": bool(values.get("Cookie")),
            "cookie_len": len(values.get("Cookie", "") or ""),
            "has_bx_ua": bool(values.get("bx-ua")),
            "bx_ua_len": len(values.get("bx-ua", "") or ""),
            "has_bx_umidtoken": bool(values.get("bx-umidtoken")),
            "bx_umidtoken_len": len(values.get("bx-umidtoken", "") or ""),
            "has_bx_v": bool(values.get("bx-v")),
            "bx_v_len": len(values.get("bx-v", "") or ""),
            "has_user_agent": bool(values.get("User-Agent")),
            "user_agent_len": len(values.get("User-Agent", "") or ""),
            "has_authorization": bool(values.get("Authorization")),
            "extra_header_count": len(self._get_file_api_extra_headers()),
            "extra_header_names": sorted(self._get_file_api_extra_headers().keys()),
        }

    def _get_file_api_headers(self) -> dict[str, str]:



        headers = self._get_headers()
        headers.update(self._get_file_api_extra_headers())
        headers.update(self._get_browser_session_headers())
        headers["User-Agent"] = self.user_agent
        headers["Authorization"] = f"Bearer {self.token}"
        headers["X-Xsrf-Token"] = self.token
        headers.setdefault("Origin", "https://chat.qwen.ai")
        headers.setdefault("Referer", "https://chat.qwen.ai/")
        headers.setdefault("Content-Type", "application/json")
        return headers

    @staticmethod
    def _extract_recursive(data: Any, aliases: set[str]) -> Any:
        if isinstance(data, dict):
            lowered = {str(key).lower(): value for key, value in data.items()}
            for alias in aliases:
                if alias.lower() in lowered:
                    value = lowered[alias.lower()]
                    if value not in (None, ""):
                        return value
            for value in data.values():
                found = QwenTransport._extract_recursive(value, aliases)
                if found not in (None, ""):
                    return found
        elif isinstance(data, list):
            for item in data:
                found = QwenTransport._extract_recursive(item, aliases)
                if found not in (None, ""):
                    return found
        return None

    def _normalize_upload_ticket(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize Qwen getstsToken variants observed in browser HARs."""
        data = dict(raw or {})
        file_id = self._extract_recursive(data, {"file_id", "fileId", "id"})
        file_url = self._extract_recursive(data, {"file_url", "fileUrl", "url", "upload_url", "uploadUrl", "oss_url", "ossUrl"})
        object_key = self._extract_recursive(data, {"file_path", "filePath", "object_key", "objectKey", "key", "oss_key", "ossKey", "path"})
        bucket = self._extract_recursive(data, {"bucketname", "bucket_name", "bucketName", "bucket"})
        region = self._extract_recursive(data, {"region", "region_id", "regionId"})
        endpoint = self._extract_recursive(data, {"endpoint", "oss_endpoint", "ossEndpoint", "host"})
        access_key_id = self._extract_recursive(data, {"access_key_id", "accessKeyId", "AccessKeyId", "accessid", "accessId"})
        access_key_secret = self._extract_recursive(
            data,
            {"access_key_secret", "accessKeySecret", "AccessKeySecret", "access_key", "AccessKeySecret"},
        )
        security_token = self._extract_recursive(
            data,
            {"security_token", "securityToken", "SecurityToken", "sts_token", "stsToken", "token"},
        )

        if file_id:
            data["file_id"] = str(file_id).strip()
        if file_url:
            data["file_url"] = str(file_url).strip()
        if object_key:
            data["object_key"] = str(object_key).strip()
        if bucket:
            data["bucket"] = str(bucket).strip()
        if region:
            data["region"] = str(region).strip()
        if endpoint:
            data["endpoint"] = str(endpoint).strip()
        if access_key_id:
            data["access_key_id"] = str(access_key_id).strip()
        if access_key_secret:
            data["access_key_secret"] = str(access_key_secret).strip()
        if security_token:
            data["security_token"] = str(security_token).strip()
        return data

    @staticmethod
    def _is_file_auth_message(message: str) -> bool:
        lower = str(message or "").lower()
        return any(
            marker in lower
            for marker in (
                "auth_failed",
                "authentication failed",
                "unauthorized",
                "forbidden",
                "401",
                "403",
                "browser-session",
                "browser session",
                "qwen_token",
            )
        )

    def _extract_data(self, response_json: dict[str, Any]) -> Any:
        """Extract provider payload or raise an explicit provider error.

        Qwen may return HTTP 200 with a JSON envelope such as
        ``{"success": false, "data": {"code": "...", "details": "..."}}``.
        Treating that as normal data makes backend endpoints look successful
        while returning empty sessions/models/history. Convert it to a real
        provider error so callers can surface the reason.
        """
        if isinstance(response_json, dict):
            if response_json.get("success") is False:
                err = response_json.get("data") or response_json.get("error") or {}
                if isinstance(err, dict):
                    code = str(err.get("code") or "").strip()
                    details = str(err.get("details") or err.get("message") or "").strip()
                    message = details or code or "Qwen provider returned success=false"
                else:
                    message = str(err or "Qwen provider returned success=false").strip()
                self._log(f"Qwen API error: {message}")
                raise QwenProviderError(message)
            if "error" in response_json and response_json.get("error"):
                message = str(response_json.get("error") or "Qwen provider returned error").strip()
                self._log(f"Qwen API error: {message}")
                raise QwenProviderError(message)
            if "data" in response_json:
                return response_json.get("data")
        return response_json

    @staticmethod
    def _scrub_secretish_text(text: str, *, limit: int = 900) -> str:
        """Keep provider diagnostics useful without leaking signed URLs/tokens."""
        value = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        for marker in ("x-oss-security-token=", "x-oss-signature=", "x-oss-credential=", "Signature="):
            lower = value.lower()
            idx = lower.find(marker.lower())
            if idx >= 0:
                end = value.find("&", idx)
                if end < 0:
                    end = value.find(" ", idx)
                if end < 0:
                    end = min(len(value), idx + 220)
                value = value[:idx] + marker + "<redacted>" + value[end:]
        return value[:limit]

    def _extract_oss_error(self, resp: requests.Response) -> dict[str, str]:
        """Parse Aliyun OSS XML error responses without exposing signed URLs."""
        result: dict[str, str] = {"status": str(getattr(resp, "status_code", "") or "")}
        try:
            text = resp.text or ""
        except Exception:
            text = ""
        if not text.strip():
            return result
        try:
            root = ET.fromstring(text.encode("utf-8", errors="ignore"))
            for name in ("Code", "Message", "RequestId", "HostId", "EC", "RecommendDoc"):
                node = root.find(name)
                if node is not None and node.text:
                    key = name.lower()
                    result[key] = self._scrub_secretish_text(node.text, limit=260)
        except Exception:
            result["preview"] = self._scrub_secretish_text(text, limit=360)
        return result

    @staticmethod
    def _format_safe_kv(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("status", "code", "message", "requestid", "ec", "recommenddoc", "preview"):
            value = str(data.get(key) or "").strip()
            if value:
                parts.append(f"{key}={value}")
        return "; ".join(parts)

    def _safe_response_text(self, resp: requests.Response, limit: int = 800) -> str:
        """Return a short, token-safe response preview for diagnostics."""
        try:
            text = resp.text or ""
        except Exception:
            return ""

        return self._scrub_secretish_text(text, limit=limit)

    def _raise_for_bad_response(self, resp: requests.Response, *, operation: str) -> None:
        """Convert non-2xx provider responses into explicit provider errors.

        Without this guard, an HTML/JSON error page can be fed into the SSE parser,
        producing an empty answer that looks like a successful Qwen response.
        """
        if 200 <= int(resp.status_code) < 300:
            return

        preview = self._safe_response_text(resp)
        status = int(resp.status_code)
        message = f"Qwen provider {operation} failed with HTTP {status}"
        if preview:
            message = f"{message}: {preview}"

        lower = message.lower()
        op = str(operation or "")
        if op == "oss_file_put":
            oss_error = self._extract_oss_error(resp)
            detail = self._format_safe_kv(oss_error)
            if status in {401, 403}:
                raise QwenProviderError(
                    "qwen_oss_auth_failed: OSS rejected provider signed upload URL"
                    + (f"; {detail}" if detail else "")
                )
            raise QwenProviderError(
                f"qwen_oss_put_failed: OSS PUT failed with HTTP {status}"
                + (f"; {detail}" if detail else "")
            )
        if status in {401, 403}:
            if op == "files/getstsToken":
                raise QwenProviderError(
                    "qwen_file_sts_auth_failed: Qwen getstsToken rejected auth/session; "
                    "refresh HAR from a real /api/v2/files/getstsToken request and check Cookie/bx-*/User-Agent/templates"
                )
            if op == "files/parse":
                raise QwenProviderError(
                    "qwen_file_parse_auth_failed: Qwen files/parse rejected the uploaded file/session; "
                    "use HAR templates for QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON and QWEN_FILE_PARSE_URL"
                )
            if op == "files/parse/status":
                raise QwenProviderError(
                    "qwen_file_parse_status_auth_failed: Qwen files/parse/status rejected the uploaded file/session; "
                    "use HAR templates for QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON"
                )
            if op.startswith("files/"):
                raise QwenProviderError(
                    "qwen_file_auth_failed: Qwen file endpoint rejected auth; "
                    "check QWEN_COOKIE/QWEN_BX_UA/QWEN_BX_UMIDTOKEN/QWEN_BX_V/QWEN_USER_AGENT"
                )
            raise QwenProviderError("Qwen provider authentication failed; check QWEN_TOKEN")
        if status == 429 or "rate limit" in lower:
            raise QwenProviderError(message)
        if "model not found" in lower:
            raise QwenProviderError(message)
        raise QwenProviderError(message)

    def _setup_proxy(self, proxy_config: dict[str, Any]):
        """Configure proxy if provided"""
        proxy_url = proxy_config.get("url")
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}
            self.session.proxies.update(proxies)

    def _log(self, message: str):
        if callable(self.logger):
            try:
                self.logger(message)
            except Exception:
                pass

    def update_referer(self, session_id: str | None):
        """Update referer header with session"""
        if session_id:
            self.session.headers["Referer"] = f"https://chat.qwen.ai/c/{session_id}"

    def get_user_info(self) -> dict:
        """Get current user info"""
        url = "https://chat.qwen.ai/api/user"
        resp = self.session.get(url, timeout=30)
        self._raise_for_bad_response(resp, operation="get_user_info")
        return resp.json()

    def validate_token(self) -> bool:
        """Validate authentication token"""
        info = self.get_user_info()
        return bool(info.get("id"))

    def _reset_session_after_transport_error(self) -> None:
        """Recreate requests.Session after provider closes/reset TCP connection."""
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.headers.update(self._get_headers())
        if self.proxy_config:
            self._setup_proxy(self.proxy_config)

    def create_session(self, model: str = "qwen3.6-plus") -> str | None:
        """Create new chat session with retry for transient provider TCP resets.

        Parallel chat tests create several sessions at once. chat.qwen.ai can
        sporadically close one of those /chats/new connections with WinError
        10054 / ConnectionResetError. This is not a local qwen_service crash;
        retrying session creation on a fresh HTTP session is safe because no
        chat session id was returned yet.
        """
        attempts = _env_int("QWEN_CREATE_SESSION_ATTEMPTS", 3, min_value=1, max_value=10)
        retry_delay = _env_float("QWEN_CREATE_SESSION_RETRY_DELAY_SEC", 0.8, min_value=0.0, max_value=30.0)
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            payload = {
                "title": "New Chat",
                "models": [model],
                "chat_mode": "normal",
                "chat_type": "t2t",
                "timestamp": int(time.time() * 1000),
                "project_id": "",
            }

            try:
                resp = self.session.post(
                    self.CHATS_NEW_URL,
                    json=payload,
                    timeout=self.connect_timeout,
                )
                self._raise_for_bad_response(resp, operation="create_session")
                data = self._extract_data(resp.json())
                session_id = data.get("id") if isinstance(data, dict) else None
                if session_id:
                    self.update_referer(session_id)
                    return session_id
                last_error = QwenProviderError("Qwen provider did not return session id")

            except requests.exceptions.RequestException as exc:
                last_error = exc
                self._log(
                    f"Qwen create_session attempt {attempt}/{attempts} failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                self._reset_session_after_transport_error()

            except ValueError as exc:


                last_error = exc
                self._log(
                    f"Qwen create_session attempt {attempt}/{attempts} returned invalid JSON: {exc}"
                )
                self._reset_session_after_transport_error()

            except QwenProviderError as exc:
                last_error = exc
                msg = str(exc).lower()
                if "authentication failed" in msg or "qwen_token" in msg:
                    raise
                self._log(
                    f"Qwen create_session attempt {attempt}/{attempts} provider error: {exc}"
                )

            if attempt < attempts:
                time.sleep(retry_delay * attempt)

        raise QwenProviderError(
            f"Qwen create_session failed after {attempts} attempts: {last_error}"
        )

    def delete_session(self, session_id: str) -> bool:
        """Delete chat session"""
        url = f"{self.CHATS_URL}/{session_id}"
        resp = self.session.delete(url, timeout=30)
        self._raise_for_bad_response(resp, operation="delete_session")
        return resp.status_code == 200

    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title"""
        url = f"{self.CHATS_URL}/{session_id}"
        payload = {"title": title}
        resp = self.session.put(url, json=payload, timeout=30)
        self._raise_for_bad_response(resp, operation="update_session_title")
        return resp.status_code == 200

    def fetch_sessions_page(self, page: int = 1, exclude_project: bool = True) -> list[dict]:
        """Fetch list of sessions"""
        params = {"page": page}
        if exclude_project:
            params["exclude_project"] = "true"
        resp = self.session.get(f"{self.CHATS_URL}/", params=params, timeout=30)
        self._raise_for_bad_response(resp, operation="fetch_sessions")
        data = self._extract_data(resp.json())
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return items
        if isinstance(data, list):
            return data
        return []

    def fetch_chat(self, session_id: str) -> dict:
        """Fetch chat history"""
        url = f"{self.CHATS_URL}/{session_id}"
        resp = self.session.get(url, timeout=30)
        self._raise_for_bad_response(resp, operation="fetch_chat")
        data = self._extract_data(resp.json())
        if isinstance(data, dict):
            return data
        return {}

    def fetch_models(self) -> list[dict]:
        """Fetch available models"""
        url = "https://chat.qwen.ai/api/models"
        resp = self.session.get(url, timeout=30)
        self._raise_for_bad_response(resp, operation="fetch_models")
        data = resp.json()
        return data.get("models") or []

    @staticmethod
    def _is_safe_qwen_file_sts_url(url: str) -> bool:
        try:
            parsed = urlparse(str(url or ""))
        except Exception:
            return False
        host = str(parsed.netloc or "").lower()
        path = str(parsed.path or "")
        return "chat.qwen.ai" in host and path.endswith("/api/v2/files/getstsToken")

    def _get_file_sts_url(self) -> str:
        captured = _env_str("QWEN_FILE_STS_URL")
        return captured if self._is_safe_qwen_file_sts_url(captured) else self.FILE_STS_URL

    @staticmethod
    def _is_safe_qwen_file_parse_url(url: str, *, status: bool = False) -> bool:
        try:
            parsed = urlparse(str(url or ""))
        except Exception:
            return False
        host = str(parsed.netloc or "").lower()
        path = str(parsed.path or "")
        if "chat.qwen.ai" not in host:
            return False
        expected = "/api/v2/files/parse/status" if status else "/api/v2/files/parse"
        return path.endswith(expected)

    def _get_file_parse_url(self) -> str:
        captured = _env_str("QWEN_FILE_PARSE_URL")
        return captured if self._is_safe_qwen_file_parse_url(captured, status=False) else self.FILE_PARSE_URL

    def _get_file_parse_status_url(self) -> str:
        captured = _env_str("QWEN_FILE_PARSE_STATUS_URL")
        return captured if self._is_safe_qwen_file_parse_url(captured, status=True) else self.FILE_PARSE_STATUS_URL

    @staticmethod
    def _deepcopy_json_like(value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, ensure_ascii=False))
        except Exception:
            if isinstance(value, dict):
                return dict(value)
            if isinstance(value, list):
                return list(value)
            return value

    def _replace_payload_aliases_recursive(self, payload: Any, aliases: set[str], value: Any) -> int:
        alias_lower = {str(alias).lower() for alias in aliases}
        replaced = 0
        if isinstance(payload, dict):
            for key in list(payload.keys()):
                lowered = str(key).lower()
                if lowered in alias_lower:
                    payload[key] = value
                    replaced += 1
                else:
                    replaced += self._replace_payload_aliases_recursive(payload[key], aliases, value)
        elif isinstance(payload, list):
            for item in payload:
                replaced += self._replace_payload_aliases_recursive(item, aliases, value)
        return replaced

    def _replace_payload_list_aliases_recursive(self, payload: Any, aliases: set[str], values: list[Any]) -> int:
        alias_lower = {str(alias).lower() for alias in aliases}
        replaced = 0
        if isinstance(payload, dict):
            for key in list(payload.keys()):
                lowered = str(key).lower()
                if lowered in alias_lower:
                    payload[key] = list(values)
                    replaced += 1
                else:
                    replaced += self._replace_payload_list_aliases_recursive(payload[key], aliases, values)
        elif isinstance(payload, list):
            for item in payload:
                replaced += self._replace_payload_list_aliases_recursive(item, aliases, values)
        return replaced

    @staticmethod
    def _replace_payload_aliases(payload: dict[str, Any], aliases: set[str], value: Any) -> bool:
        replaced = False
        for key in list(payload.keys()):
            lowered = str(key).lower()
            if lowered in {alias.lower() for alias in aliases}:
                payload[key] = value
                replaced = True
        return replaced

    def _build_file_upload_ticket_payload(self, *, filename: str, filesize: int, filetype: str = "file") -> dict[str, Any]:
        template = _env_json_dict("QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON")
        payload = dict(template) if template else {}
        if not payload:
            payload = {"filename": filename, "filesize": int(filesize), "filetype": filetype or "file"}
            return payload

        if not self._replace_payload_aliases_recursive(payload, {"filename", "fileName", "name", "file_name"}, filename):
            payload.setdefault("filename", filename)
        if not self._replace_payload_aliases_recursive(payload, {"filesize", "fileSize", "size", "file_size"}, int(filesize)):
            payload.setdefault("filesize", int(filesize))
        self._replace_payload_aliases_recursive(payload, {"filetype", "fileType", "type", "file_type", "content_type", "contentType", "mime_type", "mimeType"}, filetype or "file")
        return payload

    def _payload_template_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "keys": sorted(str(key) for key in payload.keys()),
            "has_template": bool(_env_str("QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON")),
            "uses_captured_sts_url": self._get_file_sts_url() != self.FILE_STS_URL,
        }

    @staticmethod
    def _payload_keys(payload: Any) -> list[str]:
        if isinstance(payload, dict):
            return sorted(str(key) for key in payload.keys())
        if isinstance(payload, list):
            return ["<list>"]
        return [type(payload).__name__]

    def _file_step_payload_summary(self, payload: Any, *, env_name: str, url_used: str, default_url: str) -> dict[str, Any]:
        return {
            "keys": self._payload_keys(payload),
            "has_template": bool(_env_str(env_name)),
            "uses_captured_url": url_used != default_url,
        }

    def request_file_upload_token(self, *, filename: str, filesize: int, filetype: str = "file") -> dict[str, Any]:
        """Create Qwen file upload ticket.

        HAR sequence observed on chat.qwen.ai:
        POST /api/v2/files/getstsToken -> PUT OSS signed URL -> POST /api/v2/files/parse
        """
        payload = self._build_file_upload_ticket_payload(filename=filename, filesize=int(filesize), filetype=filetype or "file")
        file_headers = self._get_file_api_headers()
        self._log(f"Qwen file getstsToken header summary: {self._file_header_summary(file_headers)}")
        self._log(f"Qwen file getstsToken payload summary: {self._payload_template_summary(payload)}")
        resp = self.session.post(
            self._get_file_sts_url(),
            json=payload,
            headers=file_headers,
            timeout=self.connect_timeout,
        )
        self._raise_for_bad_response(resp, operation="files/getstsToken")
        data = self._extract_data(resp.json())
        if not isinstance(data, dict):
            raise QwenProviderError("Qwen file upload ticket is not an object")
        data = self._normalize_upload_ticket(data)
        if not data.get("file_id") or not data.get("file_url"):
            raise QwenProviderError("Qwen file upload ticket is missing file_id/file_url")
        return data

    @staticmethod
    def _url_has_oss_presigned_signature(upload_url: str) -> bool:
        """Return True when the OSS URL already carries a query signature.

        Qwen can return two different upload ticket shapes:
        - a pre-signed OSS URL with Signature/x-oss-signature query params;
        - a raw OSS URL plus STS credentials that must be signed by us.

        These modes must not be mixed: Aliyun OSS rejects requests that contain
        both query-string Signature and Authorization header.
        """
        parsed = urlparse(upload_url or "")
        query_keys = {str(key).lower() for key, _ in parse_qsl(parsed.query or "", keep_blank_values=True)}
        presigned_keys = {
            "signature",
            "ossaccesskeyid",
            "expires",
            "x-oss-signature",
            "x-oss-credential",
            "x-oss-date",
            "x-oss-expires",
            "x-oss-signature-version",
        }
        return bool(query_keys & presigned_keys)

    @staticmethod
    def _canonical_query_string(parsed_url: Any) -> str:
        pairs = parse_qsl(parsed_url.query or "", keep_blank_values=True)
        encoded: list[tuple[str, str]] = []
        for key, value in pairs:
            encoded.append((quote(str(key), safe="-_.~"), quote(str(value), safe="-_.~")))
        encoded.sort(key=lambda item: (item[0], item[1]))
        return "&".join(f"{key}={value}" for key, value in encoded)

    @staticmethod
    def _oss_v4_signing_key(secret: str, date_short: str, region: str) -> bytes:
        k_date = hmac.new(("aliyun_v4" + secret).encode("utf-8"), date_short.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, b"oss", hashlib.sha256).digest()
        return hmac.new(k_service, b"aliyun_v4_request", hashlib.sha256).digest()

    @staticmethod
    def _oss_query_keys(upload_url: str) -> set[str]:
        try:
            return {str(key).lower() for key, _ in parse_qsl(urlparse(upload_url or "").query or "", keep_blank_values=True)}
        except Exception:
            return set()

    @staticmethod
    def _oss_additional_signed_headers(upload_url: str) -> set[str]:
        try:
            pairs = parse_qsl(urlparse(upload_url or "").query or "", keep_blank_values=True)
        except Exception:
            return set()
        for key, value in pairs:
            if str(key).lower() == "x-oss-additional-headers":
                return {part.strip().lower() for part in str(value or "").split(";") if part.strip()}
        return set()

    def _get_oss_put_header_template(self) -> dict[str, str]:
        raw = _env_json_dict("QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON")
        result: dict[str, str] = {}
        deny = {"authorization", "cookie", "host", "content-length", "connection", "proxy-authorization"}
        for name, value in raw.items():
            key = str(name or "").strip()
            val = str(value or "").strip()
            if not key or not val or key.lower() in deny:
                continue
            result[key] = val
        return result

    @staticmethod
    def _find_header_value(headers: dict[str, str], name: str) -> str:
        target = str(name or "").lower()
        for key, value in headers.items():
            if str(key or "").lower() == target:
                return str(value or "").strip()
        return ""

    @staticmethod
    def _set_header_case_insensitive(headers: dict[str, str], name: str, value: str) -> None:
        target = str(name or "").lower()
        for key in list(headers.keys()):
            if str(key or "").lower() == target:
                headers.pop(key, None)
        if str(value or "").strip():
            headers[name] = str(value).strip()

    def _build_presigned_oss_put_headers(self, upload_url: str, *, content_type: str | None) -> dict[str, str]:
        """Build OSS PUT headers for a provider pre-signed URL.

        OSS V4 pre-signed URLs are extremely sensitive to signed/canonical
        headers. The query string already carries the signature; replaying
        headers captured from a different browser PUT can invalidate it.

        In particular, *any* x-oss-* header can enter OSS canonicalization.
        Previous patches removed dynamic x-oss-date/security-token, but keeping
        x-oss-user-agent was still enough to trigger SignatureDoesNotMatch.
        Therefore the default/minimal mode now sends only non x-oss browser
        headers and does not send Content-Type unless explicitly enabled.
        """
        template = self._get_oss_put_header_template()
        mode = _env_str("QWEN_OSS_PUT_MODE", "minimal").lower() or "minimal"
        if mode not in {"bare", "minimal", "browser_like", "har"}:
            mode = "minimal"





        dynamic_deny = {
            "authorization",
            "cookie",
            "host",
            "content-length",
            "connection",
            "proxy-authorization",
            "x-oss-content-sha256",
            "x-oss-date",
            "x-oss-security-token",
            "x-oss-credential",
            "x-oss-signature",
            "x-oss-expires",
            "x-oss-signature-version",
            "x-oss-user-agent",
        }
        safe_browser_headers = {
            "accept",
            "accept-language",
            "origin",
            "referer",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
            "user-agent",
        }

        headers: dict[str, str] = {}
        include_content_type = _env_bool("QWEN_OSS_PUT_INCLUDE_CONTENT_TYPE", False)

        if mode == "bare":
            headers = {}
        elif mode == "minimal":


            ua = self._find_header_value(template, "user-agent") or _env_str("QWEN_USER_AGENT")
            if ua:
                headers["User-Agent"] = ua
        elif mode in {"browser_like", "har"}:
            for key, value in template.items():
                lowered = str(key or "").lower()
                if lowered in dynamic_deny or lowered.startswith("x-oss-"):
                    continue
                if lowered == "content-type" and not include_content_type:
                    continue
                if mode == "browser_like" and lowered not in safe_browser_headers and lowered != "content-type":
                    continue
                headers[key] = str(value or "").strip()

        if include_content_type:




            template_content_type = self._find_header_value(template, "content-type")
            effective_content_type = str(content_type or "").strip() or template_content_type
            if effective_content_type:
                self._set_header_case_insensitive(headers, "Content-Type", effective_content_type)



        for key in list(headers.keys()):
            lowered = str(key or "").lower()
            if lowered in dynamic_deny or lowered.startswith("x-oss-"):
                headers.pop(key, None)
            elif lowered == "content-type" and not include_content_type:
                headers.pop(key, None)
        return headers

    def _oss_put_header_summary(self, headers: dict[str, str], *, upload_url: str) -> dict[str, Any]:
        return {
            "mode": _env_str("QWEN_OSS_PUT_MODE", "minimal") or "minimal",
            "has_template": bool(_env_str("QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON")),
            "header_names": sorted(headers.keys()),
            "has_content_type": any(key.lower() == "content-type" for key in headers),
            "include_content_type": _env_bool("QWEN_OSS_PUT_INCLUDE_CONTENT_TYPE", False),
            "has_dynamic_x_oss_headers": any(key.lower().startswith("x-oss-") for key in headers),
            "additional_signed_headers": sorted(self._oss_additional_signed_headers(upload_url)),
            "uses_sts_header_signing": any(key.lower() == "authorization" for key in headers),
        }

    @staticmethod
    def _normalize_oss_region(region: str) -> str:
        value = str(region or "").strip()


        if value.startswith("oss-"):
            value = value[4:]
        return value

    @staticmethod
    def _clean_oss_endpoint(endpoint: str) -> str:
        value = str(endpoint or "").strip()
        if not value:
            return ""
        parsed = urlparse(value if "://" in value else f"https://{value}")
        return (parsed.netloc or parsed.path or "").strip().strip("/")

    def _build_sts_oss_upload_url(self, ticket: dict[str, Any], fallback_url: str = "") -> str:
        """Build the clean object URL used by browser ali-oss SDK.

        Qwen getstsToken returns both a query-signed file_url and raw STS
        fields. Browser HARs show that the UI ignores the query-signed URL for
        PUT and instead uploads to:

            https://{bucketname}.{endpoint}/{file_path}

        with Authorization: OSS4-HMAC-SHA256.
        """
        bucket = str(ticket.get("bucket") or ticket.get("bucketname") or "").strip().strip("/")
        endpoint = self._clean_oss_endpoint(str(ticket.get("endpoint") or ""))
        object_key = str(ticket.get("object_key") or ticket.get("file_path") or "").strip().lstrip("/")
        if not object_key:
            parsed_fallback = urlparse(fallback_url or "")
            object_key = (parsed_fallback.path or "").lstrip("/")
        if not object_key:
            return ""

        if endpoint:
            host = endpoint if (bucket and endpoint.lower().startswith((bucket + ".").lower())) else f"{bucket}.{endpoint}" if bucket else endpoint
        else:
            parsed = urlparse(fallback_url or "")
            host = parsed.netloc
        if not host:
            return ""
        return f"https://{host}/{quote(object_key, safe='/-_.~')}"

    def _build_oss_v4_headers(
        self,
        *,
        upload_url: str,
        content: bytes,
        content_type: str | None,
        ticket: dict[str, Any],
    ) -> dict[str, str]:
        """Sign an OSS PUT exactly like the browser ali-oss SDK.

        Important details confirmed against user HARs:
        - use clean bucket host URL, not the query-signed file_url;
        - region in Credential scope is "ap-southeast-1", not
          "oss-ap-southeast-1";
        - x-oss-content-sha256 is the literal UNSIGNED-PAYLOAD;
        - canonical URI includes the bucket name even though the actual request
          URL uses virtual-hosted style;
        - Authorization omits AdditionalHeaders when none are used.
        """
        access_key_id = str(ticket.get("access_key_id") or "").strip()
        access_key_secret = str(ticket.get("access_key_secret") or "").strip()
        security_token = str(ticket.get("security_token") or "").strip()
        if not access_key_id or not access_key_secret or not security_token:
            return {}

        parsed = urlparse(upload_url)
        host = parsed.netloc
        if not host:
            return {}

        region = self._normalize_oss_region(
            str(ticket.get("region") or _env_str("QWEN_OSS_REGION", "ap-southeast-1") or "ap-southeast-1")
        )
        if not region:
            region = "ap-southeast-1"

        now = datetime.now(timezone.utc)
        date_short = now.strftime("%Y%m%d")
        oss_date = now.strftime("%Y%m%dT%H%M%SZ")
        payload_hash = "UNSIGNED-PAYLOAD"
        template = self._get_oss_put_header_template()
        x_oss_user_agent = self._find_header_value(template, "x-oss-user-agent") or "aliyun-sdk-js/6.23.0"
        effective_content_type = str(content_type or "").strip() or self._find_header_value(template, "content-type") or "application/octet-stream"

        headers: dict[str, str] = {
            "Content-Type": effective_content_type,
            "User-Agent": self.user_agent,
            "Origin": "https://chat.qwen.ai",
            "Referer": "https://chat.qwen.ai/",
            "x-oss-content-sha256": payload_hash,
            "x-oss-date": oss_date,
            "x-oss-security-token": security_token,
            "x-oss-user-agent": x_oss_user_agent,
        }




        canonical_header_values = {
            "content-type": effective_content_type,
            "x-oss-content-sha256": payload_hash,
            "x-oss-date": oss_date,
            "x-oss-security-token": security_token,
            "x-oss-user-agent": x_oss_user_agent,
        }
        canonical_headers = "".join(
            f"{name}:{str(canonical_header_values[name]).strip()}\n"
            for name in sorted(canonical_header_values)
        )
        additional_headers = ""

        bucket = str(ticket.get("bucket") or ticket.get("bucketname") or "").strip().strip("/")



        object_path = parsed.path or "/"
        if bucket and not object_path.lower().startswith(("/" + bucket + "/").lower()):
            canonical_uri = f"/{bucket}{object_path}"
        else:
            canonical_uri = object_path

        canonical_request = "\n".join(
            [
                "PUT",
                canonical_uri,
                self._canonical_query_string(parsed),
                canonical_headers,
                additional_headers,
                payload_hash,
            ]
        )
        scope = f"{date_short}/{region}/oss/aliyun_v4_request"
        string_to_sign = "\n".join(
            [
                "OSS4-HMAC-SHA256",
                oss_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._oss_v4_signing_key(access_key_secret, date_short, region),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["Authorization"] = (
            "OSS4-HMAC-SHA256 "
            f"Credential={access_key_id}/{scope},"
            f"Signature={signature}"
        )
        return headers

    def put_file_to_oss(
        self,
        *,
        upload_url: str,
        content: bytes,
        content_type: str | None = None,
        ticket: dict[str, Any] | None = None,
    ) -> None:
        """Upload file bytes to OSS using provider signed URL.

        The ticket comes from /files/getstsToken. Some Qwen responses include a
        pre-signed URL, others include temporary STS credentials. Support both:
        if STS credentials are present, sign PUT as OSS4-HMAC-SHA256; otherwise
        fallback to provider pre-signed URL. Never log upload_url because it may
        contain temporary credentials.
        """
        ticket = ticket or {}
        use_sts_header_signing = bool(
            ticket.get("access_key_id")
            and ticket.get("access_key_secret")
            and ticket.get("security_token")
            and (ticket.get("object_key") or ticket.get("file_path"))
            and _env_bool("QWEN_OSS_USE_STS_HEADER_SIGNING", True)
        )
        if use_sts_header_signing:
            clean_url = self._build_sts_oss_upload_url(ticket, fallback_url=upload_url)
            if clean_url:
                upload_url = clean_url

        is_presigned_url = self._url_has_oss_presigned_signature(upload_url)

        if use_sts_header_signing:
            headers = self._build_oss_v4_headers(
                upload_url=upload_url,
                content=content,
                content_type=content_type,
                ticket=ticket,
            )
            if not headers:
                raise QwenProviderError("qwen_oss_sign_failed: missing STS fields for OSS4 header signing")
        elif is_presigned_url:
            headers = self._build_presigned_oss_put_headers(upload_url, content_type=content_type)
        else:
            headers: dict[str, str] = {}
            if content_type:
                headers["Content-Type"] = content_type




        parsed = urlparse(upload_url or "")
        oss_host = parsed.netloc or "unknown-oss-host"
        connect_timeout = _env_float("QWEN_OSS_CONNECT_TIMEOUT_SEC", max(float(self.connect_timeout), 60.0), min_value=1.0, max_value=300.0)
        read_timeout = _env_float("QWEN_OSS_READ_TIMEOUT_SEC", 300.0, min_value=30.0, max_value=1800.0)
        self._log(
            "Qwen OSS PUT summary: "
            f"host={oss_host}, presigned={is_presigned_url}, "
            f"content_len={len(content)}, connect_timeout={connect_timeout}, read_timeout={read_timeout}, "
            f"headers={self._oss_put_header_summary(headers, upload_url=upload_url)}"
        )
        try:
            resp = requests.put(
                upload_url,
                data=content,
                headers=headers,
                timeout=(connect_timeout, read_timeout),
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise QwenProviderError(
                "qwen_oss_connect_timeout: cannot connect to OSS host "
                f"{oss_host} within {connect_timeout:.1f}s; check VPN/proxy/firewall/DNS for Python requests"
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise QwenProviderError(
                "qwen_oss_read_timeout: OSS host accepted connection but upload/read timed out "
                f"for {oss_host} after {read_timeout:.1f}s"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise QwenProviderError(
                f"qwen_oss_put_network_error: {type(exc).__name__} while uploading to OSS host {oss_host}"
            ) from exc
        self._raise_for_bad_response(resp, operation="oss_file_put")

    def _build_file_parse_payload(self, file_id: str, *, ticket: dict[str, Any] | None = None) -> Any:
        template = _env_json_dict("QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON")
        payload: Any = self._deepcopy_json_like(template) if template else {}
        ticket = ticket or {}
        filename = str(ticket.get("filename") or ticket.get("name") or "").strip()
        file_url = str(ticket.get("file_url") or ticket.get("url") or "").strip()
        filesize = ticket.get("filesize") or ticket.get("size")
        filetype = ticket.get("filetype") or ticket.get("file_type") or ticket.get("content_type")

        if not payload:
            payload = {"file_id": file_id}
            return payload

        replaced_id = self._replace_payload_aliases_recursive(payload, {"file_id", "fileId", "fileid", "id"}, file_id)
        if not replaced_id and isinstance(payload, dict):
            payload.setdefault("file_id", file_id)
        if file_url:
            self._replace_payload_aliases_recursive(payload, {"file_url", "fileUrl", "url"}, file_url)
        if filename:
            self._replace_payload_aliases_recursive(payload, {"filename", "fileName", "name", "file_name"}, filename)
        if filesize not in (None, ""):
            try:
                size_value: Any = int(filesize)
            except Exception:
                size_value = filesize
            self._replace_payload_aliases_recursive(payload, {"filesize", "fileSize", "size", "file_size"}, size_value)
        if filetype:
            self._replace_payload_aliases_recursive(payload, {"filetype", "fileType", "type", "file_type", "content_type", "contentType", "mime_type", "mimeType"}, filetype)
        return payload

    def _build_file_parse_status_payload(self, file_id: str) -> Any:
        template = _env_json_dict("QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON")
        payload: Any = self._deepcopy_json_like(template) if template else {}
        if not payload:
            return {"file_id_list": [file_id]}
        replaced_list = self._replace_payload_list_aliases_recursive(
            payload,
            {"file_id_list", "fileIdList", "file_ids", "fileIds", "ids"},
            [file_id],
        )
        replaced_scalar = self._replace_payload_aliases_recursive(payload, {"file_id", "fileId", "fileid", "id"}, file_id)
        if not replaced_list and not replaced_scalar and isinstance(payload, dict):
            payload.setdefault("file_id_list", [file_id])
        return payload

    def request_file_parse(self, file_id: str, *, ticket: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._build_file_parse_payload(file_id, ticket=ticket)
        url = self._get_file_parse_url()
        self._log(
            "Qwen file parse payload summary: "
            f"{self._file_step_payload_summary(payload, env_name='QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON', url_used=url, default_url=self.FILE_PARSE_URL)}"
        )
        resp = self.session.post(
            url,
            json=payload,
            headers=self._get_file_api_headers(),
            timeout=self.connect_timeout,
        )
        self._raise_for_bad_response(resp, operation="files/parse")
        data = self._extract_data(resp.json())
        return data if isinstance(data, dict) else {"file_id": file_id}

    def poll_file_parse_status(
        self,
        file_id: str,
        *,
        timeout_sec: float = 90.0,
        interval_sec: float = 1.5,
    ) -> dict[str, Any]:
        deadline = time.time() + max(1.0, float(timeout_sec))
        last_item: dict[str, Any] = {"file_id": file_id, "status": "unknown"}
        while True:
            payload = self._build_file_parse_status_payload(file_id)
            url = self._get_file_parse_status_url()
            self._log(
                "Qwen file parse/status payload summary: "
                f"{self._file_step_payload_summary(payload, env_name='QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON', url_used=url, default_url=self.FILE_PARSE_STATUS_URL)}"
            )
            resp = self.session.post(
                url,
                json=payload,
                headers=self._get_file_api_headers(),
                timeout=self.connect_timeout,
            )
            self._raise_for_bad_response(resp, operation="files/parse/status")
            data = self._extract_data(resp.json())
            if isinstance(data, list) and data:
                item = data[0] if isinstance(data[0], dict) else {}
            elif isinstance(data, dict):
                items = data.get("items") or data.get("data") or []
                item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else data
            else:
                item = {}
            last_item = dict(item or last_item)
            status = str(last_item.get("status") or last_item.get("parse_status") or "").strip().lower()
            error_msg = str(last_item.get("error_msg") or last_item.get("message") or "").strip()
            if status in {"success", "finished", "done"}:
                return last_item
            if status in {"failed", "error", "fail"}:
                raise QwenProviderError(error_msg or f"Qwen file parse failed for {file_id}")
            if time.time() >= deadline:
                raise QwenProviderError(f"Qwen file parse status timeout for {file_id}: {last_item}")
            time.sleep(max(0.2, float(interval_sec)))

    def send_stream(
        self,
        payload: dict[str, Any],
        thinking_enabled: bool,
    ) -> requests.Response:
        """Send streaming chat request"""
        payload["stream"] = True
        payload["version"] = "2.1"
        payload["incremental_output"] = True

        self._log(f"Sending request to {self.CHAT_URL}")

        resp = self.session.post(
            self.CHAT_URL,
            params={"chat_id": payload.get("chat_id", "")},
            json=payload,
            stream=True,
            timeout=(self.connect_timeout, self.stream_read_timeout),
        )
        self._raise_for_bad_response(resp, operation="send_stream")
        return resp

    def continue_stream(
        self,
        session_id: str,
        message_id: str,
        payload: dict[str, Any],
        thinking_enabled: bool,
    ) -> requests.Response:
        """Send continue request"""
        payload["stream"] = True
        payload["version"] = "2.1"
        payload["incremental_output"] = True
        payload["parent_id"] = message_id

        self._log(f"Continuing from message {message_id}")

        resp = self.session.post(
            self.CHAT_URL,
            params={"chat_id": payload.get("chat_id", session_id)},
            json=payload,
            stream=True,
            timeout=(self.connect_timeout, self.stream_read_timeout),
        )
        self._raise_for_bad_response(resp, operation="continue_stream")
        return resp






class QwenAPI:
    """
    Fully autonomous Qwen API client.
    No external dependencies from the main project.
    """

    _global_uploaded_files: dict[str, dict[str, Any]] = {}

    def __init__(
        self,
        token: str,
        logger: Callable[[str], None] | None = None,
        proxy_config: dict[str, Any] | None = None,
        user_agent: str | None = None,
        default_model: str = "qwen3.6-plus",
    ):
        self.token = token
        self.logger = logger
        self.default_model = default_model
        self.session_id: str | None = None
        self.last_message_id: int | None = None
        self.last_response_meta: dict[str, Any] = {}

        connect_timeout = _env_float("QWEN_CONNECT_TIMEOUT", 30.0, min_value=1.0, max_value=300.0)
        stream_read_timeout = _env_float("QWEN_STREAM_READ_TIMEOUT", 300.0, min_value=30.0, max_value=3600.0)

        self.transport = QwenTransport(
            token=token,
            logger=logger,
            proxy_config=proxy_config,
            user_agent=user_agent,
            connect_timeout=connect_timeout,
            stream_read_timeout=stream_read_timeout,
        )
        self.parser = QwenSseParser()


        self._remote_to_local: dict[str, dict[str, int]] = {}
        self._local_to_remote: dict[str, dict[int, str]] = {}
        self._next_local_id: dict[str, int] = {}
        self._last_response_remote_id: dict[str, str] = {}




        self._uploaded_files = QwenAPI._global_uploaded_files

    def _log(self, message: str):
        if callable(self.logger):
            try:
                self.logger(message)
            except Exception:
                pass

    def _ensure_local_message_id(self, session_id: str, remote_id: str) -> int:
        """Map remote message ID to local sequential ID"""
        if not session_id or not remote_id:
            return 0

        r2l = self._remote_to_local.setdefault(session_id, {})
        l2r = self._local_to_remote.setdefault(session_id, {})

        if remote_id in r2l:
            return r2l[remote_id]

        next_id = self._next_local_id.get(session_id, 1)
        while next_id in l2r:
            next_id += 1

        r2l[remote_id] = next_id
        l2r[next_id] = remote_id
        self._next_local_id[session_id] = next_id + 1

        return next_id

    def _get_remote_message_id(self, session_id: str, local_id: int) -> str:
        """Get remote ID from local ID"""
        if not session_id or local_id <= 0:
            return ""
        return self._local_to_remote.get(session_id, {}).get(local_id, "")

    def get_model(self) -> str:
        return self.default_model

    def set_model(self, model: str) -> str:
        self.default_model = model or "qwen3.6-plus"
        return self.default_model

    def fetch_models(self) -> list[dict]:
        return self.transport.fetch_models()

    def get_user_info(self) -> dict:
        return self.transport.get_user_info()

    def validate_token(self) -> bool:
        return self.transport.validate_token()

    def create_session(self) -> str | None:
        sid = self.transport.create_session(model=self.default_model)
        if sid:
            self.session_id = sid
        return sid

    def delete_session(self, session_id: str) -> bool:
        ok = self.transport.delete_session(session_id)
        if ok:
            self._remote_to_local.pop(session_id, None)
            self._local_to_remote.pop(session_id, None)
            self._next_local_id.pop(session_id, None)
            self._last_response_remote_id.pop(session_id, None)
            if self.session_id == session_id:
                self.session_id = None
        return ok

    def update_session_title(self, session_id: str, title: str) -> bool:
        return self.transport.update_session_title(session_id, title)

    def fetch_sessions_page(self, pinned: bool = False) -> tuple[list[dict], bool]:
        if pinned:
            return [], False
        items = self.transport.fetch_sessions_page(page=1)
        has_more = len(items) >= 20
        return items, has_more

    def fetch_history(self, session_id: str) -> tuple[dict, list[dict]]:
        chat = self.transport.fetch_chat(session_id)
        if not chat:
            return {}, []

        chat_session = {
            "id": chat.get("id", ""),
            "title": chat.get("title", ""),
            "updated_at": chat.get("updated_at"),
            "created_at": chat.get("created_at"),
        }

        messages_map = chat.get("chat", {}).get("history", {}).get("messages", {})
        if not isinstance(messages_map, dict):
            return chat_session, []

        messages = []
        assistants = []

        for key, value in messages_map.items():
            if not isinstance(value, dict):
                continue

            remote_id = value.get("id") or key
            local_id = self._ensure_local_message_id(session_id, remote_id)
            role = "USER" if value.get("role") == "user" else "ASSISTANT"

            if role == "ASSISTANT":
                assistants.append({"message_id": local_id, "remote_id": remote_id})


            content_list = value.get("content_list") or []
            think_text = ""
            response_text = ""

            for item in content_list:
                if isinstance(item, dict):
                    phase = item.get("phase", "")
                    content = item.get("content", "")
                    if phase.startswith("thinking"):
                        think_text = content or think_text
                    else:
                        response_text = content or response_text

            if not response_text:
                response_text = value.get("content", "")

            fragments = []
            if role == "USER" and value.get("content"):
                fragments.append({"type": "REQUEST", "content": value["content"]})
            else:
                if think_text:
                    fragments.append({"type": "THINK", "content": think_text})
                if response_text:
                    fragments.append({"type": "RESPONSE", "content": response_text})

            messages.append({
                "message_id": local_id,
                "remote_id": remote_id,
                "role": role,
                "inserted_at": value.get("timestamp", 0),
                "status": "COMPLETE",
                "fragments": fragments,
            })


        messages.sort(key=lambda x: x["inserted_at"])


        if assistants:
            assistants.sort(key=lambda x: x["message_id"])
            self.last_message_id = assistants[-1]["message_id"]

        return chat_session, messages

    def _build_feature_config(self, thinking_enabled: bool, search_enabled: bool) -> dict[str, Any]:
        return {
            "thinking_enabled": thinking_enabled,
            "output_schema": "phase",
            "research_mode": "normal",
            "auto_thinking": True,
            "thinking_format": "summary",
            "auto_search": search_enabled,
        }

    def _build_payload(
        self,
        session_id: str,
        prompt: str,
        thinking_enabled: bool,
        search_enabled: bool,
        parent_id: str | None = None,
        ref_file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        model = self.get_model()
        remote_user_id = str(uuid4())
        now_sec = int(time.time())
        now_ms = int(time.time() * 1000)

        self._ensure_local_message_id(session_id, remote_user_id)

        payload = {
            "chat_id": session_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": parent_id,
            "messages": [{
                "fid": remote_user_id,
                "parentId": parent_id,
                "childrenIds": [],
                "role": "user",
                "content": prompt,
                "user_action": "chat",
                "files": self._build_file_payloads(ref_file_ids or []),
                "timestamp": now_sec,
                "models": [model],
                "chat_type": "t2t",
                "feature_config": self._build_feature_config(thinking_enabled, search_enabled),
                "extra": {"meta": {"subChatType": "t2t"}},
                "sub_chat_type": "t2t",
                "parent_id": parent_id,
            }],
            "timestamp": now_ms,
        }

        return payload

    def _build_file_payloads(self, ref_file_ids: list[str]) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for file_id in ref_file_ids or []:
            fid = str(file_id or "").strip()
            if not fid:
                continue
            cached = self._uploaded_files.get(fid) or {}
            if not cached:
                raise QwenProviderError(
                    f"Qwen file payload is missing full file_info for file_id={fid}. "
                    "Upload the file through /files/upload in the current qwen_service runtime "
                    "or use /files/upload-and-send."
                )
            filename = str(cached.get("filename") or cached.get("name") or fid)
            size = int(cached.get("size") or 0)
            content_type = str(cached.get("content_type") or cached.get("file_type") or "application/octet-stream")
            url = str(cached.get("url") or cached.get("file_url") or "")
            created_at = int(cached.get("created_at") or int(time.time() * 1000))
            meta = cached.get("meta") if isinstance(cached.get("meta"), dict) else {}
            if not meta:
                meta = {
                    "name": filename,
                    "size": size,
                    "content_type": content_type,
                    "parse_meta": {"parse_status": str(cached.get("parse_status") or "success")},
                }
            parse_meta = meta.setdefault("parse_meta", {}) if isinstance(meta, dict) else {}
            if isinstance(parse_meta, dict):
                parse_meta["parse_status"] = "success"
            files.append({
                "type": "file",
                "file": {
                    "created_at": created_at,
                    "data": {},
                    "filename": filename,
                    "hash": None,
                    "id": fid,
                    "user_id": str(cached.get("user_id") or ""),
                    "meta": meta,
                    "update_at": created_at,
                },
                "id": fid,
                "url": url,
                "name": filename,
                "collection_name": "",
                "progress": 0,
                "status": str(cached.get("status") or "success"),
                "greenNet": "success",
                "size": size,
                "error": "",
                "itemId": str(cached.get("itemId") or uuid4()),
                "file_type": content_type,
                "showType": "file",
                "file_class": str(cached.get("file_class") or "document"),
                "uploadTaskId": str(cached.get("uploadTaskId") or uuid4()),
            })
        return files

    def _refresh_browser_session_if_enabled(self, *, reason: str) -> bool:
        mode = _env_str("QWEN_FILE_UPLOAD_MODE", "auto").lower() or "auto"
        if mode not in {"auto", "browser"}:
            return False

        source = _env_str("QWEN_SESSION_SOURCE", "har").lower() or "har"
        if source not in {"cdp", "playwright"}:
            self._log(
                "Qwen browser-session auto-refresh skipped: "
                f"session_source={source}; use HAR/manual update or CDP attach"
            )
            return False

        if not _env_bool("QWEN_PLAYWRIGHT_ENABLED", False):
            return False

        try:
            if source == "cdp":
                try:
                    from .playwright_session import refresh_qwen_cdp_session
                except ImportError:
                    from playwright_session import refresh_qwen_cdp_session

                self._log(f"Refreshing Qwen browser session via existing Chrome CDP: reason={reason}")
                result = refresh_qwen_cdp_session(
                    cdp_url=_env_str("QWEN_CDP_URL", "http://127.0.0.1:9222"),
                    timeout_sec=_env_float("QWEN_BROWSER_REFRESH_TIMEOUT_SEC", 120.0, min_value=10.0, max_value=600.0),
                )
            else:
                if not _env_bool("QWEN_BROWSER_LOGIN_AUTOMATION", False):
                    self._log(
                        "Qwen Playwright login automation is disabled; "
                        "use HAR/manual session update or QWEN_SESSION_SOURCE=cdp"
                    )
                    return False
                try:
                    from .playwright_session import refresh_qwen_browser_session
                except ImportError:
                    from playwright_session import refresh_qwen_browser_session

                self._log(f"Refreshing Qwen browser session via Playwright profile: reason={reason}")
                result = refresh_qwen_browser_session(
                    profile_dir=_env_str("QWEN_BROWSER_PROFILE_DIR", "qwen_service/.browser/qwen"),
                    headless=_env_bool("QWEN_BROWSER_HEADLESS", False),
                    channel=_env_str("QWEN_BROWSER_CHANNEL", "chrome"),
                    timeout_sec=_env_float("QWEN_BROWSER_REFRESH_TIMEOUT_SEC", 120.0, min_value=10.0, max_value=600.0),
                )

            values = result.get("values") if isinstance(result, dict) else {}
            if not isinstance(values, dict):
                return False
            env_map = {
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
            updated = False
            for key, env_name in env_map.items():
                value = str(values.get(key) or "").strip()
                if value:
                    os.environ[env_name] = value
                    if env_name == "QWEN_TOKEN":
                        self.token = value
                        self.transport.token = value
                    updated = True
            self.transport._reset_session_after_transport_error()
            return updated and self.transport.has_browser_session_headers()
        except Exception as exc:
            self._log(f"Qwen browser session refresh failed: {type(exc).__name__}: {exc}")
            return False

    @staticmethod
    def _max_upload_file_size_bytes() -> int:
        max_mb = _env_int("QWEN_FILE_UPLOAD_MAX_SIZE_MB", 20, min_value=1, max_value=100)
        return max_mb * 1024 * 1024

    @staticmethod
    def _max_files_per_message() -> int:


        return _env_int("QWEN_FILE_UPLOAD_MAX_FILES", 5, min_value=1, max_value=5)

    def _normalize_upload_file_paths(self, file_paths: list[str] | tuple[str, ...] | str | None) -> list[str]:
        if file_paths is None:
            paths: list[str] = []
        elif isinstance(file_paths, str):
            paths = [file_paths]
        else:
            paths = [str(item or "").strip() for item in file_paths]
        paths = [item for item in paths if item]
        max_files = self._max_files_per_message()
        if not paths:
            raise QwenProviderError("qwen_no_files: at least one file path is required")
        if len(paths) > max_files:
            raise QwenProviderError(f"qwen_too_many_files: maximum {max_files} files per message")
        return paths

    def _validate_upload_file_path(self, file_path: str) -> tuple[Path, int]:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise QwenProviderError(f"File does not exist: {file_path}")
        size = path.stat().st_size
        max_size = self._max_upload_file_size_bytes()
        if size > max_size:
            max_mb = max_size // (1024 * 1024)
            raise QwenProviderError(
                f"qwen_file_too_large: file size {size} bytes exceeds maximum {max_mb} MB"
            )
        return path, size

    def upload_file(self, file_path: str, *, attempts: int | None = None) -> dict[str, Any]:
        """Upload one local file to Qwen provider and wait until provider parses it.

        Final production path is intentionally single-attempt:
        getstsToken -> STS header-signed OSS PUT -> parse -> parse/status.
        Retries belong to the caller/Celery layer, not to the low-level provider
        upload because auth/signature mistakes are not fixed by repeating them.
        The ``attempts`` argument is accepted for backwards compatibility and ignored.
        """
        path, size = self._validate_upload_file_path(file_path)
        parse_timeout = _env_float("QWEN_FILE_PARSE_TIMEOUT_SEC", 120.0, min_value=5.0, max_value=600.0)
        parse_interval = _env_float("QWEN_FILE_PARSE_POLL_INTERVAL_SEC", 1.5, min_value=0.2, max_value=30.0)
        content = path.read_bytes()
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        try:
            ticket = self.transport.request_file_upload_token(
                filename=filename,
                filesize=len(content),
                filetype=content_type,
            )
            file_id = str(ticket.get("file_id") or "").strip()
            file_url = str(ticket.get("file_url") or "").strip()
            if not file_id or not file_url:
                raise QwenProviderError("Qwen upload ticket did not include file_id/file_url")
            ticket["filename"] = filename
            ticket["filesize"] = len(content)
            ticket["filetype"] = content_type

            self.transport.put_file_to_oss(
                upload_url=file_url,
                content=content,
                content_type=content_type,
                ticket=ticket,
            )
            self.transport.request_file_parse(file_id, ticket=ticket)
            parse_status = self.transport.poll_file_parse_status(
                file_id,
                timeout_sec=parse_timeout,
                interval_sec=parse_interval,
            )
            parse_status_value = str(parse_status.get("status") or parse_status.get("parse_status") or "success").strip().lower()
            if parse_status_value not in {"success", "finished", "done"}:
                raise QwenProviderError(f"Qwen file parse did not finish successfully for {file_id}: {parse_status}")
            file_info = {
                "id": file_id,
                "file_id": file_id,
                "filename": filename,
                "name": filename,
                "size": len(content),
                "content_type": content_type,
                "file_type": content_type,
                "url": file_url,
                "file_url": file_url,
                "status": "success",
                "parse_status": "success",
                "parse_meta": parse_status,
                "meta": {
                    "name": filename,
                    "size": len(content),
                    "content_type": content_type,
                    "parse_meta": {**dict(parse_status or {}), "parse_status": "success"},
                },
                "created_at": int(time.time() * 1000),
            }
            self._uploaded_files[file_id] = file_info
            self._log(f"Qwen file uploaded: file_id={file_id}, name={filename}, size={len(content)}")
            return file_info
        except Exception:
            self.transport._reset_session_after_transport_error()
            raise

    def upload_files(self, file_paths: list[str] | tuple[str, ...] | str) -> list[dict[str, Any]]:
        """Upload 1..5 files sequentially and wait until all are parsed."""
        paths = self._normalize_upload_file_paths(file_paths)


        for path in paths:
            self._validate_upload_file_path(path)
        return [self.upload_file(path) for path in paths]

    def send_files_message(
        self,
        *,
        file_paths: list[str] | tuple[str, ...] | str,
        message: str = "",
        session_id: str | None = None,
        thinking_enabled: bool = False,
        search_enabled: bool = False,
        auto_continue: bool | None = None,
        session_prompt: str = "",
    ) -> dict[str, Any]:
        """Upload up to five files and send one prompt with a full files[] payload."""
        paths = self._normalize_upload_file_paths(file_paths)
        initial_session_id = session_id or self.session_id
        sid = initial_session_id or self.create_session()
        if not sid:
            raise QwenProviderError("Cannot send file message: failed to create Qwen session")

        prompt_sent_before_file = False
        prompt = (session_prompt or "").strip()
        if prompt and not initial_session_id:
            holder: dict[str, Any] = {}

            def on_prompt_complete(thinking: str, response: str) -> None:
                holder["thinking"] = thinking
                holder["response"] = response

            def on_prompt_meta(meta: dict[str, Any]) -> None:
                holder.update(meta or {})

            self.send(
                SendRequest(
                    session_id=str(sid),
                    prompt=prompt,
                    ref_file_ids=[],
                    thinking_enabled=False,
                    search_enabled=False,
                ),
                StreamCallbacks(on_complete_parts=on_prompt_complete, on_meta=on_prompt_meta),
            )
            prompt_sent_before_file = True

        file_infos = self.upload_files(paths)
        file_ids = [str(info.get("file_id") or info.get("id")) for info in file_infos if info]
        response_holder: dict[str, Any] = {}

        def on_complete(thinking: str, response: str) -> None:
            response_holder["thinking"] = thinking
            response_holder["response"] = response

        def on_meta(meta: dict[str, Any]) -> None:
            response_holder.update(meta or {})

        callbacks = StreamCallbacks(on_complete_parts=on_complete, on_meta=on_meta)
        self.send(
            SendRequest(
                session_id=str(sid),
                prompt=message or "",
                ref_file_ids=file_ids,
                thinking_enabled=thinking_enabled,
                search_enabled=search_enabled,
            ),
            callbacks,
        )
        result: dict[str, Any] = {
            "session_id": sid,
            "message": message or "",
            "file_ids": file_ids,
            "files": file_infos,
            "file_infos": file_infos,
            "response": response_holder.get("response", ""),
            "thinking": response_holder.get("thinking", ""),
            "message_id": response_holder.get("response_message_id") or response_holder.get("message_id") or 0,
            "used_replacement_session": False,
            "session_prompt_sent_before_file": prompt_sent_before_file,
            "upload_attempts": 1,
            "errors": [],
        }
        if len(file_infos) == 1:
            result["file_id"] = file_ids[0] if file_ids else ""
            result["file_info"] = file_infos[0]
        return result

    def send_file_message_with_recovery(
        self,
        *,
        file_path: str,
        message: str = "",
        session_id: str | None = None,
        thinking_enabled: bool = False,
        search_enabled: bool = False,
        auto_continue: bool | None = None,
        session_prompt: str = "",
    ) -> dict[str, Any]:
        """Backward-compatible single-file wrapper around send_files_message."""
        return self.send_files_message(
            file_paths=[file_path],
            message=message,
            session_id=session_id,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            auto_continue=auto_continue,
            session_prompt=session_prompt,
        )

    def send(self, request: SendRequest, callbacks: StreamCallbacks) -> None:
        """Send message with streaming response"""
        try:
            session_id = request.session_id




            parent_id = self._last_response_remote_id.get(session_id)

            payload = self._build_payload(
                session_id=session_id,
                prompt=request.prompt,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
                parent_id=parent_id,
                ref_file_ids=request.ref_file_ids,
            )

            resp = self.transport.send_stream(
                payload=payload,
                thinking_enabled=request.thinking_enabled,
            )

            self._parse_and_finalize(
                session_id=session_id,
                resp=resp,
                thinking_enabled=request.thinking_enabled,
                callbacks=callbacks,
            )

        except Exception as e:
            if callbacks.on_error:
                callbacks.on_error(str(e))
            raise

    def continue_message(
        self,
        message_id: int,
        on_parts: Callable[[str, str], None] | None = None,
        on_complete_parts: Callable[[str, str], None] | None = None,
        on_meta: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Continue response from a specific message."""
        try:
            session_id = self.session_id
            if not session_id:
                raise QwenProviderError("Cannot continue Qwen response without session_id")

            remote_id = self._get_remote_message_id(session_id, message_id)
            if not remote_id and message_id > 0:




                self.fetch_history(session_id)
                remote_id = self._get_remote_message_id(session_id, message_id)

            if not remote_id and message_id <= 0:
                remote_id = self._last_response_remote_id.get(session_id, "")
                if not remote_id:
                    chat = self.transport.fetch_chat(session_id)
                    remote_id = self._find_latest_assistant_id(chat) or ""

            if not remote_id:
                raise QwenProviderError(
                    f"Cannot continue Qwen response: remote message id is unknown for local id {message_id}"
                )

            callbacks = StreamCallbacks(
                on_parts=on_parts,
                on_complete_parts=on_complete_parts,
                on_meta=on_meta,
            )

            payload = self._build_payload(
                session_id=session_id,
                prompt="",
                thinking_enabled=False,
                search_enabled=False,
                parent_id=remote_id,
            )

            resp = self.transport.continue_stream(
                session_id=session_id,
                message_id=remote_id,
                payload=payload,
                thinking_enabled=False,
            )

            self._parse_and_finalize(
                session_id=session_id,
                resp=resp,
                thinking_enabled=False,
                callbacks=callbacks,
            )

        except Exception:
            raise

    def _find_latest_assistant_id(self, chat: dict) -> str | None:
        """Find latest assistant message ID in chat"""
        messages_map = chat.get("chat", {}).get("history", {}).get("messages", {})
        if not isinstance(messages_map, dict):
            return None

        latest_ts = 0
        latest_id = ""

        for key, value in messages_map.items():
            if not isinstance(value, dict):
                continue
            if value.get("role") != "assistant":
                continue

            rid = value.get("id") or key
            ts = value.get("timestamp", 0)

            if ts >= latest_ts:
                latest_ts = ts
                latest_id = rid

        return latest_id

    def _parse_and_finalize(
        self,
        session_id: str,
        resp: requests.Response,
        thinking_enabled: bool,
        callbacks: StreamCallbacks,
    ) -> None:
        """Parse SSE stream and finalize response"""
        meta_snapshots: list[dict[str, Any]] = []

        def on_meta_local(meta: dict[str, Any]):
            if isinstance(meta, dict):
                meta_snapshots.append(dict(meta))

        think_text, answer_text, meta = self.parser.parse(
            resp=resp,
            thinking_enabled=thinking_enabled,
            on_parts=callbacks.on_parts,
            on_complete_parts=None,
            on_meta=on_meta_local,
            on_error=callbacks.on_error,
        )

        final_meta = dict(meta or {})
        if meta_snapshots:
            final_meta.update(meta_snapshots[-1])


        remote_response_id = final_meta.get("response_id")
        if remote_response_id:
            self._last_response_remote_id[session_id] = remote_response_id
            local_id = self._ensure_local_message_id(session_id, remote_response_id)
            self.last_message_id = local_id
            final_meta["response_message_id"] = local_id
        else:
            final_meta["response_message_id"] = self.last_message_id or 0

        final_meta["can_continue"] = final_meta.get("response_status") == "length"
        final_meta["auto_continue"] = False
        final_meta["has_pending_fragment"] = False

        self.last_response_meta = final_meta

        if callbacks.on_meta:
            callbacks.on_meta(final_meta)

        if callbacks.on_complete_parts:
            callbacks.on_complete_parts(think_text, answer_text)
