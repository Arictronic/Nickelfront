"""
Autonomous Qwen API Client - No external dependencies
Fully self-contained implementation for qwen_service
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import requests

# ============================================================================
# Data Classes (replacing Domain.chat.ports)
# ============================================================================

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


# ============================================================================
# SSE Parser (replacing AI.Qwen.protocol.qwen_sse_parser)
# ============================================================================

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
                if not line_str.startswith("data:"):
                    continue

                data_str = line_str[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Extract response ID
                if "id" in data and not response_id:
                    response_id = data["id"]
                created_meta = data.get("response.created")
                if isinstance(created_meta, dict):
                    response_id = response_id or created_meta.get("response_id")
                    parent_id = created_meta.get("parent_id")
                    if parent_id:
                        meta["parent_id"] = parent_id

                # Extract choices
                choices = data.get("choices") or []
                for choice in choices:
                    delta = choice.get("delta") or {}
                    content = delta.get("content") or ""
                    phase = str(delta.get("phase") or "")

                    # Check for thinking phase
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

                    # Check finish reason
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        response_status = "FINISHED" if finish_reason == "stop" else finish_reason

                # Extract usage and metadata
                if "usage" in data:
                    meta["usage"] = data["usage"]
                if "thinking_enabled" in data:
                    meta["thinking_enabled"] = data["thinking_enabled"]

            meta["response_id"] = response_id
            meta["response_status"] = response_status
            meta["can_continue"] = response_status == "length"

            # Final callbacks
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


# ============================================================================
# Transport Layer (replacing AI.Qwen.transport.qwen_transport)
# ============================================================================

class QwenTransport:
    """HTTP transport for Qwen API"""

    BASE_URL = "https://chat.qwen.ai/api/v2"
    CHAT_URL = f"{BASE_URL}/chat/completions"
    CHATS_URL = f"{BASE_URL}/chats"
    CHATS_NEW_URL = f"{CHATS_URL}/new"

    def __init__(
        self,
        token: str,
        logger: Callable[[str], None] | None = None,
        proxy_config: dict[str, Any] | None = None,
        user_agent: str | None = None,
    ):
        self.token = token.strip()
        self.logger = logger
        self.proxy_config = proxy_config
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
        if isinstance(response_json, dict):
            if response_json.get("success") is False:
                err = response_json.get("data") or {}
                self._log(f"Qwen API error: {err}")
            if "data" in response_json:
                return response_json.get("data")
        return response_json

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
        if resp.status_code == 200:
            return resp.json()
        return {}

    def validate_token(self) -> bool:
        """Validate authentication token"""
        info = self.get_user_info()
        return bool(info.get("id"))

    def create_session(self, model: str = "qwen3.5-plus") -> str | None:
        """Create new chat session"""
        payload = {
            "title": "New Chat",
            "models": [model],
            "chat_mode": "normal",
            "chat_type": "t2t",
            "timestamp": int(time.time() * 1000),
            "project_id": "",
        }
        resp = self.session.post(self.CHATS_NEW_URL, json=payload, timeout=30)
        if resp.status_code == 200:
            data = self._extract_data(resp.json())
            session_id = data.get("id") if isinstance(data, dict) else None
            if session_id:
                self.update_referer(session_id)
                return session_id
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete chat session"""
        url = f"{self.CHATS_URL}/{session_id}"
        resp = self.session.delete(url, timeout=30)
        return resp.status_code == 200

    def update_session_title(self, session_id: str, title: str) -> bool:
        """Update session title"""
        url = f"{self.CHATS_URL}/{session_id}"
        payload = {"title": title}
        resp = self.session.put(url, json=payload, timeout=30)
        return resp.status_code == 200

    def fetch_sessions_page(self, page: int = 1, exclude_project: bool = True) -> list[dict]:
        """Fetch list of sessions"""
        params = {"page": page}
        if exclude_project:
            params["exclude_project"] = "true"
        resp = self.session.get(f"{self.CHATS_URL}/", params=params, timeout=30)
        if resp.status_code == 200:
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
        if resp.status_code == 200:
            data = self._extract_data(resp.json())
            if isinstance(data, dict):
                return data
        return {}

    def fetch_models(self) -> list[dict]:
        """Fetch available models"""
        url = "https://chat.qwen.ai/api/models"
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("models") or []
        return []

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
            timeout=120,
        )
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
            timeout=120,
        )
        return resp


# ============================================================================
# Autonomous QwenAPI Client
# ============================================================================

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
        default_model: str = "qwen3.5-plus",
    ):
        self.token = token
        self.logger = logger
        self.default_model = default_model
        self.session_id: str | None = None
        self.last_message_id: int | None = None
        self.last_response_meta: dict[str, Any] = {}

        self.transport = QwenTransport(
            token=token,
            logger=logger,
            proxy_config=proxy_config,
            user_agent=user_agent,
        )
        self.parser = QwenSseParser()

        # Message ID mapping (remote <-> local)
        self._remote_to_local: dict[str, dict[str, int]] = {}
        self._local_to_remote: dict[str, dict[int, str]] = {}
        self._next_local_id: dict[str, int] = {}
        self._last_response_remote_id: dict[str, str] = {}

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
        self.default_model = model or "qwen3.5-plus"
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

            # Extract content
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

        # Sort by timestamp
        messages.sort(key=lambda x: x["inserted_at"])

        # Set last_message_id
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
                "files": [],
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

    def send(self, request: SendRequest, callbacks: StreamCallbacks) -> None:
        """Send message with streaming response"""
        try:
            session_id = request.session_id

            # Для первого сообщения parent_id должен быть None.
            # Используем только локально сохранённый последний response_id,
            # чтобы не подхватывать случайные/служебные сообщения из истории.
            parent_id = self._last_response_remote_id.get(session_id)

            payload = self._build_payload(
                session_id=session_id,
                prompt=request.prompt,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
                parent_id=parent_id,
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
        on_complete_parts: Callable[[str, str], None] | None = None,
        on_meta: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Continue response from a specific message"""
        try:
            remote_id = self._get_remote_message_id(self.session_id, message_id)
            if not remote_id:
                remote_id = self._last_response_remote_id.get(self.session_id, "")

            callbacks = StreamCallbacks(
                on_complete_parts=on_complete_parts,
                on_meta=on_meta,
            )

            payload = self._build_payload(
                session_id=self.session_id,
                prompt="",
                thinking_enabled=False,
                search_enabled=False,
                parent_id=remote_id,
            )

            resp = self.transport.continue_stream(
                session_id=self.session_id,
                message_id=remote_id,
                payload=payload,
                thinking_enabled=False,
            )

            self._parse_and_finalize(
                session_id=self.session_id,
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

        # Update message ID mapping
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
