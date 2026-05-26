from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.qwen_test_runner import run_qwen_service_test


def _print_human_result(payload: dict[str, Any]) -> None:
    print()
    print("==========================================")
    print("Проверка Qwen Service")
    print("==========================================")
    print(f"Адрес сервиса: {payload.get('service_url')}")
    print(f"Сообщение: {payload.get('message')}")
    print(f"Успешно: {payload.get('successful_count')}/{payload.get('chat_count')}")
    print(f"Ошибок: {payload.get('failed_count')}")
    print(f"Похоже на параллельную обработку: {'да' if payload.get('looks_parallel') else 'нет'}")
    print(f"Разброс старта: {payload.get('start_spread_sec')} сек")
    print(f"Разброс завершения: {payload.get('finished_spread_sec')}")
    print(f"Разброс длительности: {payload.get('duration_spread_sec')}")
    print()
    print("Результаты по чатам:")
    for item in payload.get("results", []):
        print(
            f"- Чат #{item.get('chat')}: "
            f"длительность {item.get('duration_sec')} сек, "
            f"ошибка: {item.get('error') or 'нет'}, "
            f"ответ: {item.get('response_start') or 'пусто'}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ручной тест Qwen Service.")
    parser.add_argument("--chat-count", type=int, default=5, help="Сколько параллельных чатов запустить.")
    parser.add_argument("--timeout", type=float, default=240.0, help="Таймаут одного запроса в секундах.")
    parser.add_argument("--json", action="store_true", help="Вывести результат в JSON.")
    args = parser.parse_args()

    payload = run_qwen_service_test(chat_count=max(1, args.chat_count), timeout=max(30.0, args.timeout))

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human_result(payload)

    if payload.get("status") == "error":
        return 2
    if payload.get("status") in {"partial", "warning"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
