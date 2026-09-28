"""Source registry data models (V12 capability A — Fondation).

Typed definitions for every data source the bot reads (Hyperliquid /info
endpoints, WebSocket channels, public scrapers, user imports, local cache) plus
the provenance of each fetch and a computed health snapshot.

Purpose: make data trustworthy and auditable. Every piece of data should be
traceable to a source with a hash, a timestamp, a latency and a health status —
so the decision layer can refuse stale/uncertain data (deny-by-default → NO_TRADE).

SAFETY: pure data classes, read-only research/observability. No order, no key,
no signature, no fabricated data — provenance only describes what was fetched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

try:  # py311+
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class SourceKind(StrEnum):
    HL_INFO_REST = "HL_INFO_REST"        # Hyperliquid /info REST (read-only)
    HL_WS = "HL_WS"                      # Hyperliquid public WebSocket (read-only)
    PUBLIC_SCRAPE = "PUBLIC_SCRAPE"      # public HTML pages
    GITHUB = "GITHUB"                    # public GitHub/docs
    USER_IMPORT = "USER_IMPORT"          # CSV/JSON/TXT supplied by the user
    BULK_S3 = "BULK_S3"                  # public bulk history
    LOCAL_CACHE = "LOCAL_CACHE"          # local cached copy with provenance


class SourceStatus(StrEnum):
    OK = "OK"               # recent fetch succeeded and is fresh
    DEGRADED = "DEGRADED"   # succeeding but with errors / partial
    STALE = "STALE"         # last ok too old to trust
    DOWN = "DOWN"           # recent fetches failing
    UNKNOWN = "UNKNOWN"     # never fetched / no data yet


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    kind: SourceKind
    endpoint_or_channel: str
    description: str = ""
    read_only: bool = True          # MUST stay True — this project never writes to a venue
    enabled: bool = True

    def __post_init__(self) -> None:
        if not str(self.source_id).strip() or not str(self.endpoint_or_channel).strip():
            raise ValueError("source identity and endpoint are required")
        if not self.read_only:
            raise ValueError("SourceDefinition.read_only must be True (no real external action)")


@dataclass(frozen=True, slots=True)
class FetchProvenance:
    source_id: str
    request_id: str
    fetched_at_ms: int                 # local clock when received
    origin: str = "UNKNOWN"            # LIVE_REAL | RECORDED_REAL | TEST_FIXTURE | UNKNOWN
    received_at_ms: int | None = None
    written_at_ms: int | None = None
    run_id: str | None = None
    config_hash: str | None = None
    code_hash: str | None = None
    git_head: str | None = None
    ok: bool = True
    source_ts_ms: int | None = None    # server timestamp if available
    clock_offset_ms: float | None = None
    clock_uncertainty_ms: float | None = None
    clock_synchronized: bool = False
    latency_ms: float | None = None
    rate_weight: int | None = None
    raw_hash: str | None = None
    parsed_hash: str | None = None
    item_count: int | None = None
    data_quality: str = "OK"           # OK | DEGRADED | BAD
    error: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("fetched_at_ms", self.fetched_at_ms),
            ("received_at_ms", self.received_at_ms),
            ("written_at_ms", self.written_at_ms),
            ("source_ts_ms", self.source_ts_ms),
            ("item_count", self.item_count),
            ("rate_weight", self.rate_weight),
        ):
            if value is not None and (isinstance(value, bool) or int(value) < 0):
                raise ValueError(f"{name} must be non-negative")
        for name, value in (
            ("clock_offset_ms", self.clock_offset_ms),
            ("clock_uncertainty_ms", self.clock_uncertainty_ms),
            ("latency_ms", self.latency_ms),
        ):
            if value is not None and (isinstance(value, bool) or not math.isfinite(float(value))):
                raise ValueError(f"{name} must be finite")
        if not str(self.source_id).strip() or not str(self.request_id).strip():
            raise ValueError("source_id and request_id are required")


@dataclass(frozen=True, slots=True)
class SourceHealthSnapshot:
    source_id: str
    status: SourceStatus
    last_ok_ms: int | None = None
    last_fetch_ms: int | None = None
    age_ms: int | None = None          # since last OK fetch
    consecutive_errors: int = 0
    success_rate: float = 0.0          # over the recent window
    samples: int = 0
    last_error: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not str(self.source_id).strip():
            raise ValueError("source_id is required")
        if self.age_ms is not None and self.age_ms < 0:
            raise ValueError("age_ms must be non-negative")
        if self.consecutive_errors < 0 or self.samples < 0:
            raise ValueError("health counters must be non-negative")
        if isinstance(self.success_rate, bool) or not math.isfinite(float(self.success_rate)):
            raise ValueError("success_rate must be finite")
        if not 0.0 <= float(self.success_rate) <= 1.0:
            raise ValueError("success_rate must be in [0, 1]")

    @property
    def usable(self) -> bool:
        """Deny-by-default: only OK / DEGRADED data may feed a decision."""
        return self.status in (SourceStatus.OK, SourceStatus.DEGRADED)


__all__ = [
    "SourceKind",
    "SourceStatus",
    "SourceDefinition",
    "FetchProvenance",
    "SourceHealthSnapshot",
]
