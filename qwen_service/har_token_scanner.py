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
Как получить HAR-файл с актуальным Qwen token:

1. Откройте https://chat.qwen.ai.
2. Выйдите из аккаунта Qwen, если уже авторизованы.
3. Откройте инструменты разработчика в браузере:
   - Chrome / Edge: F12 или Ctrl+Shift+I.
4. Перейдите во вкладку Network / Сеть.
5. Включите Preserve log / Сохранять журнал, если такая опция есть.
6. Не закрывая вкладку Network, войдите в аккаунт Qwen.
7. После успешного входа нажмите правой кнопкой по списку запросов во вкладке Network.
8. Выберите Save all as HAR with content / Сохранить все как HAR с содержимым.
9. Передайте этот .har файл в qwen_service/har_token_scanner.py или загрузите его в настройках Nickelfront.

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


def pick_latest_qwen_token(candidates: list[QwenHarTokenCandidate]) -> QwenHarTokenCandidate | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.index)


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


def extract_latest_qwen_token_from_har_bytes(content: bytes) -> tuple[str, dict[str, Any]]:
    return extract_latest_qwen_token_from_har(load_har_from_bytes(content))


def extract_latest_qwen_token_from_har_file(path: str | Path) -> tuple[str, dict[str, Any]]:
    return extract_latest_qwen_token_from_har(load_har_from_file(path))


def update_env_token(env_path: str | Path, token: str) -> None:
    normalized = normalize_token(token)
    if not normalized:
        raise ValueError("Qwen токен пустой.")
    path = Path(env_path).expanduser()
    if not path.exists():
        path.touch()
    set_key(str(path), "QWEN_TOKEN", normalized)


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
    parser.add_argument("--apply", action="store_true", help="Write extracted token to .env as QWEN_TOKEN")
    parser.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / ".env"), help="Path to .env")
    parser.add_argument("--push-service", action="store_true", help="Apply token to running qwen_service via /config/token")
    parser.add_argument("--validate", action="store_true", help="Validate token through qwen_service /auth/status after update")
    parser.add_argument("--service-url", default=_build_service_url(), help="Qwen service URL")
    parser.add_argument("--api-key", default=os.getenv("QWEN_API_KEY", ""), help="Qwen service API key")
    parser.add_argument("--print-token", action="store_true", help="Print full token. Avoid using this in shared logs.")
    parser.add_argument("--instructions", action="store_true", help="Show instructions for exporting HAR from chat.qwen.ai and exit")
    parser.add_argument("--no-instructions", action="store_true", help="Do not print instructions before interactive path prompt")
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
        token, meta = extract_latest_qwen_token_from_har_file(har_path)
    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 2

    print("Qwen токен найден.")
    print(f"Токен: {token if args.print_token else mask_token(token)}")
    print(f"Источник: {meta.get('source')}")
    print(f"URL: {meta.get('url')}")
    print(f"Время: {meta.get('started_at')}")
    print(f"Кандидатов: {meta.get('candidates_count')}")
    print(f"Уникальных токенов: {meta.get('unique_tokens_count')}")

    if args.apply:
        try:
            update_env_token(args.env, token)
            print(f"QWEN_TOKEN обновлён в {Path(args.env).expanduser()}")
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
