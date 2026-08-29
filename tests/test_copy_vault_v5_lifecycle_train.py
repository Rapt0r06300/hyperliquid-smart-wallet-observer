from __future__ import annotations

from hl_observer.backtesting.copy_vault_executable import cluster_metaorders
from hl_observer.backtesting.copy_vault_v5_lifecycle_train import (
    EXIT_POLICY,
    explore_copy_vault_v5_train,
    index_causal_leader_exits,
    replay_lifecycle_train,
)


def _live_fill(event_id: str, ts_ms: int, *, action: str) -> dict:
    return {
        "event_id": event_id,
        "ts_ms": ts_ms,
        "observed_at_ms": ts_ms + 25,
        "coin": "BTC",
        "direction": 1,
        "action": action,
        "dir": "Open Long",
        "vault": "0xA",
        "taille_usd": 10_000.0,
        "source": "LIVE_WS",
        "is_snapshot": False,
    }


def _book(ts_ms: int, bid: float, ask: float, line: int) -> dict:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "capacity_usd": 10_000.0,
        "source_line": line,
        "causal_observation": True,
    }


def _leader_exit(observed_at_ms: int, *, causal: bool = True) -> dict:
    return {
        "event_id": "leader-reduce",
        "fill_id": "fill-reduce",
        "ts_ms": observed_at_ms - 25,
        "observed_at_ms": observed_at_ms,
        "coin": "BTC",
        "direction": 1,
        "action": "REDUCE",
        "vault": "0xA",
        "source": "LIVE_WS",
        "is_snapshot": not causal,
    }


def _metaorders() -> tuple[list[dict], int]:
    entries = [
        _live_fill("first", 1_000, action="OPEN"),
        _live_fill("second", 2_000, action="ADD"),
    ]
    rows, _ = cluster_metaorders(entries)
    return rows, 2_025


def test_replay_sort_au_premier_reduce_causal_avant_le_time_stop() -> None:
    metaorders, signal_ms = _metaorders()
    entry_ms = signal_ms + 60_000
    reduce_ms = entry_ms + 60_000
    books = {
        "BTC": [
            _book(signal_ms, 99.0, 101.0, 1),
            _book(entry_ms, 100.0, 102.0, 2),
            _book(reduce_ms, 109.0, 111.0, 3),
            _book(entry_ms + 300_000, 97.0, 99.0, 4),
        ]
    }

    trades, audit = replay_lifecycle_train(
        metaorders,
        books,
        [_leader_exit(reduce_ms)],
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=1_000,
        train_end_ms=10_000,
    )
    placebo, _ = replay_lifecycle_train(
        metaorders,
        books,
        [_leader_exit(reduce_ms)],
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=1_000,
        train_end_ms=10_000,
        direction_multiplier=-1,
    )

    assert audit["leader_exits"]["causal_exit_events"] == 1
    assert len(trades) == len(placebo) == 1
    assert trades[0]["exit_trigger"] == "LEADER_REDUCE_OR_CLOSE"
    assert trades[0]["leader_exit_action"] == "REDUCE"
    assert trades[0]["leader_exit_event_id"] == "leader-reduce"
    assert trades[0]["exit_ts_ms"] == reduce_ms
    assert trades[0]["exit_policy"] == EXIT_POLICY
    assert trades[0]["net_pnl_usd"] > 0 > placebo[0]["net_pnl_usd"]
    assert trades[0]["liquidatable_net"] is True
    assert trades[0]["paper_read_only"] is True
    assert trades[0]["real_execution"] is False


def test_replay_ignore_une_sortie_non_causale_et_utilise_le_time_stop() -> None:
    metaorders, signal_ms = _metaorders()
    entry_ms = signal_ms + 60_000
    time_stop_ms = entry_ms + 300_000
    books = {
        "BTC": [
            _book(signal_ms, 99.0, 101.0, 1),
            _book(entry_ms, 100.0, 102.0, 2),
            _book(time_stop_ms, 103.0, 105.0, 3),
        ]
    }

    trades, audit = replay_lifecycle_train(
        metaorders,
        books,
        [_leader_exit(entry_ms + 10_000, causal=False)],
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=1_000,
        train_end_ms=10_000,
    )

    assert audit["leader_exits"]["causal_exit_events"] == 0
    assert len(trades) == 1
    assert trades[0]["exit_trigger"] == "TIME_STOP"
    assert trades[0]["leader_exit_event_id"] is None
    assert trades[0]["exit_ts_ms"] == time_stop_ms


def test_index_refuse_un_close_sans_horloge_locale_monotone() -> None:
    bad = _leader_exit(20_000)
    bad["observed_at_ms"] = bad["ts_ms"] - 1

    indexed, audit = index_causal_leader_exits([bad])

    assert indexed == {}
    assert audit["causal_exit_events"] == 0
    assert audit["noncausal_or_nonexit_events_rejected"] == 1


def test_replay_refuse_des_bornes_train_absentes() -> None:
    metaorders, _ = _metaorders()

    trades, audit = replay_lifecycle_train(
        metaorders,
        {},
        [],
        required_observed_fills=2,
        horizon_ms=300_000,
        train_start_ms=None,
        train_end_ms=None,
    )

    assert trades == []
    assert audit["replay"]["INVALID_OR_MISSING_TRAIN_BOUNDS"] == 1


def test_exploration_reste_train_only_et_fail_closed_sans_donnees() -> None:
    result = explore_copy_vault_v5_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["trial_count"] == 16
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
