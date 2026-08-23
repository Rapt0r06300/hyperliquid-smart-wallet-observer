"""Diagnostic causal de disponibilité du carnet autour des chocs Lead-Lag.

Ce module est volontairement séparé de la stratégie économique. Il répond à une
question de qualité de données : lorsqu'un choc source est observable, existe-t-il
un carnet Hyperliquid causal sous la limite d'exécution, et si non, les traces
publiques enregistrées portent-elles une preuve explicite de reconnexion/gap ?

Le seuil de choc utilisé par l'appelant peut être plus bas pour l'autopsie (par
exemple 8 bps) sans modifier le seuil économique figé de la stratégie (20 bps).
Aucun verdict économique, aucun ordre et aucune donnée future ne sont produits ici.
"""
from __future__ import annotations

import bisect
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_collection_gap_diagnostic.v1"


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _book_rows(
    books: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    rows = [
        dict(row)
        for row in books
        if _integer(row.get("ts_ms")) >= 1_500_000_000_000
    ]
    rows.sort(key=lambda row: _integer(row.get("ts_ms")))
    return rows, [_integer(row.get("ts_ms")) for row in rows]


def _explicit_gap_between(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if after is None:
        return False, reasons
    before_gap = _integer((before or {}).get("gap_count"))
    after_gap = _integer(after.get("gap_count"))
    if after_gap > before_gap:
        reasons.append("GAP_COUNT_INCREASED")
    before_reconnect = _integer((before or {}).get("reconnect_count"))
    after_reconnect = _integer(after.get("reconnect_count"))
    if after_reconnect > before_reconnect:
        reasons.append("RECONNECT_COUNT_INCREASED")
    connection_before = str((before or {}).get("connection_id") or "")
    connection_after = str(after.get("connection_id") or "")
    if connection_before and connection_after and connection_before != connection_after:
        reasons.append("CONNECTION_ID_CHANGED")
    return bool(reasons), reasons


def diagnose_shock_book_availability(
    shocks: Sequence[Mapping[str, Any]],
    books: Sequence[Mapping[str, Any]],
    *,
    max_book_delay_ms: int = 750,
    lookback_ms: int = 1_000,
    observation_horizon_ms: int = 15_000,
) -> dict[str, Any]:
    """Classifie chaque choc sans transformer absence de donnée en fait de marché.

    ``COLLECTOR_GAP_EXPLICIT`` n'est émis que lorsqu'un compteur de gap, une
    reconnexion ou un changement de connexion est effectivement observé entre le
    dernier carnet antérieur et le premier carnet postérieur. Sans cette preuve,
    un carnet tardif reste ``RECORDED_BOOK_DELAY_NO_EXPLICIT_GAP`` : ce diagnostic
    refuse d'inventer que le marché n'a pas coté ou que le collecteur a forcément
    perdu des messages.
    """

    clean_books, timestamps = _book_rows(books)
    rows: list[dict[str, Any]] = []
    limit_ms = max(0, int(max_book_delay_ms))
    before_window = max(0, int(lookback_ms))
    horizon_ms = max(limit_ms, int(observation_horizon_ms))

    for raw_shock in sorted(shocks, key=lambda row: _integer(row.get("trigger_ts_ms"))):
        trigger_ms = _integer(raw_shock.get("trigger_ts_ms"))
        if trigger_ms < 1_500_000_000_000:
            continue
        after_index = bisect.bisect_left(timestamps, trigger_ms)
        before_index = after_index - 1
        before = clean_books[before_index] if before_index >= 0 else None
        after = clean_books[after_index] if after_index < len(clean_books) else None

        before_delay = (
            trigger_ms - _integer(before.get("ts_ms")) if before is not None else None
        )
        after_delay = (
            _integer(after.get("ts_ms")) - trigger_ms if after is not None else None
        )
        before_in_window = before_delay is not None and 0 <= before_delay <= before_window
        after_in_horizon = after_delay is not None and 0 <= after_delay <= horizon_ms
        executable = after_delay is not None and 0 <= after_delay <= limit_ms
        explicit_gap, gap_reasons = _explicit_gap_between(before, after)

        if executable:
            classification = "CAUSAL_BOOK_WITHIN_EXECUTION_LIMIT"
        elif explicit_gap and (before_in_window or after_in_horizon):
            classification = "COLLECTOR_GAP_EXPLICIT"
        elif after_in_horizon:
            classification = "RECORDED_BOOK_DELAY_NO_EXPLICIT_GAP"
        elif before_in_window:
            classification = "NO_POST_SHOCK_BOOK_IN_OBSERVATION_HORIZON"
        else:
            classification = "INSUFFICIENT_SURROUNDING_BOOK_EVIDENCE"

        quality_ready = after.get("data_gate_ready") is True if after is not None else False
        rows.append(
            {
                "trigger_ts_ms": trigger_ms,
                "lead_shock_bps": raw_shock.get("lead_shock_bps"),
                "direction": raw_shock.get("direction"),
                "classification": classification,
                "executable_book_within_limit": executable,
                "max_book_delay_ms": limit_ms,
                "previous_book_ts_ms": _integer(before.get("ts_ms")) if before else None,
                "previous_book_age_ms": before_delay,
                "next_book_ts_ms": _integer(after.get("ts_ms")) if after else None,
                "next_book_delay_ms": after_delay,
                "next_book_data_gate_ready": quality_ready,
                "next_book_quality_reasons": list(after.get("quality_reasons") or ()) if after else [],
                "explicit_collector_gap": explicit_gap,
                "explicit_gap_reasons": gap_reasons,
                "previous_gap_count": _integer((before or {}).get("gap_count")),
                "next_gap_count": _integer((after or {}).get("gap_count")),
                "previous_reconnect_count": _integer((before or {}).get("reconnect_count")),
                "next_reconnect_count": _integer((after or {}).get("reconnect_count")),
            }
        )

    classifications = Counter(str(row["classification"]) for row in rows)
    executable_delays = [
        int(row["next_book_delay_ms"])
        for row in rows
        if row.get("next_book_delay_ms") is not None
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "shock_count": len(rows),
        "book_count": len(clean_books),
        "max_book_delay_ms": limit_ms,
        "lookback_ms": before_window,
        "observation_horizon_ms": horizon_ms,
        "classifications": dict(sorted(classifications.items())),
        "causal_book_within_limit_count": sum(
            row["executable_book_within_limit"] is True for row in rows
        ),
        "explicit_collector_gap_count": sum(
            row["explicit_collector_gap"] is True for row in rows
        ),
        "min_recorded_next_book_delay_ms": min(executable_delays) if executable_delays else None,
        "max_recorded_next_book_delay_ms": max(executable_delays) if executable_delays else None,
        "events": rows,
        "interpretation_rule": (
            "NO_EXPLICIT_GAP_NEVER_PROVES_MARKET_ABSENCE_OR_COLLECTOR_HEALTH"
        ),
        "economic_parameters_modified": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "diagnose_shock_book_availability"]
