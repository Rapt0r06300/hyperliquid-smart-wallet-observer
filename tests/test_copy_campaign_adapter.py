from __future__ import annotations

from hl_observer.simulation.copy_campaign_adapter import build_strict_copy_campaign


def _report(*, trades: list[dict], n_trades: int | None = None) -> dict:
    count = len(trades) if n_trades is None else n_trades
    return {
        "n_entrees_alpha": count,
        "source_prix": "candles_5m",
        "mesure": {
            "statut": "VALIDATION",
            "decision": "SCALE",
            "oos": {
                "net_bps": 10.0,
                "placebo_bps": 1.0,
                "edge_vs_placebo_bps": 9.0,
            },
            "generalisation_par_vault": {
                "n": 20,
                "net_bps": 2.0,
                "vaults_held_out": ["0xheld"],
            },
        },
        "simulation_paper_oos": {
            "n_trades": count,
            "positions_ouvertes": count,
            "positions_fermees": count,
            "pnl_brut_realise_usd": 6.0,
            "fees_usd": 0.5,
            "spread_usd": 0.3,
            "slippage_usd": 0.1,
            "latency_usd": 0.1,
            "pnl_net_usd": 5.0,
            "roi_cumulatif_pct": 0.5,
            "drawdown_usd": 0.2,
            "winrate_pct": 66.7,
            "profit_factor": 2.0,
            "LIQUIDATABLE_NET": True,
            "trade_ids_count": count,
            "trade_ids_sha256": "a" * 64,
            "duplicate_events_rejected": 0,
            "trades": trades,
        },
    }


def _freeze(ts: int = 1_000) -> dict:
    return {
        "campaign_id": "freeze",
        "frozen_at_ms": ts,
        "selected_before_final_evaluation": True,
    }


def test_copy_forward_uses_only_trades_strictly_after_physical_freeze():
    campaign = build_strict_copy_campaign(
        _report(
            trades=[
                {"ts_ms": 999, "pnl_usd": 1.0},
                {"ts_ms": 1_000, "pnl_usd": 2.0},
                {"ts_ms": 1_001, "pnl_usd": 3.0},
            ]
        ),
        freeze=_freeze(),
        datasets={"files": []},
    )

    assert campaign["physical_forward_proof_complete"] is True
    assert campaign["oos"]["sample_count"] == 2
    assert campaign["oos"]["net_pnl_usd"] == 3.0
    assert campaign["forward"]["sample_count"] == 1
    assert campaign["forward"]["net_pnl_usd"] == 3.0
    assert campaign["forward"]["post_freeze"] is True
    assert campaign["forward"]["first_trade_ts_ms"] == 1_001


def test_copy_forward_fails_closed_when_materialised_trade_list_is_truncated():
    campaign = build_strict_copy_campaign(
        _report(
            trades=[{"ts_ms": 1_001 + index, "pnl_usd": 0.1} for index in range(50)],
            n_trades=51,
        ),
        freeze=_freeze(),
        datasets={"files": []},
    )

    assert campaign["physical_forward_proof_complete"] is False
    assert campaign["forward"] is None
    assert "FORWARD_POST_FREEZE_PROOF_MISSING" in campaign["objective_reasons"]


def test_copy_trade_exactly_on_freeze_boundary_never_counts_as_forward():
    campaign = build_strict_copy_campaign(
        _report(trades=[{"ts_ms": 1_000, "pnl_usd": 1.0}]),
        freeze=_freeze(),
        datasets={"files": []},
    )

    assert campaign["oos"]["sample_count"] == 1
    assert campaign["forward"]["sample_count"] == 0
    assert campaign["forward"]["post_freeze"] is False
