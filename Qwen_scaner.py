#!/usr/bin/env python3
"""Compatibility wrapper for qwen_service.har_token_scanner.

The real implementation lives in qwen_service/har_token_scanner.py so the Qwen
service owns token extraction, runtime application and validation logic.

Quick usage:
    python Qwen_scaner.py --instructions
    python Qwen_scaner.py "chat.qwen.ai.har" --apply --push-service --validate
"""

from __future__ import annotations

from qwen_service.har_token_scanner import main


if __name__ == "__main__":
    raise SystemExit(main())
