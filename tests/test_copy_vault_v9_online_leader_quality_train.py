from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_v9_online_leader_quality_train import (
    apply_causal_online_leader_quality,
    explore_copy_vault_v9_online_leader_quality_train,
)


def _trade(
    identity: str,
    *,
    vault: str,
    entry_ms: int,
    exit_ms: int,
    net: float,
) -> dict:
    return {
        "trade_id": identity,
        "metaorder_id": identity,
        "vault": vault,
        "coin": "BTC",
        "entry_ts_ms": entry_ms,
        "exit_ts_ms": exit_ms,
        "net_pnl_usd": net,
    }


def test_online_quality_uses_only_same_vault_outcomes_closed_before_entry() -> None:
    shadow = [
        _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0),
        _trade("candidate-1", vault="A", entry_ms=30, exit_ms=40, net=-10.0),
        _trade("candidate-2", vault="A", entry_ms=35, exit_ms=45, net=-10.0),
        _trade("candidate-3", vault="A", entry_ms=50, exit_ms=60, net=100.0),
        _trade("other-vault", vault="B", entry_ms=1, exit_ms=2, net=1_000.0),
    ]
    candidates = shadow[1:4]

    selected, audit = apply_causal_online_leader_quality(
        candidates,
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )

    assert [row["trade_id"] for row in selected] == ["candidate-1", "candidate-2"]
    assert [row["leader_quality_prior_count"] for row in selected] == [1, 1]
    assert audit["NON_POSITIVE_PRIOR_MEAN_REJECTED"] == 1


def test_online_quality_emits_per_signal_retained_demoted_and_rejected_trace() -> None:
    shadow = [
        _trade("positive-history", vault="A", entry_ms=10, exit_ms=20, net=2.0),
        _trade("negative-history", vault="B", entry_ms=10, exit_ms=20, net=-2.0),
        _trade("retain-me", vault="A", entry_ms=30, exit_ms=40, net=-10.0),
        _trade("demote-me", vault="B", entry_ms=30, exit_ms=40, net=10.0),
        _trade("reject-me", vault="C", entry_ms=30, exit_ms=40, net=10.0),
    ]

    _, audit = apply_causal_online_leader_quality(
        shadow[2:],
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )

    decisions = {row["candidate_trade_id"]: row for row in audit["leader_decisions"]}
    assert decisions["retain-me"]["outcome"] == "RETAINED"
    assert decisions["demote-me"]["outcome"] == "DEMOTED"
    assert decisions["reject-me"]["outcome"] == "REJECTED"
    assert decisions["retain-me"]["as_of_ms"] == 30
    assert decisions["retain-me"]["prior_trade_ids"] == ["positive-history"]
    assert decisions["retain-me"]["prior_latest_exit_ts_ms"] == 20
    assert decisions["retain-me"]["decision_scope"] == "CANDIDATE_SIGNAL_AT_ENTRY"


def test_online_quality_invalid_candidate_timestamp_is_audited_not_raised() -> None:
    malformed = _trade("bad-time", vault="A", entry_ms=30, exit_ms=40, net=1.0)
    malformed["entry_ts_ms"] = "not-a-timestamp"
    valid = _trade("valid", vault="A", entry_ms=30, exit_ms=40, net=1.0)
    shadow = [_trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0)]

    selected, audit = apply_causal_online_leader_quality(
        [malformed, valid],
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )

    assert [row["trade_id"] for row in selected] == ["valid"]
    assert audit["INVALID_CANDIDATE_REJECTED"] == 1
    invalid = next(row for row in audit["leader_decisions"] if row["candidate_trade_id"] == "bad-time")
    assert invalid["outcome"] == "REJECTED"
    assert invalid["reason"] == "INVALID_CANDIDATE_TIMESTAMP"


def test_online_quality_trace_binds_only_complete_causal_safe_prior_lineage() -> None:
    def ref(dataset: str, digest: str, ts: int, event: str) -> dict:
        return {
            "dataset_id": dataset,
            "shard_sha256": digest * 64,
            "source_catalog_sha256": "c" * 64,
            "quality": "SAFE",
            "manifest_verified": True,
            "replay_compatible": True,
            "event_id": event,
            "event_ts_ms": ts,
            "exchange_ts_ms": ts,
            "received_at_ms": ts + 1,
        }

    history = _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0)
    history.update(
        {
            "leader_fill_evidence_status": "SAFE_CAUSAL_COMPLETE",
            "leader_fill_evidence_refs": [ref("fill-dataset", "a", 11, "fill-1")],
            "execution_book_safe_evidence_complete": True,
            "execution_book_evidence_refs": [
                {**ref("book-dataset", "b", timestamp, f"book-{index}"), "role": role}
                for index, (timestamp, role) in enumerate(
                    ((12, "REFERENCE"), (15, "ENTRY"), (19, "EXIT"))
                )
            ],
        }
    )
    candidate = _trade("candidate", vault="A", entry_ms=30, exit_ms=40, net=-1.0)

    _, audit = apply_causal_online_leader_quality(
        [candidate],
        [history],
        minimum_prior_closed=1,
        history_window=4,
    )

    decision = audit["leader_decisions"][0]
    assert decision["evidence_status"] == "SAFE_CAUSAL_COMPLETE"
    assert len(decision["evidence_refs"]) == 4
    assert {row["source_family"] for row in decision["evidence_refs"]} == {
        "copy_vault_fills",
        "copy_vault_l2",
    }
    assert all(row["received_at_ms"] <= 20 for row in decision["evidence_refs"])


def test_online_quality_trace_marks_duplicate_source_reference_incomplete() -> None:
    fill = {
        "dataset_id": "fill-dataset",
        "shard_sha256": "a" * 64,
        "source_catalog_sha256": "c" * 64,
        "quality": "SAFE",
        "manifest_verified": True,
        "replay_compatible": True,
        "event_id": "fill-1",
        "event_ts_ms": 11,
        "received_at_ms": 12,
    }
    books = [
        {
            "dataset_id": "book-dataset",
            "shard_sha256": "b" * 64,
            "source_catalog_sha256": "c" * 64,
            "quality": "SAFE",
            "manifest_verified": True,
            "replay_compatible": True,
            "role": role,
            "exchange_ts_ms": timestamp,
            "received_at_ms": timestamp + 1,
        }
        for role, timestamp in (("REFERENCE", 13), ("ENTRY", 15), ("EXIT", 18))
    ]
    history = _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0)
    history.update(
        {
            "leader_fill_evidence_status": "SAFE_CAUSAL_COMPLETE",
            "leader_fill_evidence_refs": [fill, fill],
            "execution_book_safe_evidence_complete": True,
            "execution_book_evidence_refs": books,
        }
    )
    candidate = _trade("candidate", vault="A", entry_ms=30, exit_ms=40, net=1.0)

    _, audit = apply_causal_online_leader_quality(
        [candidate], [history], minimum_prior_closed=1, history_window=4
    )

    assert audit["leader_decisions"][0]["evidence_status"] == "INCOMPLETE_OR_UNVERIFIED"


def test_online_quality_selection_is_invariant_to_current_and_future_outcomes() -> None:
    shadow = [
        _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0),
        _trade("candidate", vault="A", entry_ms=30, exit_ms=40, net=-10.0),
        _trade("future", vault="A", entry_ms=35, exit_ms=45, net=-10.0),
    ]
    candidates = shadow[1:]
    first, _ = apply_causal_online_leader_quality(
        candidates,
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )
    changed = deepcopy(shadow)
    changed[1]["net_pnl_usd"] = 10_000.0
    changed[2]["net_pnl_usd"] = 10_000.0
    second, _ = apply_causal_online_leader_quality(
        changed[1:],
        changed,
        minimum_prior_closed=1,
        history_window=4,
    )

    assert [row["trade_id"] for row in first] == [row["trade_id"] for row in second]


def test_v9_empty_input_remains_train_only_and_counts_eight_trials() -> None:
    result = explore_copy_vault_v9_online_leader_quality_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["selection_eligible"] is False
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["new_trial_count"] == 8
    assert result["fixed_grid"]["bonferroni_trial_count"] == 112
    trace = result["leader_decision_traces"]
    assert trace["scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert trace["decision_scope"] == "V9_ONLINE_LEADER_QUALITY_AFTER_ENTRY_EFFICIENCY"
    assert trace["durability"] == "CAMPAIGN_RESULT_ONLY_NOT_APPEND_ONLY_REVIEW_LEDGER"
    assert len(trace["traces"]) == 4
    assert all(row["candidate_decision_count"] == 0 for row in trace["traces"])
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
