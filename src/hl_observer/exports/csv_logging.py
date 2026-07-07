"""CSV/JSONL logging for paper decisions."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable


class CsvSignalLogger:
    def __init__(self, path: str | Path, *, fieldnames: Iterable[str]) -> None:
        self.path = Path(path)
        self.fieldnames = tuple(fieldnames)

    def append(self, row: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow({key: row.get(key, "") for key in self.fieldnames})


class JsonlSignalLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, row: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


__all__ = ["CsvSignalLogger", "JsonlSignalLogger"]
