"""Append-only CSV logging for paper decisions."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import csv


@dataclass(frozen=True, slots=True)
class DecisionCsvRow:
    ts_ms: int
    component: str
    coin: str
    decision: str
    reason: str
    edge_bps: float | None = None
    paper_only: bool = True


def append_decision_csv(path: str | Path, rows: list[DecisionCsvRow] | tuple[DecisionCsvRow, ...]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    exists = target.exists()
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(DecisionCsvRow(0, "", "", "", "")).keys()))
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return target


__all__ = ["DecisionCsvRow", "append_decision_csv"]
