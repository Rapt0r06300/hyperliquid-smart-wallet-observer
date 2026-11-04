from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_book_loader import (
    future_book_access_receipt,
    load_observed_books,
)
from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_executable import (
    _observed_book_epoch_rejection,
    causal_book_receipt,
)
from hl_observer.backtesting.copy_vault_generalization import (
    derive_heldout_vault_generalization,
)
from hl_observer.collection.vault_fills_backfill import pagination_boundary_receipt
from hl_observer.copying.copy_vault_event_controls import equity_position_version_receipt


def _levels() -> tuple[list[list[float]], list[list[float]]]:
    return [[99.0, 10.0]], [[101.0, 10.0]]


def _historical_row() -> dict[str, object]:
    return {
        "collecte_ts": 1_700_000_000,
        "coin": "BTC",
        "hl_bid": 99.0,
        "hl_ask": 101.0,
        "taille_min_usd": 1_000.0,
    }


def _metaorder_event(*, event_id: str, source: str, ts_ms: int = 1_000) -> dict[str, object]:
    return {
        "event_id": event_id,
        "source": source,
        "vault": "0xvault",
        "coin": "BTC",
        "ts_ms": ts_ms,
        "direction": 1,
        "dir": "Open Long",
        "action": "OPEN",
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }


def test_pnl031_reconnection_changes_epoch_and_is_rejected() -> None:
    first = {"connection_id": "ws-a", "l2_gap_epoch": 7}
    second = {"connection_id": "ws-a", "l2_gap_epoch": 8}
    third = {"connection_id": "ws-a", "l2_gap_epoch": 8}

    assert _observed_book_epoch_rejection((first, second, third), require_proven_identity=True) == "L2_GAP_EPOCH_CROSSED"
    assert _observed_book_epoch_rejection((second, third), require_proven_identity=True) is None


def test_pnl032_rest_and_ws_same_native_trade_are_deduplicated() -> None:
    events, audit = cluster_metaorders([
        _metaorder_event(event_id="native-1", source="REST_BACKFILL"),
        _metaorder_event(event_id="native-1", source="LIVE_WS"),
    ])

    assert len(events) == 1
    assert audit["duplicate_events_rejected"] == 1
    assert events[0]["member_event_ids"] == ["native-1"]


def test_pnl033_thousand_same_millisecond_fills_preserve_native_identity() -> None:
    page = [{"ts_ms": 1_000, "tid": index, "coin": "BTC"} for index in range(1_001)]
    receipt = pagination_boundary_receipt([page[:500], page[500:], [page[-1]]])

    assert receipt["status"] == "PROVEN"
    assert receipt["input_count"] == 1_002
    assert receipt["retained_count"] == 1_001
    assert receipt["removed_duplicates"] == 1


def test_pnl034_two_books_available_at_exact_cutoff_are_admitted() -> None:
    bids, asks = _levels()
    first = {
        "ts_ms": 2_000, "bid": 99.0, "ask": 101.0,
        "bids5": bids, "asks5": asks,
    }
    second = {
        "ts_ms": 2_000, "bid": 98.0, "ask": 102.0,
        "bids5": [[98.0, 10.0]], "asks5": [[102.0, 10.0]],
    }

    assert future_book_access_receipt(first, as_of_ms=2_000)["verdict"] == "PROVEN"
    assert future_book_access_receipt(second, as_of_ms=2_000)["verdict"] == "PROVEN"


def test_pnl035_stress_gap_is_explicit_and_not_hidden(tmp_path: Path) -> None:
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "carnet_venues.jsonl").write_text(
        json.dumps(_historical_row()) + "\n", encoding="utf-8"
    )
    (data_dir / "copy_vault_checkpoint_tail_state.json").write_text(
        json.dumps({
            "counters": {
                "input_rotations": 2,
                "checkpoints_expired": 0,
                "pending_overflow_rejected": 0,
            }
        }),
        encoding="utf-8",
    )

    _, audit = load_observed_books(tmp_path, coins=["BTC"])

    assert audit["clean_epoch_receipt"]["collector_gap_count"] == 2
    assert audit["clean_epoch_receipt"]["receipt_valid"] is False
    assert audit["replay_grade_status"] == "UNMEASURABLE"


def test_pnl036_safe_file_without_provenance_is_not_replay_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "carnet_venues.jsonl").write_text(
        json.dumps(_historical_row()) + "\n", encoding="utf-8"
    )

    _, audit = load_observed_books(tmp_path, coins=["BTC"])

    assert audit["source_evidence_rows"] == {"unavailable": 1}
    assert audit["replay_grade_status"] == "UNMEASURABLE"
    assert "SAFE_MANIFEST_L2_EVIDENCE_INCOMPLETE" in audit["replay_grade_blockers"]


def test_pnl037_position_snapshot_must_match_exact_version() -> None:
    state = {
        "snapshot_id": "snap-1",
        "position_version": "wallet-1:position-7",
        "snapshot_position_version": "wallet-1:position-7",
    }
    assert equity_position_version_receipt(state)["status"] == "PROVEN"
    state["snapshot_position_version"] = "wallet-1:position-8"
    assert equity_position_version_receipt(state)["status"] == "UNMEASURABLE"


def test_pnl038_side_and_direction_contradiction_is_quarantined() -> None:
    from hl_observer.collection.vault_fills_backfill import parser_fills_with_audit

    fills, audit = parser_fills_with_audit([
        {
            "time": 1_000,
            "coin": "BTC",
            "px": "100",
            "sz": "1",
            "side": "B",
            "dir": "Close Long",
            "startPosition": "1",
            "tid": 1,
        }
    ], vault="0xvault")

    assert fills == []
    assert audit["rejected_by_reason"] == {"FILL_SIDE_DIR_CONTRADICTION": 1}


def test_pnl039_quote_after_gap_is_not_causal() -> None:
    before_gap = causal_book_receipt(
        book_ts_ms=1_200,
        visible_ts_ms=1_250,
        decision_ts_ms=1_300,
        source_reception_ts_ms=1_250,
    )
    after_gap = causal_book_receipt(
        book_ts_ms=1_400,
        visible_ts_ms=1_450,
        decision_ts_ms=1_300,
        source_reception_ts_ms=1_450,
    )

    assert before_gap["status"] == "PROVEN"
    assert after_gap["status"] == "REJECTED"
    assert after_gap["reason"] == "BOOK_NOT_CAUSAL"


def test_pnl040_heldout_leaderboard_excludes_vault_seen_before_oos() -> None:
    def trade(vault: str, ts_ms: int, suffix: str, net: float) -> dict[str, object]:
        return {
            "vault": vault,
            "signal_ts_ms": ts_ms,
            "net_pnl_usd": net,
            "notional_usd": 100.0,
            "trade_id": suffix * 64,
            "liquidatable_net": True,
            "coin": "BTC",
            "direction": 1,
        }

    proof = derive_heldout_vault_generalization([
        trade("seen-before", 100, "a", 1.0),
        trade("seen-before", 300, "b", 10.0),
        trade("new-at-oos", 300, "c", 2.0),
    ], oos_start_ms=200)

    assert proof is not None
    assert proof["vaults_held_out"] == ["new-at-oos"]
    assert proof["sample_count"] == 1
    assert proof["net_pnl_usd"] == 2.0

