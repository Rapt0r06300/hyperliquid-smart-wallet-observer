from __future__ import annotations

import json

import pytest

import hl_observer.ops.pnl_improvement_lab as lab


def test_scalar_and_row_extractors_cover_invalid_and_aliases() -> None:
    assert lab._to_float("1.5") == 1.5
    assert lab._to_float("nan") is None
    assert lab._to_int("2") == 2
    assert lab._to_int("bad") is None
    assert lab._event_timestamp_ms({}) == 0
    assert lab._event_timestamp_ms({"observed_at_ms": "12"}) == 12

    assert lab._wallet_count({"consensus_wallets": -2}) == 0
    assert lab._wallet_count({"wallet_count": 3}) == 3
    assert lab._wallet_count({"wallet_address": " A, b, a "}) == 2
    assert lab._wallet_count({}) is None

    row = {"a": None, "b": "2.5", "c": "3"}
    assert lab._first_float(row, "a", "b") == 2.5
    assert lab._first_int(row, "a", "c") == 3
    assert lab._first_float_across(({"x": None}, ("x",)), ({"y": "4.5"}, ("y",))) == 4.5


def test_position_event_identity_strategy_and_accounting_schema() -> None:
    assert lab._position_instance_id({}) == ""
    assert lab._position_instance_id({"position_instance_id": " p1 "}) == "p1"

    identity = lab._event_identity(
        {"event_type": "OPEN", "timestamp_ms": 10, "coin": "BTC", "estimated_net_pnl_usdc": 1},
        7,
    )
    assert identity.startswith("OPEN|7|10|BTC|1")
    explicit = lab._event_identity(
        {"paper_action_type": "CLOSE", "dedupe_identity": "d1", "timestamp_ms": 20},
        8,
    )
    assert "CLOSE|d1|20" in explicit

    assert lab._strategy_name({"strategy_mode": "funding carry"}) == "FUNDING"
    assert lab._strategy_name({"strategie": "arbitrage cross"}) == "ARBITRAGE"
    assert lab._strategy_name({"bot_decision": "fusion"}) == "FUSION"
    assert lab._strategy_name({"reason": "consensus"}) == "CONSENSUS"
    assert lab._strategy_name({"leader_action": "copy leader"}) == "COPY"
    assert lab._strategy_name({}) == "LEGACY_OR_UNKNOWN"

    assert lab._accounting_schema({}, {}) is None
    assert lab._accounting_schema({"accounting_schema_version": " v1 "}, {}) == "v1"
    assert lab._accounting_schema({}, {"accounting_schema_version": ""}) is None


def test_cost_helpers_and_funding_sign_convention() -> None:
    assert lab._entry_cost_usdc({"fee_already_embedded_in_entry_price": True}) == 0.0
    assert lab._entry_cost_usdc({"fee_paid": "1.2"}) == 1.2
    assert lab._entry_cost_usdc({}) is None

    assert lab._exit_cost_usdc({"fee_already_embedded_in_exit_price": True}) == 0.0
    assert lab._exit_cost_usdc({"exit_costs": "2.3"}) == 2.3
    assert lab._exit_cost_usdc({}) is None

    assert lab._funding_cost_usdc({}, {"funding_cost_usdc": 4}) == 4.0
    assert lab._funding_cost_usdc({"funding_pnl_usdc": 3}, {}) == -3.0
    assert lab._funding_cost_usdc({}, {}) is None


def test_contamination_reasons_are_explicit_and_composable() -> None:
    reasons = lab._contamination_reasons(
        {
            "data_origin": "SYNTHETIC DEMO",
            "maker_fill_assumed": True,
            "price_source": "MID",
            "cost_defaulted_to_zero": True,
        },
        {},
    )
    assert reasons == [
        "SYNTHETIC_OR_FAKE_DATA",
        "UNEVIDENCED_EXECUTION_ASSUMPTION",
        "MID_PRICE_NOT_EXECUTABLE",
        "KNOWN_ACCOUNTING_CONTAMINATION",
    ]
    assert lab._contamination_reasons(
        {"price_source": "MID", "entry_executable_price": 100},
        {},
    ) == []


def test_discover_ledgers_deterministic_and_json_iterator(tmp_path) -> None:
    assert lab.discover_session_ledgers(tmp_path) == ()
    active = tmp_path / lab.CANONICAL_LEDGER_NAME
    active.write_text("{}\n", encoding="utf-8")
    archive = tmp_path / "_archives" / "s1" / lab.CANONICAL_LEDGER_NAME
    archive.parent.mkdir(parents=True)
    archive.write_text("{}\n", encoding="utf-8")
    empty = tmp_path / "_archives" / "s2" / lab.CANONICAL_LEDGER_NAME
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    paths = lab.discover_session_ledgers(tmp_path)
    assert active in paths and archive in paths and empty not in paths
    assert list(paths) == sorted(paths, key=lambda path: str(path).lower())

    rows_file = tmp_path / "rows.jsonl"
    rows_file.write_text(
        "\n".join(["", json.dumps({"a": 1}), "bad", "[]", json.dumps({"b": 2})]),
        encoding="utf-8",
    )
    rows = list(lab._iter_json_rows(rows_file))
    assert rows == [(2, {"a": 1}), (3, None), (4, None), (5, {"b": 2})]
    assert list(lab._iter_json_rows(tmp_path / "missing")) == []
