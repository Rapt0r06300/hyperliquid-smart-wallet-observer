"""Local rule store (V12, repo 04): JSON-backed local rules (read/write local file only).

No secrets, no venue, no network. Pure local config persistence for paper rules.
"""

from __future__ import annotations

import json
from pathlib import Path


class LocalRuleStore:
    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path) if path else None
        self._rules: dict[str, object] = {}
        if self._path and self._path.exists():
            try:
                self._rules = json.loads(self._path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                self._rules = {}

    def get(self, key: str, default=None):
        return self._rules.get(key, default)

    def set(self, key: str, value) -> None:
        self._rules[str(key)] = value
        self._save()

    def all(self) -> dict:
        return dict(self._rules)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.write_text(json.dumps(self._rules, sort_keys=True, indent=2), encoding="utf-8")
        except OSError:
            pass


__all__ = ["LocalRuleStore"]
