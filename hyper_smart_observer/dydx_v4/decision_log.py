from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class DecisionLogger:
    """Append-only JSONL log for paper decisions and no-trades."""

    def __init__(self, path: str | Path = "logs/structured/decisions.jsonl", *, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self._lock = threading.Lock()

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        row = {
            "event_type": event_type,
            "recorded_at_ms": int(time.time() * 1000),
            "paper_only": True,
            "read_only": True,
            **payload,
        }
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")

    def tail(self, limit: int = 100, *, event_type: str | None = None) -> list[dict[str, Any]]:
        if limit <= 0 or not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and row.get("event_type") != event_type:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return list(reversed(rows))


__all__ = ["DecisionLogger"]
