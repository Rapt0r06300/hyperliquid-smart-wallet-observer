"""Fixes for the money-losing run (2026-06-25): AI sample ingestion now survives a
mid-write snapshot (was ingesting 0), and the catastrophe stop caps losers while letting
winners run. Pure / paper-only."""

from __future__ import annotations

import json

from hl_observer.ml.ledger_extract import _salvage_events, _read_snapshot_events, rows_outcomes_from_events
from hl_observer.ml.train_cli import run as train_cli_run
from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp, STOP_LOSS, HOLD
from hl_observer.simulation.adaptive_paper_sizing import adaptive_paper_margin, realized_exit_pnls


def test_ai_ingest_salvages_truncated_snapshot(tmp_path):
    # a snapshot with a complete OPEN + CLOSE pair, then truncated mid-write (no closing braces)
    good = (
        '{"bot_simulation": {"ledger_events": [\n'
        '{"bot_replay_action":"PAPER_ENTRY_REPLAYED","matched_position_key":"w|ETH|LONG",'
        '"observed_at_ms":1000,"edge_remaining_bps":20,"signal_age_ms":2000,"consensus_wallets":2,'
        '"liquidity_score":0.6,"leader_score":70,"adverse_price_move_bps":0,"price_deviation_bps":1},\n'
        '{"bot_replay_action":"PAPER_CLOSE_REPLAYED","matched_position_key":"w|ETH|LONG",'
        '"observed_at_ms":5000,"estimated_net_pnl_usdc":4.2},\n'
        '{"bot_replay_action":"PAPER_ENTRY_REPLAYED","matched_position_key":"w|BTC|SHO'  # truncated!
    )
    p = tmp_path / "snap.json"
    p.write_text(good, encoding="utf-8")
    evs = _read_snapshot_events(str(p))
    assert len(evs) >= 2                       # salvaged the 2 complete events despite truncation
    rows, outs = rows_outcomes_from_events(evs)
    assert len(rows) == 1                       # one OPEN<->CLOSE pair recovered
    assert outs[0].realized_net_pnl_usdc == 4.2


def test_catastrophe_stop_caps_losers_lets_winners_run():
    cfg = SLTPConfig(stop_loss_bps=150.0, take_profit_bps=99999.0, trailing_stop_bps=None)
    # loser: LONG, price -1.6% -> below -150bps -> STOP_LOSS (capped)
    loser = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=98.4, config=cfg)
    assert loser.exit and loser.reason == STOP_LOSS
    # small adverse move -1.0% -> still HOLD (not a catastrophe)
    small = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=99.0, config=cfg)
    assert small.hold
    # winner: LONG +5% -> NOT closed by our exit (TP off, no trail) -> lets it run
    winner = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=105.0, config=cfg)
    assert winner.hold and winner.reason == HOLD
    # SHORT loser: price +1.6% -> -160bps signed -> STOP_LOSS
    short_loser = evaluate_sl_tp(side="SHORT", entry_price=100.0, current_price=101.6, config=cfg)
    assert short_loser.exit and short_loser.reason == STOP_LOSS


def test_ai_training_context_all_uses_existing_replay_samples(tmp_path):
    samples = tmp_path / "training_samples.jsonl"
    for idx, pnl in enumerate([1.2, -0.7, 0.9, -0.4]):
        with samples.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "decision_id": f"k{idx}",
                "ts_ms": 1000 + idx,
                "close_ts_ms": 2000 + idx,
                "context": "REPLAY",
                "features": {
                    "net_edge_bps": 10 + idx,
                    "signal_age_ms": 1000,
                    "consensus_wallets": 2 + idx,
                    "liquidity_score": 1.0,
                },
                "net_pnl_usdc": pnl,
            }, sort_keys=True) + "\n")

    live_only = train_cli_run(samples=str(samples), out=None, context="LIVE", min_samples=2)
    assert live_only["n"] == 0
    all_context = train_cli_run(samples=str(samples), out=None, context="ALL", min_samples=2)
    assert all_context["context_effective"] == "ALL"
    assert all_context["n"] == 4
    assert all_context["n_win"] == 2
    assert all_context["n_loss"] == 2


def test_adaptive_paper_sizing_reduces_after_loss_streak():
    recent_events = [
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "estimated_net_pnl_usdc": -0.8,
        },
        {
            "status": "LOCAL_REPLAY",
            "bot_replay_action": "PAPER_CONSENSUS_CLOSE_REPLAYED",
            "estimated_net_pnl_usdc": -0.6,
        },
    ]

    pnls = realized_exit_pnls(recent_events)
    assert pnls == [-0.8, -0.6]

    sizing = adaptive_paper_margin(
        requested_margin_usdt=50.0,
        equity_usdt=998.6,
        recent_events=recent_events,
        edge_remaining_bps=60.0,
        liquidity_score=1.0,
        consensus_wallets=4,
        min_margin_usdt=5.0,
        max_margin_usdt=50.0,
    )

    assert sizing.enabled
    assert sizing.consecutive_losses == 2
    assert sizing.final_margin_usdt < 50.0
    assert sizing.reason == "LOSS_STREAK_SIZE_REDUCED"
