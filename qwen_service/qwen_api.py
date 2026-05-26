"""
Autonomous Qwen API Client - No external dependencies
Fully self-contained implementation for qwen_service
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
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
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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

    def _safe_response_text(self, resp: requests.Response, limit: int = 800) -> str:
        """Return a short, token-safe response preview for diagnostics."""
        try:
            text = resp.text or ""
        except Exception:
            return ""

        return text.replace("\r", " ").replace("\n", " ").strip()[:limit]

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
        if status in {401, 403}:
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

    def request_file_upload_token(self, *, filename: str, filesize: int, filetype: str = "file") -> dict[str, Any]:
        """Create Qwen file upload ticket.

        HAR sequence observed on chat.qwen.ai:
        POST /api/v2/files/getstsToken -> PUT OSS signed URL -> POST /api/v2/files/parse
        """
        payload = {"filename": filename, "filesize": int(filesize), "filetype": filetype or "file"}
        resp = self.session.post(self.FILE_STS_URL, json=payload, timeout=self.connect_timeout)
        self._raise_for_bad_response(resp, operation="files/getstsToken")
        data = self._extract_data(resp.json())
        if not isinstance(data, dict) or not data.get("file_id") or not data.get("file_url"):
            raise QwenProviderError("Qwen file upload ticket is missing file_id/file_url")
        return data

    def put_file_to_oss(self, *, upload_url: str, content: bytes, content_type: str | None = None) -> None:
        """Upload file bytes to OSS using provider signed URL.

        The signed URL comes from /files/getstsToken. Do not log it because it contains
        temporary credentials in query parameters.
        """
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        resp = self.session.put(upload_url, data=content, headers=headers, timeout=(self.connect_timeout, 180.0))
        self._raise_for_bad_response(resp, operation="oss_file_put")

    def request_file_parse(self, file_id: str) -> dict[str, Any]:
        resp = self.session.post(self.FILE_PARSE_URL, json={"file_id": file_id}, timeout=self.connect_timeout)
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
            resp = self.session.post(
                self.FILE_PARSE_STATUS_URL,
                json={"file_id_list": [file_id]},
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
        self._uploaded_files: dict[str, dict[str, Any]] = {}

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
                "status": str(cached.get("status") or "uploaded"),
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

    def upload_file(self, file_path: str, *, attempts: int | None = None) -> dict[str, Any]:
        """Upload a local file to Qwen provider and wait until provider parses it.

        Retries the whole get-token -> put-oss -> parse pipeline. No credentials or
        signed URLs are logged.
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise QwenProviderError(f"File does not exist: {file_path}")

        max_attempts = attempts or _env_int("QWEN_FILE_UPLOAD_ATTEMPTS", 3, min_value=1, max_value=10)
        parse_timeout = _env_float("QWEN_FILE_PARSE_TIMEOUT_SEC", 120.0, min_value=5.0, max_value=600.0)
        parse_interval = _env_float("QWEN_FILE_PARSE_POLL_INTERVAL_SEC", 1.5, min_value=0.2, max_value=30.0)
        content = path.read_bytes()
        filename = path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                ticket = self.transport.request_file_upload_token(
                    filename=filename,
                    filesize=len(content),
                    filetype="file",
                )
                file_id = str(ticket.get("file_id") or "").strip()
                file_url = str(ticket.get("file_url") or "").strip()
                if not file_id or not file_url:
                    raise QwenProviderError("Qwen upload ticket did not include file_id/file_url")

                self.transport.put_file_to_oss(
                    upload_url=file_url,
                    content=content,
                    content_type=content_type,
                )
                self.transport.request_file_parse(file_id)
                parse_status = self.transport.poll_file_parse_status(
                    file_id,
                    timeout_sec=parse_timeout,
                    interval_sec=parse_interval,
                )
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
                    "status": "uploaded",
                    "parse_status": str(parse_status.get("status") or "success"),
                    "parse_meta": parse_status,
                    "meta": {
                        "name": filename,
                        "size": len(content),
                        "content_type": content_type,
                        "parse_meta": {"parse_status": str(parse_status.get("status") or "success")},
                    },
                    "created_at": int(time.time() * 1000),
                }
                self._uploaded_files[file_id] = file_info
                self._log(f"Qwen file uploaded: file_id={file_id}, name={filename}, size={len(content)}")
                return file_info
            except Exception as exc:
                last_error = exc
                self._log(f"Qwen file upload attempt {attempt}/{max_attempts} failed: {type(exc).__name__}: {exc}")
                self.transport._reset_session_after_transport_error()
                if attempt < max_attempts:
                    time.sleep(min(10.0, 0.8 * attempt))

        raise QwenProviderError(f"Qwen file upload failed after {max_attempts} attempts: {last_error}")

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
        """Upload a file and send it with an optional message.

        First tries the requested/current session. If upload or send fails after
        upload retries, creates a fresh chat session and retries once there.
        """
        errors: list[str] = []
        initial_session_id = session_id or self.session_id
        sid = initial_session_id or self.create_session()
        if not sid:
            raise QwenProviderError("Cannot send file message: failed to create Qwen session")

        def _send_session_prompt_once(target_sid: str) -> None:
            prompt = (session_prompt or "").strip()
            if not prompt:
                return
            holder: dict[str, Any] = {}

            def on_complete(thinking: str, response: str) -> None:
                holder["thinking"] = thinking
                holder["response"] = response

            def on_meta(meta: dict[str, Any]) -> None:
                holder.update(meta or {})

            callbacks = StreamCallbacks(on_complete_parts=on_complete, on_meta=on_meta)
            self.send(
                SendRequest(
                    session_id=str(target_sid),
                    prompt=prompt,
                    ref_file_ids=[],
                    thinking_enabled=False,
                    search_enabled=False,
                ),
                callbacks,
            )

        for phase in ("current_session", "new_session"):
            try:
                prompt_sent_before_file = False
                if phase == "new_session":
                    sid = self.create_session()
                    if not sid:
                        raise QwenProviderError("Failed to create replacement Qwen session")
                    _send_session_prompt_once(str(sid))
                    prompt_sent_before_file = bool((session_prompt or "").strip())
                elif not initial_session_id:
                    _send_session_prompt_once(str(sid))
                    prompt_sent_before_file = bool((session_prompt or "").strip())
                file_info = self.upload_file(file_path, attempts=3)
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
                        ref_file_ids=[str(file_info["file_id"])],
                        thinking_enabled=thinking_enabled,
                        search_enabled=search_enabled,
                    ),
                    callbacks,
                )
                return {
                    "session_id": sid,
                    "message": message or "",
                    "file_id": file_info.get("file_id"),
                    "file_info": file_info,
                    "response": response_holder.get("response", ""),
                    "thinking": response_holder.get("thinking", ""),
                    "message_id": response_holder.get("response_message_id") or response_holder.get("message_id") or 0,
                    "used_replacement_session": phase == "new_session",
                    "session_prompt_sent_before_file": prompt_sent_before_file,
                    "upload_attempts": 3,
                    "errors": errors,
                }
            except Exception as exc:
                errors.append(f"{phase}: {type(exc).__name__}: {exc}")
                self._log(f"Qwen send_file_message {phase} failed: {exc}")
                if phase == "current_session":
                    continue
                raise QwenProviderError("Qwen file message failed after retrying in a new session: " + "; ".join(errors))

        raise QwenProviderError("Qwen file message failed: " + "; ".join(errors))

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
