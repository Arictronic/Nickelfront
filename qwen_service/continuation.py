"""Auto-continuation bookkeeping helpers for qwen_service.service."""

from typing import Any


def can_auto_continue(
    *,
    config: dict[str, Any],
    tracker_store: dict[str, dict[str, Any]],
    session_id: str,
    default_enabled: bool,
    default_max_continues: int,
) -> bool:
    """Return whether auto-continue may run for the session."""
    if not config.get("auto_continue_enabled", default_enabled):
        return False

    max_continues = int(config.get("max_continues", default_max_continues))
    tracker = tracker_store.get(session_id, {})
    count = int(tracker.get("count", 0) or 0)
    return count < max_continues


def track_continuation(tracker_store: dict[str, dict[str, Any]], session_id: str, message_id: int) -> None:
    """Record one continuation request for a session."""
    if session_id not in tracker_store:
        tracker_store[session_id] = {
            "message_ids": set(),
            "count": 0,
            "last_message_id": None,
        }

    tracker = tracker_store[session_id]
    tracker["count"] = int(tracker.get("count", 0) or 0) + 1
    message_ids = tracker.setdefault("message_ids", set())
    if hasattr(message_ids, "add"):
        message_ids.add(message_id)
    tracker["last_message_id"] = message_id


def reset_continuation_tracker(tracker_store: dict[str, dict[str, Any]], session_id: str) -> None:
    """Reset continuation bookkeeping for a new user/provider turn."""
    tracker_store[session_id] = {
        "message_ids": set(),
        "count": 0,
        "last_message_id": None,
    }


def should_auto_continue(response_text: str, can_continue_flag: bool) -> bool:
    """Continue strictly by provider signal, not text heuristics."""
    return bool(can_continue_flag)
