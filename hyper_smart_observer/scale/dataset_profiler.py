from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DatasetProfile:
    path: str
    exists: bool
    files: int
    bytes_total: int
    sampled_rows: int
    detected_columns: list[str] = field(default_factory=list)
    network_used: bool = False
    stopped_reason: str = "PROFILE_COMPLETE"


def profile_dataset(path: Path, *, sample_rows: int = 1_000) -> DatasetProfile:
    if not path.exists():
        return DatasetProfile(str(path), False, 0, 0, 0, stopped_reason="PATH_NOT_FOUND")
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    bytes_total = sum(item.stat().st_size for item in files)
    columns: set[str] = set()
    rows = 0
    for file_path in files:
        if file_path.suffix.lower() not in {".json", ".jsonl", ".csv", ".txt"}:
            continue
        for raw in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if rows >= sample_rows:
                break
            row = _parse_sample_row(raw, file_path.suffix.lower())
            if row:
                columns.update(row.keys())
                rows += 1
        if rows >= sample_rows:
            break
    return DatasetProfile(
        path=str(path),
        exists=True,
        files=len(files),
        bytes_total=bytes_total,
        sampled_rows=rows,
        detected_columns=sorted(columns),
    )


def _parse_sample_row(raw: str, suffix: str) -> dict[str, Any]:
    line = raw.strip()
    if not line:
        return {}
    if suffix in {".json", ".jsonl"}:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    if suffix == ".csv":
        return {name.strip(): "" for name in line.split(",") if name.strip()}
    return {"value": line}
