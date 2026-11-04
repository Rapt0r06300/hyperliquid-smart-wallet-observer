from hl_observer.backtesting.copy_vault_replay_controls import (
    collect_analyze_phase_receipt,
    hotpath_replay_parity_receipt,
    oos_forward_separation_receipt,
    observed_source_manifest_receipt,
    paper_decision_engine_freeze_receipt,
    reconnect_receive_chrono_receipt,
    replay_merge_order_receipt,
    runtime_not_validated_dataset_receipt,
    sample_vs_real_capture_receipt,
    tape_contract_receipt,
)


def test_lch141_requires_safe_replay_tape_contract() -> None:
    row = {"tape_id": "t1", "required_for_replay": True, "manifest_hash": "a" * 64, "safe": True}
    assert tape_contract_receipt([row])["status"] == "PROVEN"
    row["safe"] = False
    assert tape_contract_receipt([row])["status"] == "REJECTED"


def test_lch142_requires_hotpath_replay_decision_parity() -> None:
    row = {"input_hash": "h1", "hotpath_decision": "NO_TRADE", "replay_decision": "NO_TRADE"}
    assert hotpath_replay_parity_receipt([row])["status"] == "PROVEN"
    row["replay_decision"] = "COPY_PAPER"
    assert hotpath_replay_parity_receipt([row])["status"] == "REJECTED"


def test_lch143_requires_monotonic_receive_time_and_native_identity() -> None:
    rows = [{"receive_ts_ms": 1, "native_event_id": "a"}, {"receive_ts_ms": 2, "native_event_id": "b"}]
    assert reconnect_receive_chrono_receipt(rows)["status"] == "PROVEN"
    rows[1]["receive_ts_ms"] = 0
    assert reconnect_receive_chrono_receipt(rows)["status"] == "UNMEASURABLE"


def test_lch144_rejects_sample_and_real_mix() -> None:
    assert sample_vs_real_capture_receipt([
        {"dataset_id": "d1", "capture_kind": "sample"},
        {"dataset_id": "d2", "capture_kind": "real", "provenance": "safe:1"},
    ])["status"] == "PROVEN"
    assert sample_vs_real_capture_receipt([
        {"dataset_id": "d1", "capture_kind": "sample"},
        {"dataset_id": "d1", "capture_kind": "real", "provenance": "safe:1"},
    ])["status"] == "REJECTED"


def test_lch145_publishes_observed_source_manifest() -> None:
    row = {"source": "l2", "manifest_hash": "a" * 64, "observed_at_ms": 10}
    assert observed_source_manifest_receipt([row])["status"] == "PROVEN"


def test_lch146_freezes_paper_decision_engine_identity() -> None:
    rows = [{"decision_id": "d1", "engine_version": "v1", "code_sha": "a" * 40}, {"decision_id": "d2", "engine_version": "v1", "code_sha": "a" * 40}]
    assert paper_decision_engine_freeze_receipt(rows)["status"] == "PROVEN"
    rows[1]["engine_version"] = "v2"
    assert paper_decision_engine_freeze_receipt(rows)["status"] == "UNMEASURABLE"


def test_lch147_runtime_directory_cannot_be_validated_dataset() -> None:
    assert runtime_not_validated_dataset_receipt({"runtime_directory": True, "dataset_validated": False})["status"] == "PROVEN"
    assert runtime_not_validated_dataset_receipt({"runtime_directory": True, "dataset_validated": True})["status"] == "REJECTED"


def test_lch148_blocks_analyze_during_collect() -> None:
    assert collect_analyze_phase_receipt({"phase": "COLLECT", "analyze_requested": False})["status"] == "PROVEN"
    assert collect_analyze_phase_receipt({"phase": "COLLECT", "analyze_requested": True})["status"] == "REJECTED"


def test_lch149_requires_deterministic_replay_merge_order() -> None:
    rows = [{"seed": 1, "merge_order": 0}, {"seed": 1, "merge_order": 1}]
    assert replay_merge_order_receipt(rows)["status"] == "PROVEN"
    rows[1]["merge_order"] = 0
    assert replay_merge_order_receipt(rows)["status"] == "REJECTED"


def test_lch150_separates_oos_and_forward_at_freeze() -> None:
    rows = [{"lane": "OOS", "ts_ms": 99}, {"lane": "FORWARD", "ts_ms": 100}]
    assert oos_forward_separation_receipt(rows, freeze_ts_ms=100)["status"] == "PROVEN"
    rows[0]["ts_ms"] = 100
    assert oos_forward_separation_receipt(rows, freeze_ts_ms=100)["status"] == "REJECTED"
