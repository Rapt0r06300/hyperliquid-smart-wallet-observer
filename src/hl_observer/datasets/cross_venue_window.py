"""Strict eligibility gate for multi-venue replay/backtest windows.

A clean shard proves only its own integrity. Cross-venue validation additionally
requires same-run provenance, temporal overlap, exact instrument mapping and an
explicit pair-synchronisation report. Missing proof remains PARTIAL.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.datasets.strategy_data_contracts import get_strategy_data_contract

SAFE = "SAFE"
PARTIAL = "PARTIAL"
REJECT = "REJECT"
NO_DATA = "NO_DATA"


def build_cross_venue_window_manifest(
    manifests: Iterable[Mapping[str, Any]],
    *,
    canonical_coin: str,
    required_families_by_venue: Mapping[str, Iterable[str]],
    instrument_mapping_exact: bool,
    sync_report: Mapping[str, Any] | None,
    min_overlap_ms: int = 1_000,
    max_p95_receive_skew_ms: float = 250.0,
    max_receive_skew_ms: float = 500.0,
    min_sync_samples: int = 20,
    require_same_collection_run: bool = True,
) -> dict[str, Any]:
    rows = [dict(item) for item in manifests]
    if not rows:
        return {
            "schema": "alina.cross_venue_window.v1",
            "canonical_coin": str(canonical_coin).upper(),
            "quality_status": NO_DATA,
            "quality_reasons": ["NO_COMPONENTS"],
            "validation_allowed": False,
            "proof_of_pnl_allowed": False,
            "components": [],
        }

    reasons: list[str] = []
    severe: list[str] = []
    coin = str(canonical_coin or "").strip().upper()
    if not coin:
        severe.append("MISSING_CANONICAL_COIN")

    required = {
        str(venue).strip().lower(): {
            str(family).strip()
            for family in families
            if str(family).strip()
        }
        for venue, families in required_families_by_venue.items()
        if str(venue).strip()
    }

    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    starts: list[int] = []
    ends: list[int] = []
    run_ids: set[str] = set()
    component_ids: list[str] = []

    for row in rows:
        venue = str(row.get("venue") or "").strip().lower()
        family = str(row.get("family") or "").strip()
        by_key.setdefault((venue, family), []).append(row)
        dataset_id = str(row.get("dataset_id") or "")
        if dataset_id:
            component_ids.append(dataset_id)

        status = str(row.get("quality_status") or "").upper()
        if status == REJECT:
            severe.append(f"COMPONENT_REJECT:{dataset_id or venue + ':' + family}")
        elif status != SAFE or row.get("validation_allowed") is not True:
            reasons.append(f"COMPONENT_NOT_SAFE:{dataset_id or venue + ':' + family}")

        if row.get("asset_verified") is not True:
            reasons.append(f"COMPONENT_ASSET_UNVERIFIED:{dataset_id or venue + ':' + family}")

        start = _int(row.get("start_ts_ms"))
        end = _int(row.get("end_ts_ms"))
        if start is None or end is None or start <= 0 or end < start:
            severe.append(f"INVALID_COMPONENT_TIME:{dataset_id or venue + ':' + family}")
        else:
            starts.append(start)
            ends.append(end)

        run_id = str(row.get("collection_run_id") or "").strip()
        if run_id:
            run_ids.add(run_id)
        elif require_same_collection_run:
            reasons.append(f"MISSING_COLLECTION_RUN_ID:{dataset_id or venue + ':' + family}")

    for venue, families in required.items():
        for family in families:
            if not by_key.get((venue, family)):
                reasons.append(f"MISSING_REQUIRED_COMPONENT:{venue}:{family}")

    if not instrument_mapping_exact:
        reasons.append("INSTRUMENT_MAPPING_UNVERIFIED")

    if require_same_collection_run and len(run_ids) != 1:
        reasons.append("MULTIPLE_OR_UNKNOWN_COLLECTION_RUNS")

    overlap_start = max(starts) if starts else None
    overlap_end = min(ends) if ends else None
    overlap_ms: int | None = None
    if overlap_start is not None and overlap_end is not None:
        overlap_ms = overlap_end - overlap_start
        if overlap_ms < 0:
            severe.append("NO_TEMPORAL_OVERLAP")
        elif overlap_ms < int(min_overlap_ms):
            reasons.append("OVERLAP_TOO_SHORT")
    else:
        severe.append("UNRESOLVED_WINDOW_BOUNDS")

    sync = dict(sync_report or {})
    sync_status = str(sync.get("status") or "UNVERIFIED").upper()
    sample_count = _int(sync.get("sample_count")) or 0
    p95 = _float(sync.get("p95_receive_skew_ms"))
    maximum = _float(sync.get("max_receive_skew_ms"))
    sync_gaps = _int(sync.get("gap_count")) or 0
    if sync_status not in {"MATCHED", "PASS"}:
        reasons.append("PAIR_SYNC_UNVERIFIED")
    if sample_count < max(1, int(min_sync_samples)):
        reasons.append("PAIR_SYNC_SAMPLE_TOO_SMALL")
    if sync_gaps > 0:
        severe.append("PAIR_SYNC_GAPS")
    if p95 is None:
        reasons.append("PAIR_SYNC_P95_MISSING")
    elif p95 > float(max_p95_receive_skew_ms):
        reasons.append("PAIR_SYNC_P95_TOO_HIGH")
    if maximum is None:
        reasons.append("PAIR_SYNC_MAX_MISSING")
    elif maximum > float(max_receive_skew_ms):
        reasons.append("PAIR_SYNC_MAX_TOO_HIGH")

    if severe:
        status = REJECT
    elif reasons:
        status = PARTIAL
    else:
        status = SAFE

    return {
        "schema": "alina.cross_venue_window.v1",
        "canonical_coin": coin,
        "collection_run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
        "collection_run_ids": sorted(run_ids),
        "required_families_by_venue": {
            venue: sorted(families) for venue, families in sorted(required.items())
        },
        "component_count": len(rows),
        "components": sorted(component_ids),
        "window": {
            "start_ts_ms": overlap_start,
            "end_ts_ms": overlap_end,
            "overlap_ms": overlap_ms,
        },
        "instrument_mapping_exact": bool(instrument_mapping_exact),
        "pair_synchronization": {
            "status": sync_status,
            "sample_count": sample_count,
            "p95_receive_skew_ms": p95,
            "max_receive_skew_ms": maximum,
            "gap_count": sync_gaps,
        },
        "quality_status": status,
        "quality_reasons": sorted(set(severe + reasons)),
        "validation_allowed": status == SAFE,
        # Data completeness authorizes replay only. Profitability is a separate
        # output of the costed replay/backtest and must never be inferred here.
        "proof_of_pnl_allowed": False,
        "read_only": True,
        "real_execution": False,
    }


def build_strategy_window_manifest(
    manifests: Iterable[Mapping[str, Any]],
    *,
    strategy: str,
    canonical_coin: str,
    venues: Iterable[str],
    instrument_mapping_exact: bool,
    sync_report: Mapping[str, Any] | None,
    min_overlap_ms: int = 1_000,
) -> dict[str, Any]:
    """Apply the declared replay data contract for one strategy/window."""
    contract = get_strategy_data_contract(strategy)
    required = contract.for_venues(venues)
    result = build_cross_venue_window_manifest(
        manifests,
        canonical_coin=canonical_coin,
        required_families_by_venue=required,
        instrument_mapping_exact=instrument_mapping_exact,
        sync_report=sync_report,
        min_overlap_ms=min_overlap_ms,
        max_p95_receive_skew_ms=(
            float(contract.max_receive_skew_ms)
            if contract.max_receive_skew_ms is not None
            else 250.0
        ),
        max_receive_skew_ms=(
            float(contract.max_receive_skew_ms)
            if contract.max_receive_skew_ms is not None
            else 500.0
        ),
        min_sync_samples=contract.min_sync_samples,
        require_same_collection_run=contract.require_same_collection_run,
    )
    result["schema"] = "alina.strategy_window.v1"
    result["strategy"] = contract.strategy
    result["contract"] = {
        "max_receive_skew_ms": contract.max_receive_skew_ms,
        "max_exchange_skew_ms": contract.max_exchange_skew_ms,
        "min_sync_samples": contract.min_sync_samples,
        "require_exact_instrument_mapping": contract.require_exact_instrument_mapping,
        "require_same_collection_run": contract.require_same_collection_run,
        "require_reconciliation": contract.require_reconciliation,
    }
    return result


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "NO_DATA",
    "PARTIAL",
    "REJECT",
    "SAFE",
    "build_cross_venue_window_manifest",
    "build_strategy_window_manifest",
]
