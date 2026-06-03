"""Playwright-based Qwen browser session refresh.

This module is intentionally optional: qwen_service can start without
Playwright installed. It is used only to refresh the real browser-session layer
required by Qwen file endpoints (Cookie + bx-* headers + optional Bearer token).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


QWEN_ORIGIN = "https://chat.qwen.ai"
INTERESTING_PATH_MARKERS = (
    "/api/v2/files/",
    "/api/v2/chat/completions",
    "/api/v2/chats",
    "/api/user",
    "/api/models",
)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "вкл"}:
        return True
    if text in {"0", "false", "no", "off", "выкл"}:
        return False
    return default


def _normalize_token(raw: Any) -> str:
    text = str(raw or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return "".join(text.split())


def _cookie_header_from_context(context: Any) -> str:
    try:
        cookies = context.cookies(QWEN_ORIGIN)
    except TypeError:
        cookies = context.cookies()
    except Exception:
        cookies = []
    pairs: list[str] = []
    for cookie in cookies or []:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        domain = str(cookie.get("domain") or "").lower()
        if not name or value == "":
            continue
        if domain and "qwen.ai" not in domain:
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _token_from_cookie_header(cookie_header: str) -> str:
    for part in str(cookie_header or "").split(";"):
        chunk = part.strip()
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key.strip().lower() == "token":
            token = _normalize_token(value)
            if token:
                return token
    return ""


def _is_interesting_qwen_request(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return False
    if "chat.qwen.ai" not in str(parsed.netloc or "").lower():
        return False
    path = str(parsed.path or "")
    return any(marker in path for marker in INTERESTING_PATH_MARKERS)


def _safe_public_payload(values: dict[str, str], *, source: str) -> dict[str, Any]:
    return {
        "ok": bool(values.get("cookie") and values.get("bx_ua") and values.get("bx_umidtoken") and values.get("bx_v")),
        "source": source,
        "has_token": bool(values.get("token")),
        "has_cookie": bool(values.get("cookie")),
        "has_bx_ua": bool(values.get("bx_ua")),
        "has_bx_umidtoken": bool(values.get("bx_umidtoken")),
        "has_bx_v": bool(values.get("bx_v")),
        "has_user_agent": bool(values.get("user_agent")),
        "user_agent_len": len(str(values.get("user_agent") or "")),
        "values": values,
    }


def refresh_qwen_browser_session(
    *,
    profile_dir: str | Path | None = None,
    headless: bool | str | None = None,
    channel: str | None = None,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    """Open a persistent browser profile and capture Qwen session headers.

    First run should be visible (headless=false), so the user can login once.
    Later runs reuse the same profile and usually finish without manual login.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is not installed. Install it for qwen_service with: "
            "pip install playwright && python -m playwright install chromium"
        ) from exc

    raw_profile = Path(profile_dir or os.getenv("QWEN_BROWSER_PROFILE_DIR") or "qwen_service/.browser/qwen")
    if not raw_profile.is_absolute():
        raw_profile = Path.cwd() / raw_profile
    raw_profile.mkdir(parents=True, exist_ok=True)

    use_headless = _bool(headless, False)
    browser_channel = str(channel or os.getenv("QWEN_BROWSER_CHANNEL") or "chrome").strip() or None
    timeout_ms = int(max(10.0, float(timeout_sec or 120.0)) * 1000)

    captured: dict[str, str] = {}

    def on_request(request: Any) -> None:
        url = str(getattr(request, "url", "") or "")
        if not _is_interesting_qwen_request(url):
            return
        try:
            headers = request.headers or {}
        except Exception:
            return
        lowered = {str(k).lower(): str(v) for k, v in dict(headers).items()}
        auth = lowered.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            captured["token"] = _normalize_token(auth)
        if lowered.get("cookie"):
            captured["cookie"] = lowered["cookie"]
        if lowered.get("bx-ua"):
            captured["bx_ua"] = lowered["bx-ua"]
        if lowered.get("bx-umidtoken"):
            captured["bx_umidtoken"] = lowered["bx-umidtoken"]
        if lowered.get("bx-v"):
            captured["bx_v"] = lowered["bx-v"]
        if lowered.get("user-agent"):
            captured["user_agent"] = lowered["user-agent"]

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": use_headless,
            "viewport": {"width": 1365, "height": 900},
            "locale": "en-US",
        }
        if browser_channel:
            launch_kwargs["channel"] = browser_channel
        try:
            context = p.chromium.launch_persistent_context(str(raw_profile), **launch_kwargs)
        except Exception:


            launch_kwargs.pop("channel", None)
            context = p.chromium.launch_persistent_context(str(raw_profile), **launch_kwargs)

        try:
            context.on("request", on_request)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(QWEN_ORIGIN, wait_until="domcontentloaded", timeout=timeout_ms)



            for js in (
                "fetch('/api/user', {credentials: 'include'}).catch(() => null)",
                "fetch('/api/v2/chats/?page=1&exclude_project=true', {credentials: 'include'}).catch(() => null)",
                "fetch('/api/models', {credentials: 'include'}).catch(() => null)",
            ):
                try:
                    page.evaluate(js)
                except Exception:
                    pass

            deadline = time.monotonic() + max(10.0, float(timeout_sec or 120.0))
            while time.monotonic() < deadline:
                cookie_header = captured.get("cookie") or _cookie_header_from_context(context)
                if cookie_header:
                    captured["cookie"] = cookie_header
                    captured.setdefault("token", _token_from_cookie_header(cookie_header))
                if all(captured.get(key) for key in ("cookie", "bx_ua", "bx_umidtoken", "bx_v")):
                    break
                try:
                    page.wait_for_timeout(1000)
                except PlaywrightTimeoutError:
                    pass

            cookie_header = captured.get("cookie") or _cookie_header_from_context(context)
            if cookie_header:
                captured["cookie"] = cookie_header
                captured.setdefault("token", _token_from_cookie_header(cookie_header))
        finally:
            context.close()

    values = {
        "token": captured.get("token", ""),
        "cookie": captured.get("cookie", ""),
        "bx_ua": captured.get("bx_ua", ""),
        "bx_umidtoken": captured.get("bx_umidtoken", ""),
        "bx_v": captured.get("bx_v", ""),
        "user_agent": captured.get("user_agent", ""),
    }
    result = _safe_public_payload(values, source="playwright")
    if not result["ok"]:
        missing = [name for name, value in values.items() if name != "token" and not value]
        result["message"] = (
            "qwen_browser_login_required_or_headers_missing: "
            "login in the opened browser window and retry; missing=" + ",".join(missing)
        )
    else:
        result["message"] = "Qwen browser session captured successfully."
    return result


def refresh_qwen_cdp_session(
    *,
    cdp_url: str | None = None,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    """Capture Qwen session headers from an already-open normal Chrome via CDP.

    This path does not automate login and does not launch a suspicious browser.
    The user starts Chrome/Edge manually with --remote-debugging-port, logs in as
    usual, and qwen_service only attaches to capture real request headers.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is not installed. Install it for CDP capture with: "
            "pip install playwright && python -m playwright install chromium"
        ) from exc

    remote_url = str(cdp_url or os.getenv("QWEN_CDP_URL") or "http://127.0.0.1:9222").strip()
    timeout_ms = int(max(10.0, float(timeout_sec or 120.0)) * 1000)
    captured: dict[str, str] = {}

    def on_request(request: Any) -> None:
        url = str(getattr(request, "url", "") or "")
        if not _is_interesting_qwen_request(url):
            return
        try:
            headers = request.headers or {}
        except Exception:
            return
        lowered = {str(k).lower(): str(v) for k, v in dict(headers).items()}
        auth = lowered.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            captured["token"] = _normalize_token(auth)
        if lowered.get("cookie"):
            captured["cookie"] = lowered["cookie"]
        if lowered.get("bx-ua"):
            captured["bx_ua"] = lowered["bx-ua"]
        if lowered.get("bx-umidtoken"):
            captured["bx_umidtoken"] = lowered["bx-umidtoken"]
        if lowered.get("bx-v"):
            captured["bx_v"] = lowered["bx-v"]
        if lowered.get("user-agent"):
            captured["user_agent"] = lowered["user-agent"]

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(remote_url, timeout=timeout_ms)
        except Exception as exc:
            raise RuntimeError(
                "qwen_cdp_unavailable: start a normal Chrome first, for example: "
                'chrome.exe --remote-debugging-port=9222 --user-data-dir="D:\\Project\\Nickelfront\\.chrome-qwen"'
            ) from exc



        contexts = list(getattr(browser, "contexts", []) or [])
        if not contexts:
            raise RuntimeError("qwen_cdp_no_browser_context: Chrome is connected but has no contexts")
        context = contexts[0]
        context.on("request", on_request)

        pages = list(getattr(context, "pages", []) or [])
        page = None
        for candidate in pages:
            try:
                if "chat.qwen.ai" in str(candidate.url or "").lower():
                    page = candidate
                    break
            except Exception:
                continue
        if page is None:
            page = context.new_page()
            page.goto(QWEN_ORIGIN, wait_until="domcontentloaded", timeout=timeout_ms)
        else:
            try:
                page.bring_to_front()
            except Exception:
                pass

        for js in (
            "fetch('/api/user', {credentials: 'include'}).catch(() => null)",
            "fetch('/api/v2/chats/?page=1&exclude_project=true', {credentials: 'include'}).catch(() => null)",
            "fetch('/api/models', {credentials: 'include'}).catch(() => null)",
        ):
            try:
                page.evaluate(js)
            except Exception:
                pass

        deadline = time.monotonic() + max(10.0, float(timeout_sec or 120.0))
        while time.monotonic() < deadline:
            cookie_header = captured.get("cookie") or _cookie_header_from_context(context)
            if cookie_header:
                captured["cookie"] = cookie_header
                captured.setdefault("token", _token_from_cookie_header(cookie_header))
            if all(captured.get(key) for key in ("cookie", "bx_ua", "bx_umidtoken", "bx_v")):
                break
            try:
                page.wait_for_timeout(1000)
            except PlaywrightTimeoutError:
                pass

        cookie_header = captured.get("cookie") or _cookie_header_from_context(context)
        if cookie_header:
            captured["cookie"] = cookie_header
            captured.setdefault("token", _token_from_cookie_header(cookie_header))

    values = {
        "token": captured.get("token", ""),
        "cookie": captured.get("cookie", ""),
        "bx_ua": captured.get("bx_ua", ""),
        "bx_umidtoken": captured.get("bx_umidtoken", ""),
        "bx_v": captured.get("bx_v", ""),
        "user_agent": captured.get("user_agent", ""),
    }
    result = _safe_public_payload(values, source="cdp")
    if not result["ok"]:
        missing = [name for name, value in values.items() if name != "token" and not value]
        result["message"] = (
            "qwen_cdp_headers_missing: make sure the attached Chrome is logged into "
            "chat.qwen.ai and trigger a chat/file request; missing=" + ",".join(missing)
        )
    else:
        result["message"] = "Qwen browser session captured from existing Chrome via CDP."
    return result
