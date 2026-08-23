from __future__ import annotations

from hl_observer.backtesting.lead_lag_collection_gap_diagnostic import (
    diagnose_shock_book_availability,
)


def _shock(ts_ms: int, bps: float = 8.0) -> dict:
    return {
        "trigger_ts_ms": ts_ms,
        "lead_shock_bps": bps,
        "direction": 1,
    }


def _book(
    ts_ms: int,
    *,
    gap_count: int = 0,
    reconnect_count: int = 0,
    connection_id: str = "c1",
    ready: bool = True,
) -> dict:
    return {
        "ts_ms": ts_ms,
        "bid": 100.0,
        "ask": 100.1,
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "connection_id": connection_id,
        "data_gate_ready": ready,
        "quality_reasons": [] if ready else ["STALE"],
    }


def test_book_sous_750ms_est_classe_executable() -> None:
    t0 = 1_800_000_000_000
    result = diagnose_shock_book_availability(
        [_shock(t0)],
        [_book(t0 - 100), _book(t0 + 250)],
    )

    event = result["events"][0]
    assert event["classification"] == "CAUSAL_BOOK_WITHIN_EXECUTION_LIMIT"
    assert event["executable_book_within_limit"] is True
    assert event["next_book_delay_ms"] == 250
    assert result["causal_book_within_limit_count"] == 1
    assert result["economic_parameters_modified"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_retard_avec_compteur_gap_est_preuve_collecteur_explicite() -> None:
    t0 = 1_800_000_000_000
    result = diagnose_shock_book_availability(
        [_shock(t0)],
        [
            _book(t0 - 100, gap_count=2, reconnect_count=4, connection_id="c1"),
            _book(t0 + 2_295, gap_count=3, reconnect_count=5, connection_id="c2"),
        ],
    )

    event = result["events"][0]
    assert event["classification"] == "COLLECTOR_GAP_EXPLICIT"
    assert event["explicit_collector_gap"] is True
    assert set(event["explicit_gap_reasons"]) == {
        "GAP_COUNT_INCREASED",
        "RECONNECT_COUNT_INCREASED",
        "CONNECTION_ID_CHANGED",
    }
    assert result["explicit_collector_gap_count"] == 1


def test_retard_sans_trace_gap_ne_devient_pas_fausse_preuve_de_marche() -> None:
    t0 = 1_800_000_000_000
    result = diagnose_shock_book_availability(
        [_shock(t0)],
        [_book(t0 - 100), _book(t0 + 4_715)],
    )

    event = result["events"][0]
    assert event["classification"] == "RECORDED_BOOK_DELAY_NO_EXPLICIT_GAP"
    assert event["explicit_collector_gap"] is False
    assert event["executable_book_within_limit"] is False
    assert result["interpretation_rule"] == (
        "NO_EXPLICIT_GAP_NEVER_PROVES_MARKET_ABSENCE_OR_COLLECTOR_HEALTH"
    )


def test_absence_totale_autour_du_choc_reste_insuffisante() -> None:
    t0 = 1_800_000_000_000
    result = diagnose_shock_book_availability(
        [_shock(t0)],
        [_book(t0 - 20_000), _book(t0 + 30_000)],
    )

    event = result["events"][0]
    assert event["classification"] == "INSUFFICIENT_SURROUNDING_BOOK_EVIDENCE"
    assert event["next_book_delay_ms"] == 30_000


def test_diagnostic_ne_depend_pas_de_l_ordre_des_carnets() -> None:
    t0 = 1_800_000_000_000
    books = [_book(t0 + 500), _book(t0 - 300), _book(t0 + 2_000)]
    result = diagnose_shock_book_availability([_shock(t0)], books)

    assert result["events"][0]["next_book_delay_ms"] == 500
    assert result["events"][0]["previous_book_age_ms"] == 300
    assert result["min_recorded_next_book_delay_ms"] == 500
