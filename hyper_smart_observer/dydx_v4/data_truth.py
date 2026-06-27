from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REAL_ENTRY_SOURCES = {"REAL_INDEXER", "orderbook_real"}
NON_REAL_ENTRY_SOURCES = {"LEGACY_ARTIFICIAL", "FALLBACK_ESTIMATED", "mark_simple_fallback"}
REAL_SIGNAL_ORIGINS = {"rest", "stream", "flow", "wallet_cluster", "indexer"}
NON_REAL_SIGNAL_ORIGINS = {"legacy_artificial", "synthetic", "fallback"}


@dataclass(frozen=True)
class DataTruthVerdict:
    real_data: bool
    reason: str
    source: str
    read_only: bool = True
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "real_data": self.real_data,
            "reason": self.reason,
            "source": self.source,
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


def classify_entry_source(source: object) -> DataTruthVerdict:
    text = str(source or "").strip()
    if text in REAL_ENTRY_SOURCES:
        return DataTruthVerdict(True, "REAL_ENTRY_SOURCE", text)
    if text in NON_REAL_ENTRY_SOURCES:
        return DataTruthVerdict(False, "NON_REAL_ENTRY_SOURCE", text)
    return DataTruthVerdict(False, "UNKNOWN_ENTRY_SOURCE", text)


def classify_signal_origin(origin: object) -> DataTruthVerdict:
    text = str(origin or "rest").strip().lower()
    if text in REAL_SIGNAL_ORIGINS:
        return DataTruthVerdict(True, "REAL_SIGNAL_ORIGIN", text)
    if text in NON_REAL_SIGNAL_ORIGINS:
        return DataTruthVerdict(False, "NON_REAL_SIGNAL_ORIGIN", text)
    return DataTruthVerdict(False, "UNKNOWN_SIGNAL_ORIGIN", text)


def summarize_position_truth(status: dict[str, Any]) -> dict[str, Any]:
    positions = status.get("positions") or status.get("open_positions_detail") or []
    if not isinstance(positions, list):
        positions = []
    checked = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        checked.append(classify_entry_source(pos.get("data_source") or pos.get("source")).to_dict())
    return {
        "positions_checked": len(checked),
        "all_real_data": all(item.get("real_data") for item in checked) if checked else True,
        "entries": checked,
        "read_only": True,
        "paper_only": True,
    }


__all__ = [
    "DataTruthVerdict",
    "REAL_ENTRY_SOURCES",
    "NON_REAL_ENTRY_SOURCES",
    "REAL_SIGNAL_ORIGINS",
    "NON_REAL_SIGNAL_ORIGINS",
    "classify_entry_source",
    "classify_signal_origin",
    "summarize_position_truth",
]
