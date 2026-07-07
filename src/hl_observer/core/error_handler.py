from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    timestamp_ms: int
    module: str
    function: str
    severity: str
    error_type: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    impact: str = "unknown"
    action_taken: str = "logged"
    recovered: bool = False
    next_retry_at_ms: int | None = None
    stack: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ErrorHandler:
    def __init__(self, jsonl_path: str | Path | None = None) -> None:
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self.events: list[ErrorEvent] = []

    def record(
        self,
        *,
        module: str,
        function: str,
        severity: str,
        error_type: str,
        message: str,
        context: dict[str, Any] | None = None,
        impact: str = "unknown",
        action_taken: str = "logged",
        recovered: bool = False,
        next_retry_at_ms: int | None = None,
        stack: str | None = None,
    ) -> ErrorEvent:
        event = ErrorEvent(
            timestamp_ms=int(time.time() * 1000),
            module=module,
            function=function,
            severity=severity.upper(),
            error_type=error_type,
            message=message,
            context=context or {},
            impact=impact,
            action_taken=action_taken,
            recovered=recovered,
            next_retry_at_ms=next_retry_at_ms,
            stack=stack,
        )
        self.events.append(event)
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def record_exception(
        self,
        exc: BaseException,
        *,
        module: str,
        function: str,
        severity: str = "ERROR",
        context: dict[str, Any] | None = None,
        impact: str = "component degraded",
        action_taken: str = "exception recorded",
        recovered: bool = False,
        next_retry_at_ms: int | None = None,
    ) -> ErrorEvent:
        return self.record(
            module=module,
            function=function,
            severity=severity,
            error_type=type(exc).__name__,
            message=str(exc),
            context=context,
            impact=impact,
            action_taken=action_taken,
            recovered=recovered,
            next_retry_at_ms=next_retry_at_ms,
            stack="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )


__all__ = ["ErrorEvent", "ErrorHandler"]
