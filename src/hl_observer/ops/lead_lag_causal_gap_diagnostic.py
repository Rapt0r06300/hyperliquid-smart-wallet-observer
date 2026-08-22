"""Fail-closed causal book-availability diagnostic for Lead-Lag research.

The 8 bps threshold in this module is DIAGNOSTIC ONLY.  It exists to explain
why the already-observed smaller Binance shocks did or did not have a causal
Hyperliquid book available quickly enough.  It MUST NOT change the frozen
20 bps economic Lead-Lag hypothesis, produce trades, or promote PnL.

All inputs are recorded public market data.  No network access and no order
execution surface exist in this module.
"""
from __future__ import annotations

import bisect
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_queue_replay import (
    MAX_BOOK_DELAY_MS,
    SHOCK_THRESHOLD_BPS,
    detect_rolling_shocks,
)
from hl_observer.backtesting.lead_lag_source_alignment import (
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)
from hl_observer.datasets.source_discovery import (
    is_dataset_workspace,
    load_family_source_paths,
)
from hl_observer.simulation.lead_lag_l2_history import (
    load_market_microstructure_event_windows,
)

SCHEMA_VERSION = "hypersmart.lead_lag_causal_gap_diagnostic.v1"
DIAGNOSTIC_SHOCK_THRESHOLD_BPS = 8.0
ECONOMIC_SHOCK_THRESHOLD_BPS = float(SHOCK_THRESHOLD_BPS)
DIAGNOSTIC_MAX_BOOK_DELAY_MS = int(MAX_BOOK_DELAY_MS)
REPORT_FILENAME = "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC.json"
REPORT_MARKDOWN_FILENAME = "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC.md"


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)


def _book_view(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "ts_ms": _integer(row.get("ts_ms")),
        "received_ts_ms": _integer(row.get("received_ts_ms")),
        "written_ts_ms": _integer(row.get("written_ts_ms")),
        "exchange_ts_ms": (
            _integer(row.get("exchange_ts_ms")) if row.get("exchange_ts_ms") is not None else None
        ),
        "data_gate_ready": row.get("data_gate_ready") is True,
        "feed_quality_score": row.get("feed_quality_score"),
        "quality_reasons": list(row.get("quality_reasons") or ()),
        "gap_count": _integer(row.get("gap_count")),
        "reconnect_count": _integer(row.get("reconnect_count")),
        "connection_id": row.get("connection_id"),
        "sequence": row.get("sequence"),
        "source": row.get("source"),
    }


def diagnose_causal_book_availability(
    event_ts_ms: Sequence[int],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    coin: str = "ETH",
    max_delay_ms: int = DIAGNOSTIC_MAX_BOOK_DELAY_MS,
) -> dict[str, Any]:
    """Classify recorded book availability without inferring unobserved market state.

    A late book is called a collector gap only when the recorded gap/reconnect
    counters provide explicit evidence.  Otherwise the result deliberately says
    that the next recorded book was too late *without gap proof*; absence of a
    collector flag is not enough to claim that the market itself had no book.
    """

    selected_coin = str(coin).upper()
    books = sorted(
        [dict(row) for row in books_by_coin.get(selected_coin, ())],
        key=lambda row: _integer(row.get("ts_ms")),
    )
    timestamps = [_integer(row.get("ts_ms")) for row in books]
    limit = max(0, int(max_delay_ms))
    rows: list[dict[str, Any]] = []

    for raw_event in sorted({_integer(value) for value in event_ts_ms if _integer(value) > 0}):
        index = bisect.bisect_left(timestamps, raw_event)
        previous = books[index - 1] if index > 0 else None
        following = books[index] if index < len(books) else None
        previous_view = _book_view(previous)
        following_view = _book_view(following)
        delay_ms = None if following is None else _integer(following.get("ts_ms")) - raw_event
        gap_delta = None
        reconnect_delta = None
        if previous is not None and following is not None:
            gap_delta = max(
                0,
                _integer(following.get("gap_count")) - _integer(previous.get("gap_count")),
            )
            reconnect_delta = max(
                0,
                _integer(following.get("reconnect_count"))
                - _integer(previous.get("reconnect_count")),
            )

        explicit_gap = bool((gap_delta or 0) > 0 or (reconnect_delta or 0) > 0)
        if following is None:
            classification = "NO_LATER_BOOK_RECORDED"
        elif delay_ms is not None and 0 <= delay_ms <= limit:
            classification = (
                "CAUSAL_BOOK_WITHIN_750MS"
                if following.get("data_gate_ready") is True
                else "CAUSAL_BOOK_WITHIN_750MS_REJECTED_QUALITY"
            )
        elif explicit_gap:
            classification = "EXPLICIT_COLLECTOR_GAP_BEFORE_NEXT_BOOK"
        else:
            classification = "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF"

        rows.append(
            {
                "event_ts_ms": raw_event,
                "classification": classification,
                "max_delay_ms": limit,
                "next_book_delay_ms": delay_ms,
                "explicit_collector_gap": explicit_gap,
                "gap_count_delta": gap_delta,
                "reconnect_count_delta": reconnect_delta,
                "previous_book": previous_view,
                "next_book": following_view,
            }
        )

    counts = Counter(row["classification"] for row in rows)
    executable = counts["CAUSAL_BOOK_WITHIN_750MS"]
    explicit_gaps = counts["EXPLICIT_COLLECTOR_GAP_BEFORE_NEXT_BOOK"]
    unexplained_late = counts["NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF"]
    no_later = counts["NO_LATER_BOOK_RECORDED"]
    rejected_quality = counts["CAUSAL_BOOK_WITHIN_750MS_REJECTED_QUALITY"]

    if not rows:
        root_cause = "NO_DIAGNOSTIC_SHOCKS"
    elif executable:
        root_cause = "EXECUTABLE_CAUSAL_BOOK_OBSERVED_FOR_AT_LEAST_ONE_EVENT"
    elif explicit_gaps and explicit_gaps == len(rows):
        root_cause = "COLLECTION_GAP_EXPLICITLY_PROVEN_FOR_ALL_EVENTS"
    elif explicit_gaps:
        root_cause = "MIXED_COLLECTION_GAP_AND_UNRESOLVED_BOOK_ABSENCE"
    elif rejected_quality and rejected_quality == len(rows):
        root_cause = "BOOKS_TIMELY_BUT_QUALITY_GATE_REJECTED"
    elif unexplained_late or no_later:
        root_cause = "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"
    else:
        root_cause = "UNRESOLVED_FAIL_CLOSED"

    return {
        "schema_version": SCHEMA_VERSION,
        "coin": selected_coin,
        "event_count": len(rows),
        "book_count": len(books),
        "max_causal_book_delay_ms": limit,
        "classification_counts": dict(sorted(counts.items())),
        "root_cause": root_cause,
        "events": rows,
        "interpretation_guard": (
            "A missing explicit collector gap does not prove market absence; it only means "
            "the recorded evidence does not prove a collector gap."
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


def build_lead_lag_causal_gap_diagnostic(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    candidates = (
        load_family_source_paths(project_root, "lead_lag")
        if is_dataset_workspace(project_root)
        else None
    )
    aligned_sources, alignment = select_aligned_bbo_sources(
        project_root,
        candidates=candidates,
    )
    tape, tape_meta = load_aligned_binance_trade_tape(project_root, aligned_sources)
    trades = (tape.get("ETH") or {}).get("TRADE") or ()
    diagnostic_shocks = detect_rolling_shocks(
        trades,
        threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    )
    event_timestamps = [int(row["trigger_ts_ms"]) for row in diagnostic_shocks]
    books, public_trades, history_meta = load_market_microstructure_event_windows(
        project_root,
        event_timestamps,
    )
    availability = diagnose_causal_book_availability(event_timestamps, books)
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "DATA_QUALITY_AND_CAUSAL_BOOK_AVAILABILITY_ONLY",
        "diagnostic_threshold_bps": DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
        "economic_threshold_bps": ECONOMIC_SHOCK_THRESHOLD_BPS,
        "threshold_separation_enforced": (
            DIAGNOSTIC_SHOCK_THRESHOLD_BPS < ECONOMIC_SHOCK_THRESHOLD_BPS
        ),
        "economic_parameters_modified": False,
        "diagnostic_shocks": diagnostic_shocks,
        "source_alignment": alignment,
        "aligned_lead_tape": tape_meta,
        "microstructure_history": history_meta,
        "public_trade_rows_loaded": sum(len(rows) for rows in public_trades.values()),
        "causal_book_availability": availability,
        "paper_read_only": True,
        "real_execution": False,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    availability = payload.get("causal_book_availability")
    if not isinstance(availability, Mapping):
        availability = {}
    lines = [
        "# Lead-Lag causal gap diagnostic",
        "",
        "**DIAGNOSTIC ONLY — the economic threshold remains 20 bps.**",
        "",
        f"- diagnostic shock threshold: `{payload.get('diagnostic_threshold_bps')} bps`",
        f"- economic shock threshold: `{payload.get('economic_threshold_bps')} bps`",
        f"- diagnostic events: `{availability.get('event_count', 0)}`",
        f"- root cause: `{availability.get('root_cause', 'UNKNOWN')}`",
        "- paper/read-only: `true`",
        "",
        "The absence of an explicit collector-gap counter is never interpreted as proof "
        "that the market itself had no executable book.",
        "",
        "## Events",
        "",
    ]
    for row in availability.get("events", ()):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "- `{} ms` → `{}` | next delay=`{}` ms | gap_delta=`{}` | reconnect_delta=`{}`".format(
                row.get("event_ts_ms"),
                row.get("classification"),
                row.get("next_book_delay_ms"),
                row.get("gap_count_delta"),
                row.get("reconnect_count_delta"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_lead_lag_causal_gap_diagnostic(
    root: str | Path,
    *,
    output_dir: str | Path,
) -> tuple[Path, Path, dict[str, Any]]:
    payload = build_lead_lag_causal_gap_diagnostic(root)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / REPORT_FILENAME
    markdown_path = destination / REPORT_MARKDOWN_FILENAME
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, json_path)
    markdown_path.write_text(_markdown(payload), encoding="utf-8", newline="\n")
    return json_path, markdown_path, payload


__all__ = [
    "DIAGNOSTIC_MAX_BOOK_DELAY_MS",
    "DIAGNOSTIC_SHOCK_THRESHOLD_BPS",
    "ECONOMIC_SHOCK_THRESHOLD_BPS",
    "SCHEMA_VERSION",
    "build_lead_lag_causal_gap_diagnostic",
    "diagnose_causal_book_availability",
    "write_lead_lag_causal_gap_diagnostic",
]
