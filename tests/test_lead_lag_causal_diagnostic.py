from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostic import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_availability,
)


def _shock(ts_ms: int, *, bps: float = 8.5) -> dict:
    return {
        "trigger_ts_ms": ts_ms,
        "lead_shock_bps": bps,
        "direction": 1 if bps > 0 else -1,
    }


def _book(
    ts_ms: int,
    *,
    ready: bool = True,
    gap_count: int = 0,
    reconnect_count: int = 0,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "bid": 100.0,
        "ask": 100.1,
        "bid_size": 3.0,
        "ask_size": 3.0,
        "data_gate_ready": ready,
        "connection_id": "ws-test",
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "quality_reasons": list(reasons or []),
        "read_only": True,
        "real_execution": False,
    }


def test_diagnostic_separe_carnet_executable_tardif_et_rejete() -> None:
    base = 1_786_552_000_000
    shocks = [
        _shock(base),
        _shock(base + 10_000),
        _shock(base + 20_000),
    ]
    books = {
        "ETH": [
            _book(base + 500),
            _book(base + 12_295),
            _book(base + 20_400, ready=False, reasons=["QUALITY_LOW"]),
        ]
    }

    result = diagnose_causal_book_availability(shocks, books)

    assert result["shock_count"] == 3
    assert result["classifications"] == {
        "BOOK_WITHIN_BUDGET_QUALITY_REJECTED": 1,
        "EXECUTABLE_CAUSAL_BOOK": 1,
        "LATE_CAUSAL_BOOK": 1,
    }
    assert result["events"][0]["first_causal_book_delay_ms"] == 500
    assert result["events"][1]["first_causal_book_delay_ms"] == 2295
    assert result["events"][2]["first_causal_book_delay_ms"] == 400
    assert result["conclusion"] == "EXECUTABLE_BOOKS_EXIST_IN_DIAGNOSTIC_SAMPLE"


def test_diagnostic_distingue_gap_collecte_prouve_et_absence_non_prouvee() -> None:
    base = 1_786_552_000_000
    shocks = [_shock(base + 1_000), _shock(base + 40_000)]
    books = {
        "ETH": [
            _book(base, gap_count=2, reconnect_count=1, reasons=["SEQUENCE_GAP"]),
        ]
    }

    result = diagnose_causal_book_availability(shocks, books, lookahead_ms=5_000)

    # Le même dernier book antérieur porte une preuve explicite de gap pour les
    # deux événements : l'outil refuse donc d'appeler cela une absence "marché".
    assert result["explicit_collection_gap_events"] == 2
    assert result["gap_unproven_events"] == 0
    assert result["conclusion"] == (
        "COLLECTION_GAPS_EXPLAIN_AT_LEAST_PART_OF_MISSING_EXECUTION_EVIDENCE"
    )
    assert all(event["explicit_gap_evidence"] is True for event in result["events"])


def test_diagnostic_fail_closed_sans_book_ni_preuve_de_gap() -> None:
    result = diagnose_causal_book_availability(
        [_shock(1_786_552_000_000)],
        {"ETH": []},
    )

    assert result["gap_unproven_events"] == 1
    assert result["explicit_collection_gap_events"] == 0
    assert result["conclusion"] == "NO_EXECUTABLE_BOOK_AND_NO_EXPLICIT_GAP_PROOF"


def test_diagnostic_8bps_ne_modifie_jamais_la_strategie_economique() -> None:
    result = diagnose_causal_book_availability([], {"ETH": []})

    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert result["diagnostic_shock_threshold_bps"] == 8.0
    assert result["purpose"] == "SOURCE_COVERAGE_DIAGNOSTIC_ONLY_NOT_ECONOMIC_TUNING"
    assert result["economic_threshold_unchanged"] is True
    assert result["creates_trades"] is False
    assert result["changes_strategy_parameters"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
