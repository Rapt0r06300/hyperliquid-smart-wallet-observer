from __future__ import annotations

from hl_observer.backtesting.copy_vault_v7_exit_flow_train import (
    cluster_causal_exit_flow,
    explore_copy_vault_v7_exit_flow_train,
    replay_exit_flow_train,
)


def _exit(
    event_id: str,
    ts_ms: int,
    *,
    direction: int = 1,
    snapshot: bool = False,
    coin: str = "BTC",
    vault: str = "0xA",
) -> dict:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "observed_at_ms": ts_ms + 25,
        "coin": coin,
        "direction": direction,
        "action": "REDUCE",
        "vault": vault,
        "source": "LIVE_WS",
        "is_snapshot": snapshot,
    }


def _book(ts_ms: int, bid: float, ask: float, line: int) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "bids5": [[bid, 100.0]],
        "asks5": [[ask, 100.0]],
        "capacity_usd": 10_000.0,
        "source_line": line,
        "causal_observation": True,
    }


def test_cluster_exit_flow_collapses_slices_and_follows_order_side() -> None:
    signals, audit = cluster_causal_exit_flow(
        [_exit("a", 1_000), _exit("b", 3_000), _exit("c", 10_000)]
    )

    assert len(signals) == 2
    assert signals[0]["direction"] == -1
    assert signals[0]["leader_position_direction"] == 1
    assert signals[0]["member_event_ids"] == ["a", "b"]
    assert audit["causal_exit_events"] == 3
    assert audit["exit_flow_signals"] == 2


def test_cluster_exit_flow_collapses_per_key_across_interleaved_flow() -> None:
    signals, audit = cluster_causal_exit_flow(
        [
            _exit("a", 1_000),
            _exit("other", 2_000, coin="ETH", vault="0xB"),
            _exit("b", 3_000),
        ]
    )

    btc = next(signal for signal in signals if signal["coin"] == "BTC")
    assert btc["member_event_ids"] == ["a", "b"]
    assert audit["exit_flow_signals"] == 2
    assert audit["collapsed_slices"] == 1


def test_cluster_exit_flow_rejects_snapshot_rows() -> None:
    signals, audit = cluster_causal_exit_flow([_exit("a", 1_000, snapshot=True)])

    assert signals == []
    assert audit["noncausal_or_nonexit_events_rejected"] == 1


def test_replay_long_reduction_opens_short_after_causal_delay() -> None:
    signal = _exit("a", 1_000)["observed_at_ms"]
    books = {
        "BTC": [
            _book(signal, 100.0, 100.1, 1),
            _book(signal + 250, 99.9, 100.0, 2),
            _book(signal + 30_250, 98.0, 98.1, 3),
        ]
    }

    trades, audit = replay_exit_flow_train(
        [_exit("a", 1_000)],
        books,
        copy_delay_ms=250,
        horizon_ms=30_000,
        train_start_ms=0,
        train_end_ms=10_000,
    )

    assert len(trades) == 1
    assert trades[0]["direction"] == -1
    assert trades[0]["net_pnl_usd"] > 0
    assert trades[0]["liquidatable_net"] is True
    assert audit["replay"]["completed_positions"] == 1


def test_v7_empty_input_is_train_only_and_accounts_all_trials() -> None:
    result = explore_copy_vault_v7_exit_flow_train([], {})

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["new_trial_count"] == 8
    assert result["fixed_grid"]["bonferroni_trial_count"] == 84
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
