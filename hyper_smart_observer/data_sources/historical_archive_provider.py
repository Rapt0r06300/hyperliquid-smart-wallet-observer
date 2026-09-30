from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class HistoricalArchiveProvider:
    root: Path
    name: str = "HistoricalArchiveProvider"
    enabled_by_default: bool = True
    requires_network: bool = False
    requires_api_key: bool = False

    def list_json_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(path for path in self.root.rglob("*.json") if path.is_file())

    def read_json_rows(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.list_json_files():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                rows.append(payload)
            elif isinstance(payload, list):
                rows.extend(item for item in payload if isinstance(item, dict))
            if len(rows) >= limit:
                break
        return rows[:limit]
