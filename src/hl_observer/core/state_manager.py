from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class StateManager:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, default: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.path.exists():
            return dict(default or {})
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    def snapshot_before_crash(self, state: dict[str, Any], *, reason: str) -> Path:
        payload = dict(state)
        payload["crash_snapshot"] = {
            "reason": reason,
            "timestamp_ms": int(time.time() * 1000),
            "simulation_only": True,
        }
        return self.save(payload)


__all__ = ["StateManager"]
