"""Runtime state (V12, repo 05): small key/value runtime state with optional JSON persist.

Local, read/write-local only (no venue, no secret). Distinct from RunContext (which isolates
LIVE/BACKTEST/REPLAY/TEST_FIXTURE). Pure local bookkeeping.
"""

from __future__ import annotations

import json
from pathlib import Path


class RuntimeState:
    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path) if path else None
        self._state: dict[str, object] = {}
        if self._path and self._path.exists():
            try:
                self._state = json.loads(self._path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                self._state = {}

    def get(self, key: str, default=None):
        return self._state.get(key, default)

    def set(self, key: str, value) -> None:
        self._state[str(key)] = value
        if self._path is not None:
            try:
                self._path.write_text(json.dumps(self._state, sort_keys=True), encoding="utf-8")
            except OSError:
                pass

    def snapshot(self) -> dict:
        return dict(self._state)


__all__ = ["RuntimeState"]
