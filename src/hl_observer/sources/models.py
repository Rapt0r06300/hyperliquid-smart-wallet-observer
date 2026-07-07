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
        if not self.read_only:
            raise ValueError("SourceDefinition.read_only must be True (no real external action)")


@dataclass(frozen=True, slots=True)
class FetchProvenance:
    source_id: str
    request_id: str
    fetched_at_ms: int                 # local clock when received
    ok: bool = True
    source_ts_ms: int | None = None    # server timestamp if available
    latency_ms: float | None = None
    rate_weight: int | None = None
    raw_hash: str | None = None
    parsed_hash: str | None = None
    item_count: int | None = None
    data_quality: str = "OK"           # OK | DEGRADED | BAD
    error: str | None = None


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
