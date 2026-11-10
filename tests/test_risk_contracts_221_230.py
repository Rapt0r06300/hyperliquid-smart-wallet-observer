from hl_observer.copying.copy_vault_risk_controls import (
    authoritative_risk_engine_receipt,
    drawdown_threshold_receipt,
    env_limits_monotonic_receipt,
    independent_security_veto_receipt,
    leverage_cost_receipt,
    paper_kill_switch_source_receipt,
    reduce_only_invariant_receipt,
    stream_outage_position_priority_receipt,
    vault_concentration_receipt,
    veto_order_receipt,
)


def test_lch221_one_authoritative_risk_engine() -> None:
    state = {"risk_engine_id": "risk-v1", "authoritative": True, "engine_count": 1, "paper_read_only": True}
    assert authoritative_risk_engine_receipt(state)["status"] == "PROVEN"
    state["engine_count"] = 2
    assert authoritative_risk_engine_receipt(state)["status"] == "REJECTED"


def test_lch222_veto_precedes_paper_order() -> None:
    row = {"veto_order": 1, "paper_order_order": 2, "real_execution": False}
    assert veto_order_receipt([row])["status"] == "PROVEN"
    row["veto_order"] = 3
    assert veto_order_receipt([row])["status"] == "REJECTED"


def test_lch223_leverage_cost_requires_canonical_350_usd_capital() -> None:
    assert leverage_cost_receipt({"capital_usd": 350, "leverage": 2, "leverage_cost_usd": 1})["status"] == "PROVEN"
    assert leverage_cost_receipt({"capital_usd": 200, "leverage": 2, "leverage_cost_usd": 1})["status"] == "UNMEASURABLE"
    assert leverage_cost_receipt({"capital_usd": 100, "leverage": 2, "leverage_cost_usd": 1})["status"] == "UNMEASURABLE"


def test_lch224_vault_concentration_is_bounded() -> None:
    assert vault_concentration_receipt([{"vault_id": "v1", "fraction": 0.2}], max_fraction=0.25)["status"] == "PROVEN"
    assert vault_concentration_receipt([{"vault_id": "v1", "fraction": 0.3}], max_fraction=0.25)["status"] == "REJECTED"


def test_lch225_outage_prioritizes_position_management() -> None:
    state = {"stream_healthy": False, "position_management_priority": True, "new_entries_allowed": False}
    assert stream_outage_position_priority_receipt(state)["status"] == "PROVEN"


def test_lch226_kill_switch_and_source_stop_are_distinct() -> None:
    state = {"paper_kill_switch": True, "sources_stopped": True, "kill_switch_reason": "risk", "source_stop_reason": "stale"}
    assert paper_kill_switch_source_receipt(state)["status"] == "PROVEN"


def test_lch227_drawdown_threshold_crossing_is_explicit() -> None:
    state = {"drawdown_fraction": 0.2, "threshold_fraction": 0.1, "threshold_crossed": True}
    assert drawdown_threshold_receipt(state)["status"] == "PROVEN"
    state["threshold_crossed"] = False
    assert drawdown_threshold_receipt(state)["status"] == "REJECTED"


def test_lch228_environment_cannot_lower_safety_limit() -> None:
    state = {"canonical_limit": 0.1, "effective_limit": 0.1, "env_override_attempted": False}
    assert env_limits_monotonic_receipt(state)["status"] == "PROVEN"
    state["effective_limit"] = 0.05
    assert env_limits_monotonic_receipt(state)["status"] == "REJECTED"


def test_lch229_all_pipelines_preserve_reduce_only() -> None:
    assert reduce_only_invariant_receipt([{"pipeline": "copy", "reduce_only": True, "real_execution": False}])["status"] == "PROVEN"
    assert reduce_only_invariant_receipt([{"pipeline": "copy", "reduce_only": False, "real_execution": False}])["status"] == "REJECTED"


def test_lch230_security_veto_is_independent_of_ai_score() -> None:
    state = {"security_veto": True, "ai_score": 0.99, "decision": "NO_TRADE", "real_execution": False}
    assert independent_security_veto_receipt(state)["status"] == "PROVEN"
    state["decision"] = "COPY"
    assert independent_security_veto_receipt(state)["status"] == "REJECTED"
