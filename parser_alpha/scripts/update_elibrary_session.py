from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _extract_cookie_headers_from_har(har_path: Path) -> list[str]:
    payload = json.loads(har_path.read_text(encoding="utf-8", errors="ignore"))
    entries = ((payload.get("log") or {}).get("entries") or [])
    cookies: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        req = entry.get("request") or {}
        url = str(req.get("url") or "")
        if "elibrary.ru" not in url:
            continue
        for header in req.get("headers") or []:
            if not isinstance(header, dict):
                continue
            if str(header.get("name") or "").lower() != "cookie":
                continue
            value = _normalize(header.get("value"))
            if value:
                cookies.append(value)
    return cookies


def _pick_best_cookie_header(values: list[str]) -> str | None:
    if not values:
        return None
    counts = Counter(values)
    return max(values, key=lambda v: (counts[v], len(v)))


def _header_to_cookie_map(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in header.split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


def _resolve_har_path(cli_har: str | None) -> Path:
    if cli_har:
        path = Path(cli_har)
        if not path.exists():
            raise FileNotFoundError(f"HAR file not found: {path}")
        return path

    candidates = sorted(Path(".").glob("www.elibrary.ru_Archive*.har"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("No HAR found. Put HAR in project root or pass --har.")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Update eLibrary session cookies from HAR archive.")
    parser.add_argument("--har", help="Path to HAR file. If omitted, uses latest www.elibrary.ru_Archive*.har in project root.")
    parser.add_argument(
        "--session-dir",
        default="session/elibrary",
        help="Session directory to write files into (default: session/elibrary).",
    )
    parser.add_argument(
        "--copy-har",
        action="store_true",
        help="Copy HAR to <session-dir>/latest.har for reproducible local runs.",
    )
    args = parser.parse_args()

    har_path = _resolve_har_path(args.har)
    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    cookie_headers = _extract_cookie_headers_from_har(har_path)
    cookie_header = _pick_best_cookie_header(cookie_headers)
    if not cookie_header:
        raise RuntimeError("No Cookie header for elibrary.ru found in HAR.")

    cookie_map = _header_to_cookie_map(cookie_header)

    (session_dir / "cookie_header.txt").write_text(cookie_header + "\n", encoding="utf-8")
    (session_dir / "cookies.json").write_text(
        json.dumps(cookie_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (session_dir / "source.har.path.txt").write_text(str(har_path.resolve()) + "\n", encoding="utf-8")

    if args.copy_har:
        (session_dir / "latest.har").write_bytes(har_path.read_bytes())

    print(f"Updated eLibrary session in: {session_dir}")
    print(f"HAR: {har_path}")
    print(f"Cookies: {len(cookie_map)}")
    print("Files:")
    print(f" - {session_dir / 'cookie_header.txt'}")
    print(f" - {session_dir / 'cookies.json'}")
    print(f" - {session_dir / 'source.har.path.txt'}")
    if args.copy_har:
        print(f" - {session_dir / 'latest.har'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

