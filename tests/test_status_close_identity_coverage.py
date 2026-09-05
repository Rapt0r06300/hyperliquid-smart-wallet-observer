from __future__ import annotations

import hl_observer.ui.status_routes as status_routes


def test_closed_trade_identity_covers_instance_delta_and_source_paths() -> None:
    assert status_routes._closed_trade_identity({"paper_position_instance_id": "instance-1"}) == "instance-1"
    assert status_routes._closed_trade_identity({"delta_key": "d1", "paper_action_type": "REDUCE"}) == "delta:d1"
    assert status_routes._closed_trade_identity({"delta_key": "d2", "paper_action_type": "CLOSE"}) == "delta:d2"
    assert status_routes._closed_trade_identity({}) == ""
    assert (
        status_routes._closed_trade_identity(
            {"matched_position_key": "BTC|LONG", "source_delta_key": "source-7"}
        )
        == "BTC|LONG|src:source-7"
    )


def test_closed_trade_identity_fallback_is_stable_with_known_and_unknown_values() -> None:
    assert (
        status_routes._closed_trade_identity(
            {
                "matched_position_key": "ETH|SHORT",
                "entry_price": 2500.0,
                "size_closed": -0.4,
                "exit_method": "TAKE_PROFIT",
            }
        )
        == "ETH|SHORT|entry:2500|size:0.4|method:TAKE_PROFIT"
    )
    assert (
        status_routes._closed_trade_identity(
            {"matched_position_key": "SOL|LONG", "reason": "MANUAL_PAPER_CLOSE"}
        )
        == "SOL|LONG|entry:unknown_entry|size:unknown_size|method:MANUAL_PAPER_CLOSE"
    )


def test_status_paper_position_instance_id_prefers_source_then_open_time_then_fallback() -> None:
    assert (
        status_routes._status_paper_position_instance_id(
            position_key="BTC|LONG",
            position={"source_delta_key": "delta-1"},
            entry_price=100.0,
            size=-2.0,
        )
        == "BTC|LONG|src:delta-1"
    )
    assert (
        status_routes._status_paper_position_instance_id(
            position_key="BTC|LONG",
            position={"opened_at_ms": 12345},
            entry_price=100.0,
            size=-2.0,
        )
        == "BTC|LONG|opened:12345|entry:100|size:2"
    )
    assert (
        status_routes._status_paper_position_instance_id(
            position_key="BTC|LONG",
            position={},
            entry_price=100.0,
            size=-2.0,
        )
        == "BTC|LONG|entry:100|size:2"
    )


def test_status_full_close_already_exists_ignores_irrelevant_rows_and_matches_instance() -> None:
    ledger = [
        None,
        {"paper_action_type": "REDUCE", "matched_position_key": "BTC|LONG"},
        {"paper_action_type": "CLOSE", "matched_position_key": "ETH|LONG"},
        {
            "paper_action_type": "CLOSE",
            "matched_position_key": "BTC|LONG",
            "paper_position_instance_id": "instance-1",
        },
    ]

    assert status_routes._status_full_close_already_exists(
        ledger,
        matched_position_key="BTC|LONG",
        instance_id="instance-1",
        entry_price=100.0,
        size=2.0,
    ) is True


def test_status_full_close_already_exists_supports_legacy_fallback_and_false_case() -> None:
    legacy = [
        {
            "paper_action_type": "TAKE_PROFIT",
            "matched_position_key": "BTC|LONG",
            "entry_price": 100.0,
            "size_closed": 2.0,
        }
    ]
    assert status_routes._status_full_close_already_exists(
        legacy,
        matched_position_key="BTC|LONG",
        instance_id="new-instance",
        entry_price=100.0,
        size=-2.0,
    ) is True

    assert status_routes._status_full_close_already_exists(
        legacy,
        matched_position_key="BTC|LONG",
        instance_id="new-instance",
        entry_price=101.0,
        size=2.0,
    ) is False


def test_status_full_close_already_exists_uses_callsite_values_when_legacy_fields_are_missing() -> None:
    legacy = [
        {
            "paper_action_type": "STOP_LOSS",
            "matched_position_key": "BTC|LONG",
        }
    ]
    assert status_routes._status_full_close_already_exists(
        legacy,
        matched_position_key="BTC|LONG",
        instance_id="new-instance",
        entry_price=100.0,
        size=-2.0,
    ) is True
