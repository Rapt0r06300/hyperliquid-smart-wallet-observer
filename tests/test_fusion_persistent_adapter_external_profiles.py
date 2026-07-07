from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.state import UiState


def _fusion_status_with_runtime(runtime):
    return {
        "status": "OK_LIVE_FUSION_RUNTIME",
        "paper_only": True,
        "real_execution": False,
        "runtime": runtime,
    }


def test_adapter_records_every_external_profile_execution_even_without_orders():
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-heartbeat-test"},
            "paper_orders": [],
            "external_profile_executions": [
                {
                    "repo_id": "17_rezzecup_whale_wallet_mirror_copy_trader",
                    "profile_id": "ext_rezzecup_whale_mirror_primary",
                    "family": "whale_wallet_mirror",
                    "kind": "COPY_FOLLOW",
                    "installed": True,
                    "status": "EXECUTED",
                    "decision": "NO_TRADE",
                    "reason": "NO_LEADER_VOTES",
                    "candidate_count": 0,
                    "accepted_paper_orders": 0,
                },
                {
                    "repo_id": "21_tony_42069_trader_tony_v4",
                    "profile_id": "ext_tony_autonomous_sltp_priority",
                    "family": "autonomous_sltp",
                    "kind": "FAST_TIMING",
                    "installed": True,
                    "status": "EXECUTED",
                    "decision": "EVALUATED_DIAGNOSTIC",
                    "reason": "PROFILE_EVALUATED_AS_GUARD_OR_SUPPORT_MODULE",
                    "candidate_count": 2,
                    "accepted_paper_orders": 0,
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=123_000)
    duplicate_report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=124_000)

    assert report["applied_count"] == 0
    assert report["external_profiles_executed"] == 2
    assert report["external_profile_events_recorded"] == 2
    assert "NO_PAPER_ORDERS" in report["reasons"]
    assert duplicate_report["external_profile_events_recorded"] == 0
    assert duplicate_report["external_profile_events_skipped"] == 2
    assert len(state.simulation_ledger_events) == 2
    assert all(row["paper_action_type"] == "ENGINE_EVALUATION" for row in state.simulation_ledger_events)
    assert {row["profile_id"] for row in state.simulation_ledger_events} == {
        "ext_rezzecup_whale_mirror_primary",
        "ext_tony_autonomous_sltp_priority",
    }


def test_adapter_shadows_accepted_ext_profile_direct_order_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", raising=False)
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-direct-paper-test"},
            "external_profile_executions": [
                {
                    "repo_id": "21_tony_42069_trader_tony_v4",
                    "profile_id": "ext_tony_autonomous_sltp_priority",
                    "family": "autonomous_sltp",
                    "kind": "FAST_TIMING",
                    "installed": True,
                    "status": "EXECUTED",
                    "decision": "PAPER_ORDER_ACCEPTED",
                    "reason": "PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER",
                    "candidate_count": 1,
                    "accepted_paper_orders": 1,
                },
            ],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:tony-sltp-hype-short",
                    "reason": "ACCEPT_PAPER_ORDER",
                    "coin": "HYPE",
                    "side": "SHORT",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_tony_autonomous_sltp_priority",
                    "reference_price": 70.0,
                    "metadata": {
                        "profile_family": "autonomous_sltp",
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "leader_wallets_count": 3,
                        "signal_age_ms": 1_000,
                        "edge_remaining_bps": 42.0,
                        "liquidity_score": 0.80,
                        "copy_degradation_bps": 12.0,
                    },
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=125_000)

    assert report["applied_count"] == 0
    assert report["external_direct_orders_shadowed"] == 1
    assert "EXTERNAL_GITHUB_DIRECT_MATERIALIZATION_DISABLED" in report["reasons"]
    assert report["external_profile_events_recorded"] == 1
    assert state.simulation_virtual_positions == {}
    assert any(row["paper_action_type"] == "ENGINE_EVALUATION" for row in state.simulation_ledger_events)
    assert not any(row.get("paper_action_type") == "OPEN" for row in state.simulation_ledger_events)


def test_adapter_can_materialize_ext_profile_direct_order_only_with_explicit_research_flag(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-direct-paper-test"},
            "external_profile_executions": [
                {
                    "repo_id": "21_tony_42069_trader_tony_v4",
                    "profile_id": "ext_tony_autonomous_sltp_priority",
                    "family": "autonomous_sltp",
                    "kind": "FAST_TIMING",
                    "installed": True,
                    "status": "EXECUTED",
                    "decision": "PAPER_ORDER_ACCEPTED",
                    "reason": "PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER",
                    "candidate_count": 1,
                    "accepted_paper_orders": 1,
                },
            ],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:tony-sltp-hype-short",
                    "reason": "ACCEPT_PAPER_ORDER",
                    "coin": "HYPE",
                    "side": "SHORT",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_tony_autonomous_sltp_priority",
                    "reference_price": 70.0,
                    "metadata": {
                        "profile_family": "autonomous_sltp",
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "leader_wallets_count": 3,
                        "signal_age_ms": 1_000,
                        "edge_remaining_bps": 42.0,
                        "liquidity_score": 0.80,
                        "copy_degradation_bps": 12.0,
                    },
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=125_000)

    assert report["applied_count"] == 1
    assert report["external_direct_orders_shadowed"] == 0
    assert report["external_profile_events_recorded"] == 1
    assert len(state.simulation_virtual_positions) == 1
    position = next(iter(state.simulation_virtual_positions.values()))
    assert position["coin"] == "HYPE"
    assert position["side"] == "SHORT"
    assert position["position_mode"] == "EXTERNAL_GITHUB_DIRECT_PAPER"
    assert position["strategy_id"] == "ext_tony_autonomous_sltp_priority"
    assert position["edge_remaining_bps"] == 42.0
    assert position["signal_age_ms"] == 1_000
    assert position["leader_wallets_count"] == 3
    assert position["liquidity_score"] == 0.80
    assert position["copy_degradation_bps"] == 12.0
    assert any(row["paper_action_type"] == "ENGINE_EVALUATION" for row in state.simulation_ledger_events)
    assert any(row.get("paper_action_type") == "OPEN" for row in state.simulation_ledger_events)


def test_adapter_shadows_copy_profile_direct_order_when_paper_engine_rejects_it(monkeypatch):
    monkeypatch.delenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", raising=False)
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-copy-profile-paper-fallback"},
            "external_profile_executions": [
                {
                    "repo_id": "17_rezzecup_whale_wallet_mirror_copy_trader",
                    "profile_id": "ext_rezzecup_whale_mirror_primary",
                    "family": "whale_wallet_mirror",
                    "kind": "COPY_FOLLOW",
                    "installed": True,
                    "status": "EXECUTED",
                    "decision": "PAPER_ORDER_ACCEPTED",
                    "reason": "PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER",
                    "candidate_count": 2,
                    "accepted_paper_orders": 1,
                },
            ],
            "paper_engine": {
                "accepted_count": 0,
                "decisions": [
                    {
                        "accepted": False,
                        "trade": {"reason_codes": ["edge remaining below minimum"]},
                        "position": None,
                    }
                ],
            },
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:rezzecup-copy-sol-long",
                    "reason": "ACCEPT_PAPER_ORDER",
                    "coin": "SOL",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_rezzecup_whale_mirror_primary",
                    "reference_price": 75.0,
                    "metadata": {
                        "source": "copy_conflict_resolver",
                        "profile_family": "copy_follow",
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "leader_wallets_count": 3,
                        "signal_age_ms": 900,
                        "edge_remaining_bps": 38.0,
                        "liquidity_score": 0.75,
                        "copy_degradation_bps": 14.0,
                    },
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=125_500)

    assert report["applied_count"] == 0
    assert report["external_direct_orders_shadowed"] == 1
    assert "EXTERNAL_GITHUB_DIRECT_MATERIALIZATION_DISABLED" in report["reasons"]
    assert state.simulation_virtual_positions == {}
    assert any(row.get("paper_action_type") == "ENGINE_EVALUATION" for row in state.simulation_ledger_events)
    assert not any(row.get("reason") == "EXTERNAL_GITHUB_COPY_ACCEPTED_PAPER_ONLY" for row in state.simulation_ledger_events)


def test_adapter_does_not_double_open_copy_profile_when_paper_engine_already_accepted():
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-copy-no-double-open"},
            "external_profile_executions": [],
            "paper_engine": {
                "accepted_count": 1,
                "decisions": [
                    {
                        "accepted": True,
                        "trade": {
                            "trade_id": "papertrade:accepted-copy",
                            "source_delta_id": "fusion-paper-engine:HYPE:LONG:100",
                            "fill_price": 70.1,
                            "notional_usdt": 40.0,
                            "fees_and_cost_bps": 8.0,
                            "coin": "HYPE",
                            "side": "LONG",
                        },
                        "position": {
                            "source_delta_id": "fusion-paper-engine:HYPE:LONG:100",
                            "coin": "HYPE",
                            "side": "LONG",
                            "quantity": 0.570613,
                            "entry_price": 70.1,
                            "notional_usdt": 40.0,
                            "opened_at_ms": 126_000,
                            "leader_wallet": "0x" + "1" * 40,
                        },
                        "evidence_hash": "pevidence:accepted-copy",
                    }
                ],
            },
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:copy-direct-duplicate",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "strategy_id": "ext_rezzecup_whale_mirror_primary",
                    "reference_price": 70.0,
                    "metadata": {
                        "source": "copy_conflict_resolver",
                        "profile_family": "copy_follow",
                        "paper_only": True,
                    },
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=126_000)

    assert report["applied_count"] == 1
    assert len(state.simulation_virtual_positions) == 1
    position = next(iter(state.simulation_virtual_positions.values()))
    assert position["position_mode"] == "EXTERNAL_GITHUB_FUSION_PAPER"
    assert position["last_paper_ref"] == "papertrade:accepted-copy"


def test_adapter_refuses_paper_engine_entry_when_global_position_cap_reached(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAX_OPEN_POSITIONS", "1")
    monkeypatch.setenv("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", "400")
    state = UiState()
    state.simulation_virtual_positions = {
        "existing|BTC|LONG": {
            "wallet_address": "existing",
            "coin": "BTC",
            "side": "LONG",
            "direction": "LONG",
            "size": 0.001,
            "entry_price": 60_000.0,
            "notional_usdt": 60.0,
        }
    }
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "portfolio-cap-test"},
            "external_profile_executions": [],
            "paper_engine": {
                "accepted_count": 1,
                "decisions": [
                    {
                        "accepted": True,
                        "trade": {
                            "trade_id": "papertrade:cap-refused",
                            "source_delta_id": "fusion-paper-engine:HYPE:LONG:cap",
                            "fill_price": 70.0,
                            "notional_usdt": 40.0,
                            "fees_and_cost_bps": 8.0,
                            "coin": "HYPE",
                            "side": "LONG",
                        },
                        "position": {
                            "source_delta_id": "fusion-paper-engine:HYPE:LONG:cap",
                            "coin": "HYPE",
                            "side": "LONG",
                            "quantity": 0.571428,
                            "entry_price": 70.0,
                            "notional_usdt": 40.0,
                            "opened_at_ms": 126_000,
                            "leader_wallet": "0x" + "2" * 40,
                        },
                        "evidence_hash": "pevidence:cap-refused",
                    }
                ],
            },
            "paper_orders": [],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=126_000)

    assert report["applied_count"] == 0
    assert "PORTFOLIO_MAX_OPEN_POSITIONS" in report["reasons"]
    assert len(state.simulation_virtual_positions) == 1
    assert any(
        row.get("paper_action_type") == "NO_TRADE"
        and row.get("reason") == "PORTFOLIO_MAX_OPEN_POSITIONS"
        and row.get("coin") == "HYPE"
        for row in state.simulation_ledger_events
    )


def test_adapter_refuses_paper_engine_entry_when_global_exposure_cap_reached(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MAX_OPEN_POSITIONS", "10")
    monkeypatch.setenv("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", "75")
    state = UiState()
    state.simulation_virtual_positions = {
        "existing|BTC|LONG": {
            "wallet_address": "existing",
            "coin": "BTC",
            "side": "LONG",
            "direction": "LONG",
            "size": 0.001,
            "entry_price": 60_000.0,
            "notional_usdt": 60.0,
        }
    }
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "portfolio-exposure-test"},
            "external_profile_executions": [],
            "paper_engine": {
                "accepted_count": 1,
                "decisions": [
                    {
                        "accepted": True,
                        "trade": {
                            "trade_id": "papertrade:exposure-refused",
                            "source_delta_id": "fusion-paper-engine:SOL:SHORT:exposure",
                            "fill_price": 75.0,
                            "notional_usdt": 40.0,
                            "fees_and_cost_bps": 8.0,
                            "coin": "SOL",
                            "side": "SHORT",
                        },
                        "position": {
                            "source_delta_id": "fusion-paper-engine:SOL:SHORT:exposure",
                            "coin": "SOL",
                            "side": "SHORT",
                            "quantity": 0.533333,
                            "entry_price": 75.0,
                            "notional_usdt": 40.0,
                            "opened_at_ms": 127_000,
                            "leader_wallet": "0x" + "3" * 40,
                        },
                        "evidence_hash": "pevidence:exposure-refused",
                    }
                ],
            },
            "paper_orders": [],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=127_000)

    assert report["applied_count"] == 0
    assert "PORTFOLIO_MAX_TOTAL_EXPOSURE" in report["reasons"]
    assert len(state.simulation_virtual_positions) == 1
    assert any(
        row.get("paper_action_type") == "NO_TRADE"
        and row.get("reason") == "PORTFOLIO_MAX_TOTAL_EXPOSURE"
        and row.get("coin") == "SOL"
        for row in state.simulation_ledger_events
    )


def test_adapter_refuses_copy_profile_direct_order_without_measurable_edge(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-copy-profile-missing-edge"},
            "external_profile_executions": [],
            "paper_engine": {"accepted_count": 0, "decisions": []},
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:rezzecup-copy-sol-no-edge",
                    "reason": "ACCEPT_PAPER_ORDER",
                    "coin": "SOL",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_rezzecup_whale_mirror_primary",
                    "reference_price": 75.0,
                    "metadata": {
                        "source": "copy_conflict_resolver",
                        "profile_family": "copy_follow",
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "leader_wallets_count": 3,
                        "signal_age_ms": 500,
                        "liquidity_score": 0.8,
                        "copy_degradation_bps": 12.0,
                    },
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=125_750)

    assert report["applied_count"] == 0
    assert "DIRECT_COPY_EDGE_MISSING" in report["reasons"]
    assert state.simulation_virtual_positions == {}
    assert any(
        row.get("paper_action_type") == "NO_TRADE"
        and row.get("reason") == "DIRECT_COPY_EDGE_MISSING"
        and row.get("strategy_id") == "ext_rezzecup_whale_mirror_primary"
        for row in state.simulation_ledger_events
    )


def test_adapter_releases_open_duplicate_key_after_direct_paper_close(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    state = UiState()
    open_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-direct-open-close-release"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:hype-open-release",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_momentum_research_profile",
                    "reference_price": 70.0,
                    "metadata": {
                        "profile_family": "momentum_research",
                        "fees_bps": 8.0,
                        "paper_only": True,
                    },
                }
            ],
        }
    )
    open_report = apply_fusion_paper_orders_to_state(state, open_status, current_ms=125_000)
    assert open_report["applied_count"] == 1
    assert "fusion-runtime-order:paper:hype-open-release" in state.simulation_processed_delta_keys

    close_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-direct-open-close-release"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:hype-close-release",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "CLOSE",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_momentum_research_profile",
                    "reference_price": 70.5,
                    "metadata": {
                        "profile_family": "momentum_research",
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "close_reason": "TEST_DIRECT_CLOSE_RELEASE",
                    },
                }
            ],
        }
    )
    close_report = apply_fusion_paper_orders_to_state(state, close_status, current_ms=126_000)

    assert close_report["applied_count"] == 1
    assert state.simulation_virtual_positions == {}
    assert "fusion-runtime-order:paper:hype-open-release" not in state.simulation_processed_delta_keys
    assert "fusion-runtime-order:paper:hype-close-release" in state.simulation_processed_delta_keys
    assert state.simulation_ledger_events[-1]["paper_action_type"] == "CLOSE"
    assert state.simulation_ledger_events[-1]["source_delta_key"] == "fusion-runtime-order:paper:hype-open-release"


def test_adapter_refuses_direct_external_order_without_reference_price():
    state = UiState()
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "external-direct-missing-price"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:missing-price",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "strategy_id": "ext_tony_autonomous_sltp_priority",
                    "reference_price": 0.0,
                },
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=126_000)

    assert report["applied_count"] == 0
    assert "NO_MATERIALIZABLE_PAPER_POSITION" in report["reasons"]
    assert state.simulation_virtual_positions == {}
