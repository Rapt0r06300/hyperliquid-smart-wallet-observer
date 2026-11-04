from __future__ import annotations

import pytest

from hl_observer.datasets.strategy_data_contracts import (
    evaluate_copy_vault_replay_readiness,
    get_strategy_data_contract,
    missing_required_families,
)


def test_cross_venue_contract_requires_depth_trades_and_context() -> None:
    contract = get_strategy_data_contract("cross-venue")
    assert contract.max_receive_skew_ms == 250.0
    assert contract.require_exact_instrument_mapping is True
    assert {"bbo", "l2Book", "trades", "activeAssetCtx"}.issubset(
        contract.required_families_by_venue["hyperliquid"]
    )
    assert {"bbo", "l2Book", "agg_trades", "mark_funding", "open_interest"}.issubset(
        contract.required_families_by_venue["binance"]
    )
    assert "trades" not in contract.required_families_by_venue["binance"]
    assert {"l2Book", "trades", "ticker"}.issubset(
        contract.required_families_by_venue["bybit"]
    )
    assert {
        "l2Book",
        "trades",
        "ticker",
        "funding",
        "open_interest",
        "mark_price",
        "index_price",
    }.issubset(contract.required_families_by_venue["okx"])


def test_lead_lag_contract_is_stricter_on_sync() -> None:
    contract = get_strategy_data_contract("lead_lag")
    assert contract.max_receive_skew_ms == 100.0
    assert contract.max_exchange_skew_ms == 100.0
    assert contract.min_sync_samples == 50


def test_copy_vault_contract_requires_live_fill_and_market_context() -> None:
    contract = get_strategy_data_contract("copy_vault")
    assert set(contract.required_families_by_venue) == {"hyperliquid"}
    required = contract.required_families_by_venue["hyperliquid"]
    assert {"userFills", "bbo", "l2Book", "trades", "activeAssetCtx"}.issubset(required)


def test_missing_required_families_never_silently_pass() -> None:
    manifests = [
        {"venue": "hyperliquid", "family": "bbo"},
        {"venue": "hyperliquid", "family": "l2Book"},
        {"venue": "binance", "family": "bbo"},
        {"venue": "binance", "family": "l2Book"},
    ]
    missing = missing_required_families(
        manifests,
        strategy="cross_venue",
        venues=["hyperliquid", "binance"],
    )
    assert "trades" in missing["hyperliquid"]
    assert "activeAssetCtx" in missing["hyperliquid"]
    assert "agg_trades" in missing["binance"]
    assert "mark_funding" in missing["binance"]


def test_unknown_strategy_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_strategy_data_contract("unknown")


def test_copy_vault_replay_ready_is_distinct_from_live_observer_ready() -> None:
    manifests = [
        {"venue": "hyperliquid", "family": family, "run_id": "safe-run-1"}
        for family in ("userFills", "bbo", "l2Book", "trades", "activeAssetCtx", "instrument_metadata")
    ]
    not_ready = evaluate_copy_vault_replay_readiness(
        manifests,
        observed_book_audit={"replay_grade_ready": False},
    )
    assert not_ready["ready"] is False
    assert not_ready["status"] == "DATA_NOT_READY"
    assert not_ready["live_observer_ready_is_not_replay_ready"] is True
    assert "OBSERVED_BOOK_REPLAY_GRADE_NOT_READY" in not_ready["blockers"]

    ready = evaluate_copy_vault_replay_readiness(
        manifests,
        observed_book_audit={"replay_grade_ready": True},
    )
    assert ready["ready"] is True
    assert ready["status"] == "READY_REPLAY"
    assert ready["paper_read_only"] is True
    assert ready["real_execution"] is False
