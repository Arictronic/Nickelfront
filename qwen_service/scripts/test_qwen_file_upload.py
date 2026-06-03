from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError as exc:
    raise SystemExit("Missing dependency: httpx. Run backend/qwen dependencies install first.") from exc


TEXT_MARKER = "NF_QWEN_TEXT_OK_7391"
FILE_MARKER = "NF_QWEN_FILE_UPLOAD_OK_7391"
PDF_MARKER = "NF_QWEN_PDF_UPLOAD_OK_7391"
DEFAULT_PROBE_FILE = "qwen_upload_probe.txt"
DEFAULT_PDF_FILE = "test.pdf"


class ProbeFailure(RuntimeError):
    pass


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv(project_root: Path) -> Path | None:
    """Load only simple KEY=VALUE pairs from .env without printing secrets."""
    env_path = project_root / ".env"
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value
    return env_path


def _service_url() -> str:
    host = (os.getenv("QWEN_SERVICE_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (os.getenv("QWEN_SERVICE_PORT") or "8767").strip() or "8767"
    return f"http://{host}:{port}".rstrip("/")


def _headers() -> dict[str, str]:
    api_key = (os.getenv("QWEN_API_KEY") or "").strip()
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _secret_state(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        return "missing"
    return f"present, length={len(value)}"


def _ensure_probe_file(file_path: Path) -> None:
    if file_path.exists():
        return
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        "\n".join(
            [
                "NICKELFRONT QWEN FILE UPLOAD PROBE",
                "",
                f"CONTROL_TOKEN: {FILE_MARKER}",
                "",
                "This is a diagnostic file for Nickelfront.",
                "If Qwen can read this attached file, it must return the exact CONTROL_TOKEN value.",
                "",
                "Expected answer:",
                FILE_MARKER,
                "",
            ]
        ),
        encoding="utf-8",
    )


_SENSITIVE_QUERY_KEYS = (
    "x-oss-security-token",
    "x-oss-signature",
    "x-oss-credential",
    "security-token",
    "signature",
    "access_key_secret",
    "accessKeySecret",
)


def _mask_sensitive_text(text: str) -> str:
    if not text:
        return text
    masked = text
    for key in _SENSITIVE_QUERY_KEYS:
        masked = re.sub(
            rf"([?&;\s\"']{re.escape(key)}=)[^&;\s\"']+",
            rf"\1<redacted>",
            masked,
            flags=re.IGNORECASE,
        )
        masked = re.sub(
            rf"({re.escape(key)}[\"']?\s*[:=]\s*[\"'])[^\"']+",
            rf"\1<redacted>",
            masked,
            flags=re.IGNORECASE,
        )
    masked = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1<redacted>", masked)
    masked = re.sub(r"(OSS4-HMAC-SHA256\s+Credential=)[^,;\s]+", r"\1<redacted>", masked)
    masked = re.sub(r"(Signature=)[0-9a-fA-F]{16,}", r"\1<redacted>", masked)
    return masked


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            low = str(key).lower()
            if low in {
                "access_key_secret",
                "accesskeysecret",
                "security_token",
                "securitytoken",
                "authorization",
                "cookie",
                "qwen_cookie",
            }:
                sanitized[key] = "<redacted>" if value else value
            else:
                sanitized[key] = _sanitize_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, str):
        return _mask_sensitive_text(payload)
    return payload


def _json_preview(payload: Any, limit: int = 12000) -> str:
    safe_payload = _sanitize_payload(payload)
    try:
        text = json.dumps(safe_payload, ensure_ascii=False, indent=2)
    except TypeError:
        text = repr(safe_payload)
    if len(text) > limit:
        return text[:limit] + "\n... <truncated>"
    return text


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, url, json=json_body, params=params)
    try:
        payload: Any = response.json()
    except Exception:
        payload = {"raw_text": response.text}

    if response.status_code >= 400:
        raise ProbeFailure(f"HTTP {response.status_code} {method} {url}: {_json_preview(payload, 4000)}")

    if not isinstance(payload, dict):
        raise ProbeFailure(f"Unexpected non-object response from {url}: {payload!r}")

    return payload


def _request_multipart_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    files: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, url, files=files, params=params)
    try:
        payload: Any = response.json()
    except Exception:
        payload = {"raw_text": response.text}

    if response.status_code >= 400:
        raise ProbeFailure(f"HTTP {response.status_code} {method} {url}: {_json_preview(payload, 4000)}")

    if not isinstance(payload, dict):
        raise ProbeFailure(f"Unexpected non-object response from {url}: {payload!r}")

    return payload


def _create_session(client: httpx.Client, base_url: str, title: str) -> str:
    payload = _request_json(client, "POST", f"{base_url}/sessions", json_body={"title": title})
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ProbeFailure(f"Qwen service did not return session_id: {_json_preview(payload)}")
    return session_id


def _run_readiness(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(client, "GET", f"{base_url}/diagnostics/readiness")
    payload["mode"] = "readiness"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    payload["passed"] = bool(payload.get("ok")) or str(payload.get("status")) == "warning"
    return payload


def _run_cache_maintenance(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/diagnostics/cache-maintenance",
        json_body={"dry_run": True},
    )
    payload["mode"] = "cache-maintenance"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    payload["passed"] = str(payload.get("status")) == "ok" and bool(payload.get("dry_run"))
    return payload


def _run_events(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(client, "GET", f"{base_url}/diagnostics/events", params={"limit": 20})
    payload["mode"] = "events"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    payload["passed"] = str(payload.get("status")) == "ok" and bool(payload.get("enabled", True))
    return payload


def _run_health(client: httpx.Client, base_url: str, *, deep_auth: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "health", "checks": {}}
    started = time.monotonic()
    result["checks"]["health"] = _request_json(client, "GET", f"{base_url}/health")


    try:
        result["checks"]["auth_status_force"] = _request_json(
            client,
            "GET",
            f"{base_url}/auth/status",
            params={"force": "true"},
        )
    except Exception as exc:
        result["checks"]["auth_status_force_error"] = str(exc)

    if deep_auth:

        try:
            result["checks"]["auth_check"] = _request_json(client, "POST", f"{base_url}/auth/check")
        except Exception as exc:
            result["checks"]["auth_check_error"] = str(exc)

    result["elapsed_sec"] = round(time.monotonic() - started, 2)
    return result


def _run_text(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    session_id = _create_session(client, base_url, "Nickelfront text probe")
    prompt = (
        "Ответь строго одним JSON-объектом без markdown и без пояснений:\n"
        "{\"ok\": true, \"control_token\": \"NF_QWEN_TEXT_OK_7391\"}\n"
        f"Значение control_token должно быть ровно {TEXT_MARKER}."
    )
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/messages",
        json_body={
            "session_id": session_id,
            "message": prompt,
            "thinking_enabled": False,
            "search_enabled": False,
            "file_ids": [],
            "auto_continue": False,
        },
    )
    response_text = str(payload.get("response") or "")
    return {
        "mode": "text",
        "session_id": session_id,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "passed": TEXT_MARKER in response_text,
        "expected_marker": TEXT_MARKER,
        "response": response_text,
        "raw": payload,
    }


def _file_prompt(filename: str = DEFAULT_PROBE_FILE) -> str:
    return (
        f"Прочитай прикреплённый файл {filename}.\n\n"
        "Найди строку CONTROL_TOKEN.\n\n"
        "Верни строго один JSON-объект без markdown, без пояснений и без дополнительного текста:\n\n"
        "{\n"
        '  "ok": true,\n'
        '  "control_token": "<значение CONTROL_TOKEN из файла>"\n'
        "}\n\n"
        "Если файл не прикреплён или ты не видишь его содержимое, верни:\n\n"
        "{\n"
        '  "ok": false,\n'
        '  "error": "file_not_visible"\n'
        "}"
    )


def _pdf_prompt(filename: str, expected_marker: str = "") -> str:
    if expected_marker:
        return (
            f"Прочитай прикреплённый PDF-файл {filename}.\n\n"
            f"Найди в PDF строку или маркер {expected_marker}.\n\n"
            "Верни строго один JSON-объект без markdown, без пояснений и без дополнительного текста:\n\n"
            "{\n"
            '  "ok": true,\n'
            '  "control_token": "<найденный маркер>"\n'
            "}\n\n"
            "Если PDF не прикреплён, не обработан или ты не видишь его содержимое, верни:\n\n"
            "{\n"
            '  "ok": false,\n'
            '  "error": "file_not_visible"\n'
            "}"
        )
    return (
        f"Прочитай прикреплённый PDF-файл {filename}.\n\n"
        "Верни строго один JSON-объект без markdown, без пояснений и без дополнительного текста:\n\n"
        "{\n"
        '  "ok": true,\n'
        '  "file_visible": true,\n'
        '  "short_summary": "<1-2 предложения о содержании PDF>"\n'
        "}\n\n"
        "Если PDF не прикреплён, не обработан или ты не видишь его содержимое, верни:\n\n"
        "{\n"
        '  "ok": false,\n'
        '  "error": "file_not_visible"\n'
        "}"
    )



def _generic_file_prompt(filename: str) -> str:
    return (
        f"Прочитай прикреплённый файл {filename}.\n\n"
        "Верни строго один JSON-объект без markdown, без пояснений и без дополнительного текста:\n\n"
        "{\n"
        '  "ok": true,\n'
        '  "file_visible": true,\n'
        '  "short_summary": "<1-2 предложения о содержимом файла>"\n'
        "}\n\n"
        "Если файл не прикреплён, не обработан или ты не видишь его содержимое, верни:\n\n"
        "{\n"
        '  "ok": false,\n'
        '  "error": "file_not_visible"\n'
        "}"
    )


def _multi_file_prompt(file_names: list[str]) -> str:
    joined = ", ".join(file_names)
    return (
        f"Прочитай все прикреплённые файлы: {joined}.\n\n"
        "В одном из файлов qwen_upload_probe.txt есть строка CONTROL_TOKEN.\n"
        "Верни строго один JSON-объект без markdown, без пояснений и без дополнительного текста:\n\n"
        "{\n"
        '  "ok": true,\n'
        f'  "file_count": {len(file_names)},\n'
        '  "control_token": "<значение CONTROL_TOKEN из файла>"\n'
        "}\n\n"
        "Если файлы не прикреплены, не обработаны или ты не видишь их содержимое, верни:\n\n"
        "{\n"
        '  "ok": false,\n'
        '  "error": "file_not_visible"\n'
        "}"
    )


def _run_upload_and_send(
    client: httpx.Client,
    base_url: str,
    file_path: Path,
    *,
    mode: str = "upload-and-send",
    prompt: str | None = None,
    expected_marker: str = FILE_MARKER,
    marker_required: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/files/upload-and-send",
        json_body={
            "file_path": str(file_path),
            "message": prompt or _file_prompt(file_path.name),
            "thinking_enabled": False,
            "search_enabled": False,
            "auto_continue": False,
            "session_prompt": "",
        },
    )
    response_text = str(payload.get("response") or "")
    low_response = response_text.lower()
    passed = expected_marker in response_text if marker_required else (bool(response_text.strip()) and "file_not_visible" not in low_response)
    result = {
        "mode": mode,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "passed": passed,
        "session_id": payload.get("session_id"),
        "file_id": payload.get("file_id") or payload.get("file_info", {}).get("file_id"),
        "response": response_text,
        "raw": payload,
    }
    if expected_marker:
        result["expected_marker"] = expected_marker
    return result


def _run_upload_pdf(
    client: httpx.Client,
    base_url: str,
    pdf_path: Path,
    *,
    expected_marker: str = "",
) -> dict[str, Any]:
    return _run_upload_and_send(
        client,
        base_url,
        pdf_path,
        mode="upload-pdf",
        prompt=_pdf_prompt(pdf_path.name, expected_marker),
        expected_marker=expected_marker,
        marker_required=bool(expected_marker),
    )



def _run_upload_file(
    client: httpx.Client,
    base_url: str,
    upload_path: Path,
) -> dict[str, Any]:
    return _run_upload_and_send(
        client,
        base_url,
        upload_path,
        mode="upload-file",
        prompt=_generic_file_prompt(upload_path.name),
        expected_marker="",
        marker_required=False,
    )


def _run_upload_multi(
    client: httpx.Client,
    base_url: str,
    upload_paths: list[Path],
) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/files/upload-and-send",
        json_body={
            "file_paths": [str(path) for path in upload_paths],
            "message": _multi_file_prompt([path.name for path in upload_paths]),
            "thinking_enabled": False,
            "search_enabled": False,
            "auto_continue": False,
            "session_prompt": "",
        },
    )
    response_text = str(payload.get("response") or "")
    passed = FILE_MARKER in response_text and ("file_not_visible" not in response_text.lower())
    return {
        "mode": "upload-multi",
        "elapsed_sec": round(time.monotonic() - started, 2),
        "passed": passed,
        "session_id": payload.get("session_id"),
        "file_ids": payload.get("file_ids") or [],
        "response": response_text,
        "raw": payload,
        "expected_marker": FILE_MARKER,
    }


def _run_two_step(
    client: httpx.Client,
    base_url: str,
    file_path: Path,
    *,
    sleep_after_upload: float,
    mode: str = "two-step",
    prompt: str | None = None,
    expected_marker: str = FILE_MARKER,
    marker_required: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    upload_payload = _request_json(
        client,
        "POST",
        f"{base_url}/files/upload",
        json_body={"file_path": str(file_path)},
    )
    file_id = str(upload_payload.get("file_id") or "").strip()
    if not file_id:
        raise ProbeFailure(f"Upload returned empty file_id: {_json_preview(upload_payload)}")

    if sleep_after_upload > 0:
        time.sleep(sleep_after_upload)

    session_id = _create_session(client, base_url, f"Nickelfront {mode} probe")
    message_payload = _request_json(
        client,
        "POST",
        f"{base_url}/messages",
        json_body={
            "session_id": session_id,
            "message": prompt or _file_prompt(file_path.name),
            "thinking_enabled": False,
            "search_enabled": False,
            "file_ids": [file_id],
            "auto_continue": False,
        },
    )
    response_text = str(message_payload.get("response") or "")
    low_response = response_text.lower()
    passed = expected_marker in response_text if marker_required else (bool(response_text.strip()) and "file_not_visible" not in low_response)
    result = {
        "mode": mode,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "sleep_after_upload_sec": sleep_after_upload,
        "passed": passed,
        "session_id": session_id,
        "file_id": file_id,
        "response": response_text,
        "upload": upload_payload,
        "message": message_payload,
    }
    if expected_marker:
        result["expected_marker"] = expected_marker
    return result


def _run_pdf_two_step(
    client: httpx.Client,
    base_url: str,
    pdf_path: Path,
    *,
    sleep_after_upload: float,
    expected_marker: str = "",
) -> dict[str, Any]:
    return _run_two_step(
        client,
        base_url,
        pdf_path,
        sleep_after_upload=sleep_after_upload,
        mode="pdf-two-step",
        prompt=_pdf_prompt(pdf_path.name, expected_marker),
        expected_marker=expected_marker,
        marker_required=bool(expected_marker),
    )


def _run_browser_refresh(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/config/session/refresh-browser",
        params={"validate": "false"},
    )
    payload["mode"] = "browser-refresh"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    return payload


def _run_cdp_refresh(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.monotonic()
    payload = _request_json(
        client,
        "POST",
        f"{base_url}/config/session/refresh-cdp",
        params={"validate": "false"},
    )
    payload["mode"] = "cdp-refresh"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    return payload


def _resolve_har_dir(project_root: Path) -> Path:
    raw = (os.getenv("QWEN_HAR_DIR") or "qwen_service/har").strip() or "qwen_service/har"
    har_dir = Path(raw)
    if not har_dir.is_absolute():
        har_dir = project_root / har_dir
    return har_dir


def _pick_har_file(project_root: Path, filename: str | None) -> Path:
    har_dir = _resolve_har_dir(project_root)
    har_dir.mkdir(parents=True, exist_ok=True)

    if filename:
        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = har_dir / candidate
        if not candidate.exists():
            raise ProbeFailure(f"HAR-файл не найден: {candidate}")
        if candidate.suffix.lower() != ".har":
            raise ProbeFailure(f"Файл должен иметь расширение .har: {candidate}")
        return candidate

    files = sorted(har_dir.glob("*.har"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise ProbeFailure(f"Нет .har файлов в папке: {har_dir}")
    return files[0]


def _run_har_refresh(client: httpx.Client, base_url: str, *, filename: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    project_root = _project_root()
    har_dir_info: dict[str, Any] = {}
    fallback_reason = ""

    try:
        har_dir_info = _request_json(client, "GET", f"{base_url}/config/har")
        payload = _request_json(
            client,
            "POST",
            f"{base_url}/config/token/update-from-har-file",
            json_body={"filename": filename} if filename else {},
            params={"validate": "false", "require_file_api": "true"},
        )
        payload["har_import_method"] = "server_har_folder_endpoint"
    except ProbeFailure as exc:


        fallback_reason = str(exc)
        har_file = _pick_har_file(project_root, filename)
        with har_file.open("rb") as fh:
            payload = _request_multipart_json(
                client,
                "POST",
                f"{base_url}/config/token/update-from-har",
                files={"har_file": (har_file.name, fh, "application/json")},
                params={"validate": "false", "require_file_api": "true"},
            )
        payload["har_import_method"] = "client_local_file_multipart_fallback"
        payload["har_file"] = str(har_file)

    payload["mode"] = "har-refresh"
    payload["elapsed_sec"] = round(time.monotonic() - started, 2)
    payload["har_dir_info"] = har_dir_info
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return payload


def _classify_failure(mode: str, error: str) -> str:
    low = error.lower()
    if (
        "qwen_oss_connect_timeout" in low
        or "qwen_oss_read_timeout" in low
        or "qwen_oss_put_network_error" in low
        or "qwen-webui-prod.oss" in low
        or "oss-accelerate.aliyuncs.com" in low
    ):
        return "oss_network_or_timeout_failed"
    if "connection refused" in low or "connecterror" in low:
        return "qwen_service_unavailable"
    if "timed out" in low and "127.0.0.1" in low:
        return "qwen_service_unavailable"
    if "401" in low or "invalid api key" in low or "неверный api" in low:
        return "qwen_service_api_key_rejected"
    if "qwen_browser_login_automation_disabled" in low or "unsafe" in low:
        return "browser_login_automation_disabled"
    if "qwen_cdp_unavailable" in low or "remote-debugging-port" in low:
        return "cdp_browser_not_available"
    if "/config/har" in low and "404" in low:
        return "har_folder_endpoint_missing"
    if "нет .har" in low or "har-файл не найден" in low or "no .har" in low:
        return "har_file_missing"
    if "qwen_file_sts_auth_failed" in low:
        return "file_sts_auth_failed"
    if "qwen_file_parse_auth_failed" in low:
        return "file_parse_auth_or_payload_failed"
    if "qwen_file_parse_status_auth_failed" in low:
        return "file_parse_status_auth_or_payload_failed"
    if "qwen_oss_auth_failed" in low or "qwen_oss_put_failed" in low or "oss rejected" in low:
        return "oss_signature_or_put_failed"
    if "oss_file_put" in low or "signature" in low or "x-oss" in low:
        return "oss_signature_or_put_failed"
    if "qwen_file_auth_failed" in low or "auth_failed" in low or "browser-session" in low or "browser session" in low:
        return "file_browser_session_auth_failed"
    if "parse status timeout" in low or "parse timeout" in low:
        return "file_parse_timeout"
    if "file parse failed" in low:
        return "file_parse_failed"
    if "authentication failed" in low or "check qwen_token" in low or "token" in low:
        return "provider_token_auth_failed"
    if "file does not exist" in low or "no such file" in low or "не указан путь" in low:
        return "file_path_not_available_to_qwen_service"
    if "file_id" in low:
        return "file_id_not_returned_or_not_accepted"
    return f"{mode}_failed"


def _print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _print_result(payload: dict[str, Any]) -> None:
    mode = str(payload.get("mode") or "unknown")
    _print_section(f"Result: {mode}")
    if "passed" in payload:
        print(f"Passed: {'YES' if payload.get('passed') else 'NO'}")
        print(f"Expected marker: {payload.get('expected_marker')}")
    print(f"Elapsed: {payload.get('elapsed_sec')} sec")
    if payload.get("session_id"):
        print(f"Session ID: {payload.get('session_id')}")
    if payload.get("file_id"):
        print(f"File ID: {payload.get('file_id')}")
    if payload.get("response") is not None:
        print("\nResponse:")
        print(str(payload.get("response") or "<empty>")[:4000])
    if payload.get("status") is not None:
        print(f"Status: {payload.get('status')}")
    if payload.get("error_count") is not None or payload.get("warning_count") is not None:
        print(f"Errors: {payload.get('error_count', 0)}; warnings: {payload.get('warning_count', 0)}")
    recommendations = payload.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        print("\nRecommendations:")
        for item in recommendations[:8]:
            print(f"- {item}")
    print("\nRaw payload:")
    print(_json_preview(payload))


def _run_selected_mode(
    mode: str,
    client: httpx.Client,
    base_url: str,
    file_path: Path,
    pdf_path: Path,
    upload_paths: list[Path],
    sleep_after_upload: float,
    deep_auth: bool,
    har_file: str | None = None,
    pdf_expected_marker: str = "",
) -> dict[str, Any]:
    if mode == "readiness":
        return _run_readiness(client, base_url)
    if mode == "cache-maintenance":
        return _run_cache_maintenance(client, base_url)
    if mode == "events":
        return _run_events(client, base_url)
    if mode == "health":
        return _run_health(client, base_url, deep_auth=deep_auth)
    if mode == "auth":
        return _run_health(client, base_url, deep_auth=True)
    if mode == "text":
        return _run_text(client, base_url)
    if mode == "upload-and-send":
        return _run_upload_and_send(client, base_url, file_path)
    if mode == "upload-file":
        return _run_upload_file(client, base_url, file_path)
    if mode == "upload-multi":
        return _run_upload_multi(client, base_url, upload_paths)
    if mode == "two-step":
        return _run_two_step(client, base_url, file_path, sleep_after_upload=sleep_after_upload)
    if mode == "upload-pdf":
        return _run_upload_pdf(client, base_url, pdf_path, expected_marker=pdf_expected_marker)
    if mode == "pdf-two-step":
        return _run_pdf_two_step(
            client,
            base_url,
            pdf_path,
            sleep_after_upload=sleep_after_upload,
            expected_marker=pdf_expected_marker,
        )
    if mode == "browser-refresh":
        return _run_browser_refresh(client, base_url)
    if mode == "cdp-refresh":
        return _run_cdp_refresh(client, base_url)
    if mode == "har-refresh":
        return _run_har_refresh(client, base_url, filename=har_file)
    raise ValueError(f"Unsupported mode: {mode}")


def _all_modes(args: argparse.Namespace) -> list[str]:
    return ["readiness", "cache-maintenance", "events", "health", "auth", "text", "upload-and-send", "two-step"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Qwen service text and file upload through local qwen_service.")
    parser.add_argument(
        "--mode",
        choices=["readiness", "cache-maintenance", "events", "health", "auth", "text", "upload-and-send", "upload-file", "upload-multi", "two-step", "upload-pdf", "pdf-two-step", "browser-refresh", "cdp-refresh", "har-refresh", "all"],
        default="all",
        help="Diagnostic mode. Default runs health/auth/text/file checks through local qwen_service.",
    )
    parser.add_argument(
        "--file",
        default=DEFAULT_PROBE_FILE,
        help="Text probe file path. Relative path is resolved near this script.",
    )
    parser.add_argument(
        "--files",
        default="",
        help="Comma-separated file paths for --mode upload-multi. Relative paths are resolved near this script.",
    )
    parser.add_argument(
        "--pdf-file",
        default=DEFAULT_PDF_FILE,
        help="PDF probe file path for --mode upload-pdf/pdf-two-step. Relative path is resolved near this script.",
    )
    parser.add_argument(
        "--pdf-expected-marker",
        default="",
        help=(
            "Optional marker expected inside test.pdf. If provided, PDF modes pass only when "
            "Qwen returns this exact marker; otherwise they pass when the PDF is visible and no file_not_visible is returned."
        ),
    )
    parser.add_argument(
        "--har-file",
        default="",
        help="HAR filename inside qwen_service/har for --mode har-refresh. Empty means newest *.har.",
    )
    parser.add_argument(
        "--sleep-after-upload",
        type=float,
        default=0.0,
        help="Delay between /files/upload and /messages in two-step mode.",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--deep-auth",
        action="store_true",
        help="In health mode also call POST /auth/check, which performs a minimal provider smoke check.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="For --mode all: continue running remaining checks after a failed check.",
    )
    args = parser.parse_args()
    if args.mode == "all" and not args.continue_on_error:
        args.continue_on_error = True

    project_root = _project_root()
    env_path = _load_dotenv(project_root)

    script_dir = Path(__file__).resolve().parent
    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = script_dir / file_path
    if file_path.name == DEFAULT_PROBE_FILE:
        _ensure_probe_file(file_path)
    upload_paths: list[Path] = []
    if args.files.strip():
        for raw_item in args.files.split(","):
            item = raw_item.strip()
            if not item:
                continue
            path = Path(item)
            if not path.is_absolute():
                path = script_dir / path
            upload_paths.append(path)
    else:

        upload_paths = [file_path]

    pdf_path = Path(args.pdf_file)
    if not pdf_path.is_absolute():
        pdf_path = script_dir / pdf_path

    modes = _all_modes(args) if args.mode == "all" else [args.mode]
    if any(mode in {"upload-pdf", "pdf-two-step"} for mode in modes):
        if not pdf_path.exists():
            raise SystemExit(
                f"PDF probe file not found: {pdf_path}\n"
                "Положи PDF в qwen_service/scripts/test.pdf или укажи --pdf-file <path>."
            )
        if pdf_path.suffix.lower() != ".pdf":
            raise SystemExit(f"PDF probe file must have .pdf extension: {pdf_path}")

    base_url = _service_url()

    _print_section("Nickelfront Qwen service diagnostic probe")
    print(f"Project root: {project_root}")
    print(f"Loaded env: {env_path if env_path else '<not found>'}")
    print(f"Qwen service: {base_url}")
    print(f"Mode: {args.mode}")
    print(f"QWEN_API_KEY: {_secret_state('QWEN_API_KEY')}")
    print(f"QWEN_TOKEN in local .env/process: {_secret_state('QWEN_TOKEN')}")
    print(f"QWEN_COOKIE in local .env/process: {_secret_state('QWEN_COOKIE')}")
    print(f"QWEN_BX_UA in local .env/process: {_secret_state('QWEN_BX_UA')}")
    print(f"QWEN_BX_UMIDTOKEN in local .env/process: {_secret_state('QWEN_BX_UMIDTOKEN')}")
    print(f"QWEN_BX_V in local .env/process: {_secret_state('QWEN_BX_V')}")
    print(f"QWEN_USER_AGENT in local .env/process: {_secret_state('QWEN_USER_AGENT')}")
    print(f"QWEN_FILE_API_EXTRA_HEADERS_JSON: {_secret_state('QWEN_FILE_API_EXTRA_HEADERS_JSON')}")
    print(f"QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON: {_secret_state('QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON')}")
    print(f"QWEN_FILE_STS_URL: {_secret_state('QWEN_FILE_STS_URL')}")
    print(f"QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON: {_secret_state('QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON')}")
    print(f"QWEN_FILE_PARSE_URL: {_secret_state('QWEN_FILE_PARSE_URL')}")
    print(f"QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON: {_secret_state('QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON')}")
    print(f"QWEN_FILE_PARSE_STATUS_URL: {_secret_state('QWEN_FILE_PARSE_STATUS_URL')}")
    print(f"QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON: {_secret_state('QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON')}")
    print(f"QWEN_OSS_PUT_MODE: {os.getenv('QWEN_OSS_PUT_MODE', 'minimal')}")
    print(f"QWEN_OSS_PUT_INCLUDE_CONTENT_TYPE: {os.getenv('QWEN_OSS_PUT_INCLUDE_CONTENT_TYPE', 'false')}")
    print(f"QWEN_FILE_UPLOAD_MODE: {os.getenv('QWEN_FILE_UPLOAD_MODE', 'auto')}")
    print(f"QWEN_SESSION_SOURCE: {os.getenv('QWEN_SESSION_SOURCE', 'har')}")
    print(f"QWEN_HAR_DIR: {os.getenv('QWEN_HAR_DIR', 'qwen_service/har')}")
    print(f"QWEN_PLAYWRIGHT_ENABLED: {os.getenv('QWEN_PLAYWRIGHT_ENABLED', 'false')}")
    print(f"QWEN_BROWSER_LOGIN_AUTOMATION: {os.getenv('QWEN_BROWSER_LOGIN_AUTOMATION', 'false')}")
    print(f"QWEN_CDP_URL: {os.getenv('QWEN_CDP_URL', 'http://127.0.0.1:9222')}")
    print(f"Probe file: {file_path}")
    print(f"Probe file exists: {file_path.exists()}")
    print(f"Probe file size: {file_path.stat().st_size if file_path.exists() else 0} bytes")
    if args.mode == "upload-multi":
        print(f"Multi-file probe files: {[str(path) for path in upload_paths]}")
    print(f"PDF probe file: {pdf_path}")
    print(f"PDF probe file exists: {pdf_path.exists()}")
    print(f"PDF probe file size: {pdf_path.stat().st_size if pdf_path.exists() else 0} bytes")
    if args.pdf_expected_marker.strip():
        print(f"PDF expected marker: {args.pdf_expected_marker.strip()}")

    had_failure = False
    summaries: list[dict[str, Any]] = []

    with httpx.Client(timeout=args.timeout, headers=_headers(), trust_env=False) as client:
        for mode in modes:
            try:
                payload = _run_selected_mode(
                    mode,
                    client,
                    base_url,
                    file_path,
                    pdf_path,
                    upload_paths,
                    max(0.0, args.sleep_after_upload),
                    args.deep_auth,
                    args.har_file.strip() or None,
                    args.pdf_expected_marker.strip(),
                )
                _print_result(payload)
                passed = payload.get("passed")
                if passed is False:
                    had_failure = True
                summaries.append(
                    {
                        "mode": mode,
                        "status": "ok" if passed is not False else "marker_not_found",
                        "passed": passed,
                        "elapsed_sec": payload.get("elapsed_sec"),
                    }
                )
            except Exception as exc:
                had_failure = True
                error_text = str(exc)
                classification = _classify_failure(mode, error_text)
                _print_section(f"FAILED: {mode}")
                print(f"Classification: {classification}")
                print(f"Error: {error_text}")
                summaries.append({"mode": mode, "status": "failed", "classification": classification, "error": error_text})
                if args.mode != "all" or not args.continue_on_error:
                    break

    _print_section("Summary")
    print(_json_preview(summaries))

    if had_failure:
        print("\nProbe finished with problems. See Classification above.")
        return 2

    print("\nProbe finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
