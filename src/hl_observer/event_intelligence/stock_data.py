"""Fail-closed study contract for stock-market data sources.

This module deliberately does not manufacture OHLC, quote, corporate-action or
fundamental observations.  It gives the roadmap a real, reusable boundary for
studying stock data while keeping the current Copy-Vault runtime disabled until
an approved point-in-time source and a provenance-backed observation exist.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re

from hl_observer.event_intelligence.source_catalog import SourceCatalogSnapshot

UNMEASURABLE = "UNMEASURABLE"
PROVEN = "PROVEN"
_SHA256_EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class StockPointInTimeObservation:
    """A real, provenance-linked stock observation admitted for study only."""

    source_id: str
    symbol: str
    observed_ts_ms: int
    received_ts_ms: int
    raw_evidence_ref: str
    consumer: str

    def __post_init__(self) -> None:
        if not str(self.source_id).strip():
            raise ValueError("source_id is required")
        if not str(self.symbol).strip():
            raise ValueError("symbol is required")
        for name, value in (
            ("observed_ts_ms", self.observed_ts_ms),
            ("received_ts_ms", self.received_ts_ms),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.observed_ts_ms > self.received_ts_ms:
            raise ValueError("observed_ts_ms cannot be after received_ts_ms")
        if not isinstance(self.raw_evidence_ref, str) or not _SHA256_EVIDENCE_REF.fullmatch(
            self.raw_evidence_ref.strip()
        ):
            raise ValueError("raw_evidence_ref must be sha256:<64 hex characters>")
        if not str(self.consumer).strip():
            raise ValueError("consumer is required")


@dataclass(frozen=True, slots=True)
class StockDataStudyReport:
    """Auditable source study; never an economic-performance claim."""

    status: str
    source_ids: tuple[str, ...]
    observation_count: int
    point_in_time_ready: bool
    no_lookahead: bool
    consumer_paths: tuple[str, ...]
    deployed: bool
    reasons: tuple[str, ...]

    @property
    def real_execution(self) -> bool:
        return False

    @property
    def read_only(self) -> bool:
        return True

    @property
    def usable_for_signal(self) -> bool:
        # T076 is a source study, not a promotion gate for any economic family.
        return False


def study_stock_data(
    catalog: SourceCatalogSnapshot,
    *,
    observations: Iterable[StockPointInTimeObservation] = (),
) -> StockDataStudyReport:
    """Study registered stock sources without enabling any runtime path.

    A source is considered stock data only when its catalog role is explicitly
    ``stock_market_data``.  The current catalog has none, so the honest result
    is ``UNMEASURABLE``.  Even when observations are supplied later, the report
    remains non-deployed and requires every observation to be causal and linked
    to a registered read-only source.
    """

    if not isinstance(catalog, SourceCatalogSnapshot):
        raise TypeError("catalog must be a SourceCatalogSnapshot")
    stock_sources = tuple(
        row
        for row in catalog.sources
        if row.role == "stock_market_data"
    )
    source_ids = tuple(row.source_id for row in stock_sources)
    rows = tuple(observations)
    if any(not isinstance(row, StockPointInTimeObservation) for row in rows):
        raise TypeError("observations must contain StockPointInTimeObservation values")

    reasons: list[str] = []
    if not stock_sources:
        reasons.append("NO_READ_ONLY_STOCK_SOURCE_REGISTERED")
    if not rows:
        reasons.append("NO_SAFE_POINT_IN_TIME_STOCK_OBSERVATIONS")

    source_map = {row.source_id: row for row in stock_sources}
    invalid_refs = [row for row in rows if row.source_id not in source_map]
    if invalid_refs:
        reasons.append("OBSERVATION_SOURCE_NOT_REGISTERED")
    if any(not source_map[row.source_id].read_only for row in rows if row.source_id in source_map):
        reasons.append("STOCK_SOURCE_NOT_READ_ONLY")
    if any(row.observed_ts_ms > row.received_ts_ms for row in rows):
        reasons.append("LOOKAHEAD_DETECTED")

    no_lookahead = bool(rows) and not any(
        row.observed_ts_ms > row.received_ts_ms for row in rows
    )
    point_in_time_ready = bool(rows) and not invalid_refs and no_lookahead
    consumers = tuple(sorted({row.consumer for row in rows}))
    proven = bool(stock_sources) and point_in_time_ready and not reasons
    if not proven and not reasons:
        reasons.append("STOCK_DATA_STUDY_INCOMPLETE")
    return StockDataStudyReport(
        status=PROVEN if proven else UNMEASURABLE,
        source_ids=source_ids,
        observation_count=len(rows),
        point_in_time_ready=point_in_time_ready,
        no_lookahead=no_lookahead,
        consumer_paths=consumers,
        deployed=False,
        reasons=tuple(reasons),
    )


__all__ = [
    "PROVEN",
    "UNMEASURABLE",
    "StockDataStudyReport",
    "StockPointInTimeObservation",
    "study_stock_data",
]
