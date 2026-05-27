from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from hl_observer.utils.math import clamp
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_validation import ValidationResult


class LeaderboardSourceStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PARSER_FAILED = "PARSER_FAILED"
    ONLY_TRUNCATED_ADDRESSES = "ONLY_TRUNCATED_ADDRESSES"
    IMPORT_REQUIRED = "IMPORT_REQUIRED"
    IMPORT_OK = "IMPORT_OK"
    NO_FULL_ADDRESS = "NO_FULL_ADDRESS"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class LeaderboardRowRecord(BaseModel):
    rank: int | None = None
    address: str | None = None
    address_short: str | None = None
    account_value_usdc: float | None = None
    pnl_usdc: float | None = None
    roi_pct: float | None = None
    volume_usdc: float | None = None
    period: str = "30D"
    source_method: str = "unknown"
    extraction_method: str = "unknown"
    source_payload_hash: str | None = None
    validation: ValidationResult | None = None
    source_confidence_score: float = 0.0
    raw: dict = Field(default_factory=dict)


class LeaderboardCandidate(BaseModel):
    wallet_address: str
    rank: int | None = None
    period: str = "30D"
    account_value_usdc: float | None = None
    pnl_usdc: float | None = None
    roi_pct: float | None = None
    volume_usdc: float | None = None
    leaderboard_score: float = 0.0
    selected_for_revalidation: bool = True
    selected_for_backfill: bool = False
    source_confidence: float = 0.0
    notes: str | None = None


class LeaderboardResult(BaseModel):
    run_id: int | None = None
    period: str = "30D"
    method: str = "auto"
    status: LeaderboardSourceStatus = LeaderboardSourceStatus.IMPORT_REQUIRED
    rows_seen: int = 0
    full_addresses_found: int = 0
    truncated_addresses_seen: int = 0
    candidates_created: int = 0
    rows: list[LeaderboardRowRecord] = Field(default_factory=list)
    candidates: list[LeaderboardCandidate] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    started_at_ms: int = Field(default_factory=now_ms)
    finished_at_ms: int | None = None
    notes: list[str] = Field(default_factory=list)
    error_message: str | None = None

    @classmethod
    def from_rows(
        cls,
        rows: list[LeaderboardRowRecord],
        *,
        period: str = "30D",
        method: str = "auto",
        status: LeaderboardSourceStatus | None = None,
        notes: list[str] | None = None,
    ) -> "LeaderboardResult":
        candidates: list[LeaderboardCandidate] = []
        rejected: list[dict] = []
        full = 0
        truncated = 0
        for row in rows:
            if row.validation is not None and row.validation.is_full_address:
                full += 1
            if row.validation is not None and row.validation.is_truncated:
                truncated += 1
            candidate = row_to_candidate(row)
            if candidate is None:
                rejected.append(
                    {
                        "raw_value": row.address_short or row.address or "",
                        "reason": row.validation.validation_status.value if row.validation is not None else "INVALID",
                    }
                )
                continue
            candidates.append(candidate)
        resolved_status = status
        if resolved_status is None:
            resolved_status = LeaderboardSourceStatus.OK if candidates else LeaderboardSourceStatus.IMPORT_REQUIRED
            if truncated and not candidates:
                resolved_status = LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
        return cls(
            period=period,
            method=method,
            status=resolved_status,
            rows_seen=len(rows),
            full_addresses_found=full,
            truncated_addresses_seen=truncated,
            candidates_created=len(candidates),
            rows=rows,
            candidates=candidates,
            rejected=rejected,
            finished_at_ms=now_ms(),
            notes=notes or [],
        )


def score_leaderboard_row(row: LeaderboardRowRecord) -> float:
    pnl_score = 50.0 if row.pnl_usdc is None else clamp(50.0 + row.pnl_usdc / 100_000.0 * 50.0, 0.0, 100.0)
    roi_score = 50.0 if row.roi_pct is None else clamp(50.0 + row.roi_pct, 0.0, 100.0)
    account_value_score = 50.0 if row.account_value_usdc is None else clamp(row.account_value_usdc / 1_000_000.0 * 100.0, 0.0, 100.0)
    volume_score = 50.0 if row.volume_usdc is None else clamp(row.volume_usdc / 10_000_000.0 * 100.0, 0.0, 100.0)
    rank_score = 50.0 if row.rank is None else clamp(100.0 - max(0, row.rank - 1) / 500.0 * 100.0, 0.0, 100.0)
    return clamp(
        0.30 * pnl_score
        + 0.25 * roi_score
        + 0.15 * account_value_score
        + 0.10 * volume_score
        + 0.10 * rank_score
        + 0.10 * row.source_confidence_score,
        0.0,
        100.0,
    )


def row_to_candidate(row: LeaderboardRowRecord) -> LeaderboardCandidate | None:
    if row.validation is None or not row.validation.is_full_address or row.validation.normalized_value is None:
        return None
    score = score_leaderboard_row(row)
    return LeaderboardCandidate(
        wallet_address=row.validation.normalized_value,
        rank=row.rank,
        period=row.period,
        account_value_usdc=row.account_value_usdc,
        pnl_usdc=row.pnl_usdc,
        roi_pct=row.roi_pct,
        volume_usdc=row.volume_usdc,
        leaderboard_score=score,
        selected_for_revalidation=True,
        selected_for_backfill=score >= 50.0,
        source_confidence=row.source_confidence_score,
        notes="leaderboard_full_address",
    )
