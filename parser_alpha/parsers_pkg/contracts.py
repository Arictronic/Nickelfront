from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]


@dataclass
class DiagnosticEvent:
    source: str
    stage: str
    reason: str
    severity: Severity
    record_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ParserDiagnostics:
    source: str
    events: list[DiagnosticEvent] = field(default_factory=list)
    degraded: bool = False
    degraded_reasons: list[str] = field(default_factory=list)

    def add(
        self,
        *,
        stage: str,
        reason: str,
        severity: Severity,
        record_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        logger = logging.getLogger("parsers_pkg.diagnostics")

        if severity in {"warning", "error"} and reason not in self.degraded_reasons:
            self.degraded = True
            self.degraded_reasons.append(reason)

        event = DiagnosticEvent(
            source=self.source,
            stage=stage,
            reason=reason,
            severity=severity,
            record_id=record_id,
            details=details or {},
        )
        self.events.append(event)

        level = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }.get(severity, logging.INFO)
        logger.log(
            level,
            "parser_event source=%s stage=%s reason=%s severity=%s record_id=%s details=%s",
            event.source,
            event.stage,
            event.reason,
            event.severity,
            event.record_id,
            event.details,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "degraded": self.degraded,
            "degraded_reasons": self.degraded_reasons,
            "events": [
                {
                    "source": event.source,
                    "stage": event.stage,
                    "reason": event.reason,
                    "severity": event.severity,
                    "record_id": event.record_id,
                    "details": event.details,
                    "timestamp": event.timestamp,
                }
                for event in self.events
            ],
        }

    def summary(self) -> dict[str, Any]:
        parse_errors = sum(1 for item in self.events if item.stage == "parse" and item.severity == "error")
        fetch_errors = sum(1 for item in self.events if item.stage == "fetch" and item.severity == "error")
        warnings = sum(1 for item in self.events if item.severity == "warning")
        return {
            "degraded": self.degraded,
            "degraded_reasons": self.degraded_reasons,
            "events_total": len(self.events),
            "warnings": warnings,
            "parse_errors": parse_errors,
            "fetch_errors": fetch_errors,
        }


@dataclass(frozen=True)
class RawSourceRecord:
    source: str
    payload: dict[str, Any]
    record_id: str | None = None
    fetched_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedRecord:
    source: str
    payload: dict[str, Any]
    record_id: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    provenance: dict[str, str] = field(default_factory=dict)
