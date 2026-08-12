from __future__ import annotations

from pathlib import Path

from hl_observer.simulation.economic_campaigns import freeze_parameters
from hl_observer.simulation.lead_lag_campaign_adapter import (
    campaign_from_replay,
    signals_from_tape,
)
from hl_observer.strategies.lead_lag_paper import SignalLeadLag, rejouer_lead_lag


def _quote(ts_ns: int, mid: float):
    return (ts_ns, mid, mid - 0.01, mid + 0.01)


def test_signals_from_tape_expected_edge_uses_only_prior_shocks():
    ms = 1_000_000
    trades = [(0, 100.0, 1.0)]
    hl = [_quote(0, 100.0)]
    # Six separated Binance shocks. Each HL response occurs only AFTER its
    # shock. The first two signals therefore cannot have a historical estimate.
    for i in range(1, 7):
        t = i * 200 * ms
        trades.append((t, 100.0 + 0.2 * i, 1.0))
        entry_mid = 100.0 + 0.1 * i
        hl.append(_quote(t, entry_mid))
        hl.append(_quote(t + 100 * ms, entry_mid + 0.2))
    tape = {"BTC": {"HL": sorted(hl), "BIN": [], "TRADE": trades}}

    signals, meta = signals_from_tape(
        tape,
        shock_threshold_bps=8.0,
        horizon_ms=100,
        min_history=2,
    )

    assert len(signals) >= 4
    assert signals[0].edge_bps_prevu == 0.0
    assert signals[1].edge_bps_prevu == 0.0
    assert signals[2].edge_bps_prevu > 0.0
    assert meta["no_lookahead"] is True
    assert meta["signals_built"] == len(signals)


def _signals(n: int) -> list[SignalLeadLag]:
    return [
        SignalLeadLag(
            ts_ms=1_000 * i,
            coin="BTC" if i % 2 else "ETH",
            signe_leader=1,
            mid_entree=100.0,
            delta_mid_futur=0.5,
            edge_bps_prevu=60.0,
            liquidite=1.0,
            horizon_ms=1_000,
        )
        for i in range(n)
    ]


def test_campaign_adapter_can_reconcile_closed_is_oos_forward(tmp_path: Path):
    config = {
        "notional": 100.0,
        "fee_bps": 2.5,
        "demi_spread_bps": 2.5,
        "slippage_bps": 1.0,
        "min_fill_ratio": 0.5,
        "costs_measured": True,
        "equity": 1000.0,
    }
    replay = rejouer_lead_lag(_signals(30), config=config, min_episodes=5)
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    freeze = freeze_parameters(
        tmp_path,
        "lead_lag",
        {"fixed": True},
        datasets,
        campaign_id="lead-test",
        frozen_at_ms=1,
    )
    campaign = campaign_from_replay(
        {"signals": 30, "signals_meta": {"no_lookahead": True}, "replay": replay},
        freeze=freeze,
        datasets=datasets,
    )

    assert campaign["opened_positions"] == campaign["closed_positions"] > 0
    assert campaign["duplicate_trade_ids"] == 0
    assert campaign["liquidatable_net"] is True
    assert campaign["oos"]["net_pnl_usd"] > 0
    assert campaign["forward"]["net_pnl_usd"] > 0
    assert campaign["forward"]["post_freeze"] is True
    assert campaign["placebos"]["beaten"] is True
    assert campaign["net_pnl_usd"] >= 4.0
    assert campaign["objective_status"] == "ATTEINT"


def test_estimated_costs_never_become_liquidatable(tmp_path: Path):
    config = {
        "notional": 100.0,
        "fee_bps": 9.0,
        "demi_spread_bps": 4.0,
        "slippage_bps": 1.0,
        "costs_measured": False,
    }
    replay = rejouer_lead_lag(_signals(30), config=config, min_episodes=5)
    datasets = {"dataset_fingerprint": "d" * 64, "files": []}
    freeze = freeze_parameters(
        tmp_path,
        "lead_lag",
        {"fixed": True},
        datasets,
        campaign_id="lead-estimated",
        frozen_at_ms=1,
    )
    campaign = campaign_from_replay(
        {"signals": 30, "signals_meta": {}, "replay": replay},
        freeze=freeze,
        datasets=datasets,
    )
    assert campaign["liquidatable_net"] is False
    assert campaign["objective_status"] == "NON_ATTEINT"
    assert "NOT_LIQUIDATABLE_NET" in campaign["objective_reasons"]
