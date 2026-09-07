from __future__ import annotations

from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE
from hl_observer.backtesting.cross_venue_v3_train import (
    FEES_ROUND_TRIP_BPS,
    explore_cross_venue_v3_train,
    replay_variant_train,
)


def _atomic(ts: int, hl_mid: float, bin_mid: float) -> tuple:
    half = 0.005
    return (
        ts,
        "ATOMIC",
        hl_mid - half,
        hl_mid + half,
        bin_mid - half,
        bin_mid + half,
    )


def _source_meta() -> dict[str, object]:
    return {
        "source_mode": BBO_SOURCE_MODE,
        "mapping_verified": True,
        "instrument_mapping_schema": "cross_venue_instrument_mapping_v2",
        "contract_multipliers_normalized": True,
        "quote_currencies_normalized": True,
        "sizes_normalized_to_usd_notional": True,
    }


def test_cross_v3_rejoue_impulsion_puis_entree_retardee_et_quatre_fills() -> None:
    start = 1_800_000_000_000
    series = {
        "BTC": [
            _atomic(start, 100.0, 100.0),
            _atomic(start + 1_000, 100.25, 100.0),
            _atomic(start + 1_400, 100.25, 100.0),
            _atomic(start + 2_500, 100.05, 100.05),
        ]
    }
    depth = {
        "BTC": [(row[0], 1_000.0) for row in series["BTC"]],
    }

    trades, diagnostics = replay_variant_train(
        series,
        depth,
        leader_threshold_bps=8.0,
        max_hold_ms=10_000,
        train_end_ms=start + 20_000,
    )

    assert diagnostics["CLOSED_LIQUIDATABLE_TRADE"] == 1
    assert len(trades) == 1
    trade = trades[0]
    assert trade["leader_venue"] == "HL"
    assert trade["entry_ts_ms"] == start + 1_400
    assert trade["exit_ts_ms"] == start + 2_500
    assert trade["four_fills_complete"] is True
    assert trade["two_leg"] is True
    assert trade["LIQUIDATABLE_NET"] is True
    assert trade["economic_reconciliation_ok"] is True
    assert trade["fees_round_trip_bps"] == 18.0
    assert trade["fees_usd"] == 15.0 * 18.0 / 10_000.0
    assert trade["entry_executable_edge_bps"] > FEES_ROUND_TRIP_BPS
    assert trade["real_execution"] is False


def test_cross_v3_refuse_un_ecart_executable_inferieur_aux_quatre_frais() -> None:
    start = 1_800_000_000_000
    series = {
        "BTC": [
            _atomic(start, 100.0, 100.0),
            _atomic(start + 1_000, 100.10, 100.0),
            _atomic(start + 1_400, 100.10, 100.0),
            _atomic(start + 2_500, 100.05, 100.05),
        ]
    }
    depth = {"BTC": [(row[0], 1_000.0) for row in series["BTC"]]}

    trades, diagnostics = replay_variant_train(
        series,
        depth,
        leader_threshold_bps=8.0,
        max_hold_ms=10_000,
        train_end_ms=start + 20_000,
    )

    assert trades == []
    assert diagnostics["ENTRY_EDGE_CANNOT_COVER_FEES"] == 1


def test_cross_v3_accepte_la_source_bbo_atomique_certifiee() -> None:
    start = 1_800_000_000_000
    series = {"BTC": [_atomic(start, 100.0, 100.0), _atomic(start + 1_000, 100.1, 100.0)]}
    depth = {"BTC": [(row[0], 1_000.0) for row in series["BTC"]]}
    result = explore_cross_venue_v3_train(
        series,
        depth,
        source_mode=BBO_SOURCE_MODE,
        source_meta=_source_meta(),
    )
    assert result["status"] != "MORE_DATA_CERTIFIED_ATOMIC_BOOK_REQUIRED"
    assert result["source_mode"] == BBO_SOURCE_MODE
    assert result["instrument_normalization_verified"] is True
    assert result["cost_contract"] == {
        "fee_bps_hyperliquid_per_fill": 4.5,
        "fee_bps_binance_per_fill": 4.5,
        "fees_round_trip_bps": 18.0,
        "fee_fill_count": 4,
        "spread_embedded_in_executable_prices": True,
        "entry_must_cover_fee_only_burden": True,
    }
    assert result["real_execution"] is False


def test_cross_v3_refuse_source_mode_certifie_sans_preuve_de_normalisation_instrument() -> None:
    start = 1_800_000_000_000
    series = {"BTC": [_atomic(start, 100.0, 100.0), _atomic(start + 1_000, 100.1, 100.0)]}
    depth = {"BTC": [(row[0], 1_000.0) for row in series["BTC"]]}

    result = explore_cross_venue_v3_train(
        series,
        depth,
        source_mode=BBO_SOURCE_MODE,
        source_meta={"source_mode": BBO_SOURCE_MODE, "mapping_verified": True},
    )

    assert result["status"] == "INSTRUMENT_NORMALIZATION_PROOF_REQUIRED"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["instrument_normalization_verified"] is False
    assert result["real_execution"] is False


def test_cross_v3_refuse_un_cycle_qui_traverse_un_funding_hl_non_price() -> None:
    # Hyperliquid settles funding every hour.  Without a certified funding rate
    # in the replay input, a paper cycle spanning that boundary must fail closed.
    funding_boundary = 1_800_000_000_000
    start = funding_boundary - 2_000
    series = {
        "BTC": [
            _atomic(start, 100.0, 100.0),
            _atomic(start + 1_000, 100.25, 100.0),
            _atomic(start + 1_400, 100.25, 100.0),
            _atomic(start + 2_500, 100.05, 100.05),
        ]
    }
    depth = {"BTC": [(row[0], 1_000.0) for row in series["BTC"]]}

    trades, diagnostics = replay_variant_train(
        series,
        depth,
        leader_threshold_bps=8.0,
        max_hold_ms=10_000,
        train_end_ms=funding_boundary + 20_000,
    )

    assert trades == []
    assert diagnostics["FUNDING_BOUNDARY_UNPRICED"] == 1
