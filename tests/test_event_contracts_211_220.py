from hl_observer.copying.copy_vault_event_controls import (
    collateral_transfer_receipt,
    equity_position_version_receipt,
    fill_event_identity_receipt,
    historical_live_separation_receipt,
    invalid_api_response_receipt,
    position_delta_before_sizing_receipt,
    reconstruction_timestamps_receipt,
    simultaneous_timestamp_receipt,
    timezone_consistency_receipt,
    transactional_dedupe_receipt,
)


def test_lch211_fill_event_identity_is_stable() -> None:
    assert fill_event_identity_receipt([{"event_id": "e1", "component": "collector"}, {"event_id": "e1", "component": "ledger"}])["status"] == "PROVEN"
    assert fill_event_identity_receipt([{"event_id": "", "component": "collector"}])["status"] == "UNMEASURABLE"


def test_lch212_historical_and_live_lanes_are_separate() -> None:
    assert historical_live_separation_receipt([{"lane": "historical", "event_id": "h"}, {"lane": "live", "event_id": "l"}])["status"] == "PROVEN"


def test_lch213_simultaneous_timestamps_have_tie_breakers() -> None:
    assert simultaneous_timestamp_receipt([{"ts_ms": 1, "tie_breaker": 0}, {"ts_ms": 1, "tie_breaker": 1}])["status"] == "PROVEN"
    assert simultaneous_timestamp_receipt([{"ts_ms": 1, "tie_breaker": 0}, {"ts_ms": 1, "tie_breaker": 0}])["status"] == "REJECTED"


def test_lch214_equity_snapshot_has_position_version() -> None:
    state = {"snapshot_id": "s1", "position_version": "p1", "snapshot_position_version": "p1"}
    assert equity_position_version_receipt(state)["status"] == "PROVEN"
    state["snapshot_position_version"] = "p2"
    assert equity_position_version_receipt(state)["status"] == "UNMEASURABLE"


def test_lch215_collateral_transfer_reconciles() -> None:
    row = {"transfer_id": "t1", "amount_usd": 5, "before_usd": 100, "after_usd": 105}
    assert collateral_transfer_receipt([row])["status"] == "PROVEN"
    row["after_usd"] = 106
    assert collateral_transfer_receipt([row])["status"] == "REJECTED"


def test_lch216_position_delta_precedes_sizing() -> None:
    state = {"positions_reconciled": True, "sizing_allowed": True, "real_execution": False}
    assert position_delta_before_sizing_receipt(state)["status"] == "PROVEN"
    state["positions_reconciled"] = False
    assert position_delta_before_sizing_receipt(state)["status"] == "REJECTED"


def test_lch217_batch_and_powershell_are_utc() -> None:
    assert timezone_consistency_receipt([{"timezone": "UTC", "epoch_ms": 1}])["status"] == "PROVEN"
    assert timezone_consistency_receipt([{"timezone": "CET", "epoch_ms": 1}])["status"] == "REJECTED"


def test_lch218_dedupe_is_transactional() -> None:
    row = {"source_event_id": "e1", "transaction_id": "tx1", "committed": True}
    assert transactional_dedupe_receipt([row])["status"] == "PROVEN"
    row["committed"] = False
    assert transactional_dedupe_receipt([row])["status"] == "REJECTED"


def test_lch219_invalid_api_response_is_quarantined() -> None:
    state = {"request_id": "r1", "source": "api", "valid": False, "decision": "NO_TRADE", "quarantined": True}
    assert invalid_api_response_receipt(state)["status"] == "PROVEN"
    state["quarantined"] = False
    assert invalid_api_response_receipt(state)["status"] == "REJECTED"


def test_lch220_reconstruction_has_pre_post_timestamps() -> None:
    state = {"reconstruction_id": "r1", "before_ts_ms": 10, "after_ts_ms": 20}
    assert reconstruction_timestamps_receipt(state)["status"] == "PROVEN"
    state["after_ts_ms"] = 9
    assert reconstruction_timestamps_receipt(state)["status"] == "UNMEASURABLE"
