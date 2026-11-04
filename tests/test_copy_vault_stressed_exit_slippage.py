from __future__ import annotations

from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_executable import execute_metaorder
from hl_observer.economics.assumptions import EconomicRunMode


def test_sortie_certifiable_marche_le_book_stresse_et_mesure_le_slippage():
    metaorder = cluster_metaorders([{
        "event_id": "stress-exit",
        "ts_ms": 1_000,
        "coin": "BTC",
        "direction": 1,
        "action": "OPEN",
        "dir": "Open Long",
        "vault": "0xA",
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }])[0][0]
    books = [
        {
            "ts_ms": 1_000, "bid": 99.0, "ask": 101.0, "capacity_usd": 1_000.0,
            "bids5": [[99.0, 20.0]], "asks5": [[101.0, 20.0]],
            "source_line": 1,
        },
        {
            "ts_ms": 61_000, "bid": 100.0, "ask": 102.0, "capacity_usd": 1_000.0,
            "bids5": [[100.0, 0.5], [99.0, 2.0]],
            "asks5": [[102.0, 0.5], [104.0, 2.0]],
            "source_line": 2,
        },
        {
            "ts_ms": 361_000, "bid": 109.0, "ask": 111.0, "capacity_usd": 1_000.0,
            "bids5": [[109.0, 0.5], [108.0, 2.0]],
            "asks5": [[111.0, 0.5], [113.0, 2.0]],
            "source_line": 3,
        },
    ]

    trade, reason = execute_metaorder(
        metaorder,
        books,
        horizon_ms=300_000,
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["exit_price"] < 109.0
    assert trade["slippage_cost_usd"] > 0.0
    assert trade["cost_component_receipts"]["slippage"]["formula_id"] == (
        "copy_vault.observed_l2_vwap.v1"
    )
