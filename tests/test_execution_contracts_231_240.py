from hl_observer.ops.copy_vault_execution_controls import (
    catastrophe_stop_gap_receipt,
    client_network_no_order_receipt,
    funding_on_hold_exposure_receipt,
    leader_takeover_vs_stop_receipt,
    maker_style_launcher_receipt,
    nonzero_placement_latency_receipt,
    partial_fill_then_close_receipt,
    position_inversion_two_trades_receipt,
    positive_liquidity_requires_book_receipt,
    symbol_min_size_rounding_receipt,
)


def test_lch231_maker_launcher_is_simulated() -> None:
    row = {"execution_style": "maker", "simulated": True, "execution_attempted": False, "scope": "copy-vault"}
    assert maker_style_launcher_receipt([row])["status"] == "PROVEN"
    row["execution_attempted"] = True
    assert maker_style_launcher_receipt([row])["status"] == "REJECTED"


def test_lch232_requires_nonzero_placement_latency() -> None:
    assert nonzero_placement_latency_receipt([{"request_id": "r1", "sent_ts_ms": 10, "ack_ts_ms": 11}])["status"] == "PROVEN"
    assert nonzero_placement_latency_receipt([{"request_id": "r1", "sent_ts_ms": 10, "ack_ts_ms": 10}])["status"] == "UNMEASURABLE"


def test_lch233_positive_liquidity_requires_book() -> None:
    assert positive_liquidity_requires_book_receipt([{"liquidity_usd": 2, "book_present": True}])["status"] == "PROVEN"
    assert positive_liquidity_requires_book_receipt([{"liquidity_usd": 2, "book_present": False}])["status"] == "REJECTED"


def test_lch234_requires_partial_then_close() -> None:
    events = [
        {"event_type": "PARTIAL_FILL", "order_id": "o1", "filled_qty": 3, "ts_ms": 10},
        {"event_type": "CLOSE", "order_id": "o1", "closed_qty": 3, "ts_ms": 20},
    ]
    assert partial_fill_then_close_receipt(events)["status"] == "PROVEN"
    assert partial_fill_then_close_receipt(list(reversed(events)))["status"] == "REJECTED"


def test_lch235_gap_stop_is_fail_closed() -> None:
    row = {"gap_detected": True, "stop_decision": "VETO_NO_EXECUTION", "executed": False}
    assert catastrophe_stop_gap_receipt([row])["status"] == "PROVEN"
    row["executed"] = True
    assert catastrophe_stop_gap_receipt([row])["status"] == "REJECTED"


def test_lch236_symbol_rounding_respects_minimum_and_step() -> None:
    row = {"symbol": "BTC", "requested_qty": "0.123", "min_qty": "0.01", "step_qty": "0.01", "rounded_qty": "0.12"}
    assert symbol_min_size_rounding_receipt([row])["status"] == "PROVEN"
    row["rounded_qty"] = "0.123"
    assert symbol_min_size_rounding_receipt([row])["status"] == "REJECTED"


def test_lch237_funding_uses_held_exposure() -> None:
    row = {"position_open": True, "exposure_usd": 1000, "funding_bps_8h": 8, "hold_hours": 8, "funding_usd": 0.8}
    assert funding_on_hold_exposure_receipt([row])["status"] == "PROVEN"
    row["funding_usd"] = 0
    assert funding_on_hold_exposure_receipt([row])["status"] == "REJECTED"


def test_lch238_stop_overrides_leader_takeover() -> None:
    events = [
        {"source": "STOP", "ts_ms": 10, "decision": "VETO_NO_EXECUTION"},
        {"source": "LEADER_TAKEOVER", "ts_ms": 11, "executed": False},
    ]
    assert leader_takeover_vs_stop_receipt(events)["status"] == "PROVEN"
    events[1]["executed"] = True
    assert leader_takeover_vs_stop_receipt(events)["status"] == "REJECTED"


def test_lch239_inversion_is_close_then_open() -> None:
    events = [
        {"trade_type": "CLOSE", "symbol": "BTC", "qty": 1, "ts_ms": 10},
        {"trade_type": "OPEN", "symbol": "BTC", "qty": 1, "ts_ms": 11},
    ]
    assert position_inversion_two_trades_receipt(events)["status"] == "PROVEN"
    assert position_inversion_two_trades_receipt(list(reversed(events)))["status"] == "REJECTED"


def test_lch240_client_network_has_no_order_path() -> None:
    row = {"endpoint": "/info", "read_only": True, "signed": False, "real_execution": False, "network_action": "GET"}
    assert client_network_no_order_receipt([row])["status"] == "PROVEN"
    row["endpoint"] = "/order"
    assert client_network_no_order_receipt([row])["status"] == "REJECTED"
