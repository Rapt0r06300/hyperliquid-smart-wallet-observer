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
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
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


def test_adapter_persists_paper_engine_entry_evidence_for_auditable_pnl():
    state = UiState()
    wallets = ["0x" + "a" * 40, "0x" + "b" * 40]
    fusion_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "evidence-persistence"},
            "external_profile_executions": [],
            "paper_orders": [],
            "paper_engine": {
                "accepted_count": 1,
                "decisions": [
                    {
                        "accepted": True,
                        "trade": {
                            "trade_id": "papertrade:evidence",
                            "source_delta_id": "fusion-paper-engine:BTC:LONG:evidence",
                            "fill_price": 65_010.0,
                            "notional_usdt": 40.0,
                            "fees_and_cost_bps": 8.0,
                            "coin": "BTC",
                            "side": "LONG",
                        },
                        "position": {
                            "source_delta_id": "fusion-paper-engine:BTC:LONG:evidence",
                            "coin": "BTC",
                            "side": "LONG",
                            "quantity": 40.0 / 65_010.0,
                            "entry_price": 65_010.0,
                            "notional_usdt": 40.0,
                            "opened_at_ms": 130_000,
                            "leader_wallet": ",".join(wallets),
                        },
                        "evidence_hash": "pevidence:auditable",
                        "decision_context": {
                            "consensus_wallets": 2,
                            "leader_wallets": wallets,
                            "signal_age_ms": 750,
                            "edge_remaining_bps": 31.5,
                            "liquidity_score": 0.91,
                            "copy_degradation_bps": 9.5,
                            "edge_source": "DISTILLED_MEASURED_CANDIDATE_EDGE",
                            "edge_is_empirical": True,
                        },
                    }
                ],
            },
        }
    )

    report = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=130_000)

    assert report["applied_count"] == 1
    position = next(iter(state.simulation_virtual_positions.values()))
    assert position["leader_wallets_count"] == 2
    assert position["signal_age_ms"] == 750
    assert position["edge_remaining_bps"] == 31.5
    assert position["copy_degradation_bps"] == 9.5
    assert position["edge_is_empirical"] is True
    opened = next(row for row in state.simulation_ledger_events if row.get("paper_action_type") == "OPEN")
    assert opened["leader_wallets_count"] == 2
    assert opened["edge_source"] == "DISTILLED_MEASURED_CANDIDATE_EDGE"


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
    # MAX_TOTAL_EXPOSURE_USDT = budget de MARGE ; le plafond compare est en NOTIONAL
    # (= budget x levier). A levier 1, le budget 75 est donc un plafond notional de 75 :
    # position existante 60 + nouvelle 40 = 100 > 75 -> doit etre REFUSE.
    monkeypatch.setenv("HYPERSMART_MAX_OPEN_POSITIONS", "10")
    monkeypatch.setenv("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", "75")
    monkeypatch.setenv("HYPERSMART_SIMULATION_LEVERAGE", "1")
    monkeypatch.setenv("HYPERSMART_MAX_POSITION_USDT", "40")
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
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
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


def test_closed_position_does_not_release_consumed_event_identity(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
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
    assert "fusion-runtime-order:paper:hype-open-release" in state.simulation_processed_delta_keys
    assert "fusion-runtime-order:paper:hype-close-release" in state.simulation_processed_delta_keys
    assert state.simulation_ledger_events[-1]["paper_action_type"] == "CLOSE"
    assert state.simulation_ledger_events[-1]["source_delta_key"] == "fusion-runtime-order:paper:hype-open-release"


def test_direct_close_requires_exact_position_instance(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    state = UiState()
    state.simulation_virtual_positions = {
        "ext_strategy_a|HYPE|LONG": {
            "coin": "HYPE",
            "side": "LONG",
            "size": 1.0,
            "entry_price": 70.0,
            "entry_costs": 0.0,
            "wallet_address": "ext_strategy_a",
            "source_delta_key": "open-a",
        },
        "ext_strategy_b|HYPE|LONG": {
            "coin": "HYPE",
            "side": "LONG",
            "size": 2.0,
            "entry_price": 71.0,
            "entry_costs": 0.0,
            "wallet_address": "ext_strategy_b",
            "source_delta_key": "open-b",
        },
    }
    ambiguous_close = _fusion_status_with_runtime(
        {
            "session": {"session_id": "exact-close"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:hype-close-ambiguous",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "CLOSE",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_strategy_a",
                    "reference_price": 72.0,
                    "metadata": {"fees_bps": 8.0, "paper_only": True},
                }
            ],
        }
    )

    ambiguous_report = apply_fusion_paper_orders_to_state(state, ambiguous_close, current_ms=127_000)

    assert ambiguous_report["applied_count"] == 0
    assert "NO_MATCHING_DIRECT_PAPER_POSITION_TO_CLOSE" in ambiguous_report["reasons"]
    assert set(state.simulation_virtual_positions) == {
        "ext_strategy_a|HYPE|LONG",
        "ext_strategy_b|HYPE|LONG",
    }

    exact_close = _fusion_status_with_runtime(
        {
            "session": {"session_id": "exact-close"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:hype-close-exact",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 25.0,
                    "action": "CLOSE",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_strategy_a",
                    "reference_price": 72.0,
                    "metadata": {
                        "fees_bps": 8.0,
                        "paper_only": True,
                        "position_key": "ext_strategy_a|HYPE|LONG",
                    },
                }
            ],
        }
    )

    exact_report = apply_fusion_paper_orders_to_state(state, exact_close, current_ms=128_000)

    assert exact_report["applied_count"] == 1
    assert set(state.simulation_virtual_positions) == {"ext_strategy_b|HYPE|LONG"}
    assert state.simulation_ledger_events[-1]["matched_position_key"] == "ext_strategy_a|HYPE|LONG"


def test_direct_ab_entry_and_exit_costs_are_both_in_net_pnl(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    monkeypatch.setenv("HYPERSMART_SIMULATION_LEVERAGE", "1")
    monkeypatch.setenv("HYPERSMART_MAX_POSITION_USDT", "100")
    state = UiState()
    open_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "round-trip-costs"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:cost-open",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 100.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_cost_test",
                    "reference_price": 100.0,
                    "metadata": {"all_in_cost_bps": 10.0, "paper_only": True},
                }
            ],
        }
    )
    assert apply_fusion_paper_orders_to_state(state, open_status, current_ms=129_000)["applied_count"] == 1
    position_key = "ext_cost_test|HYPE|LONG"
    assert state.simulation_virtual_positions[position_key]["entry_costs"] == 0.1

    close_status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "round-trip-costs"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:cost-close",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 101.0,
                    "action": "CLOSE",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_cost_test",
                    "reference_price": 101.0,
                    "metadata": {
                        "all_in_cost_bps": 10.0,
                        "paper_only": True,
                        "position_key": position_key,
                    },
                }
            ],
        }
    )

    assert apply_fusion_paper_orders_to_state(state, close_status, current_ms=130_000)["applied_count"] == 1
    close_event = state.simulation_ledger_events[-1]
    assert close_event["gross_pnl_usdc"] == 1.0
    assert close_event["entry_cost_carried_usdc"] == 0.1
    assert close_event["fee_cost_usdc"] == 0.101
    assert close_event["total_round_trip_cost_usdc"] == 0.201
    assert close_event["estimated_net_pnl_usdc"] == 0.799
    assert state.simulation_realized_pnl_usdc == 0.799


def test_direct_ab_missing_execution_cost_is_rejected(monkeypatch):
    monkeypatch.setenv("HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION", "1")
    monkeypatch.setenv("HYPERSMART_AB_RESEARCH_ACK", "1")
    monkeypatch.setenv("HYPERSMART_LEDGER_SCOPE", "EXPERIMENTAL")
    state = UiState()
    status = _fusion_status_with_runtime(
        {
            "session": {"session_id": "missing-cost"},
            "external_profile_executions": [],
            "paper_orders": [
                {
                    "accepted": True,
                    "paper_only": True,
                    "real_execution": False,
                    "order_id": "paper:missing-cost",
                    "coin": "HYPE",
                    "side": "LONG",
                    "notional_usdt": 100.0,
                    "action": "OPEN",
                    "order_type": "PAPER_MARKET",
                    "strategy_id": "ext_missing_cost",
                    "reference_price": 100.0,
                    "metadata": {"paper_only": True},
                }
            ],
        }
    )

    report = apply_fusion_paper_orders_to_state(state, status, current_ms=131_000)

    assert report["applied_count"] == 0
    assert "DIRECT_EXECUTION_COST_UNMEASURABLE" in report["reasons"]
    assert state.simulation_virtual_positions == {}


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
