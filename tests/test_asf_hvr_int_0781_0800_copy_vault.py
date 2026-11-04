from hl_observer.backtest.runtime_parity import RuntimeReplayParityResult
from hl_observer.simulation.cost_components import (
    cost_components_safety_receipt,
    mark_mid_cost_receipt,
    runtime_parity_to_cost_boundary_receipt,
)


def _parity(**overrides):
    values = {
        "runtime_scope": None,
        "replay_scope": None,
        "runtime_decision": None,
        "replay_decision": None,
        "economics_match": True,
        "risk_match": True,
        "pnl_may_merge": False,
        "warnings": (),
    }
    values.update(overrides)
    return RuntimeReplayParityResult(**values)


def _cost(**overrides):
    result = mark_mid_cost_receipt(
        side="BUY",
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.2,
        mid_at_fill=100.15,
        fee_bps=1.0,
    )
    result.update(overrides)
    return result


def test_asf_hvr_0781_normal_fixture_joins_safely():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost())["status"] == "PROVEN"


def test_asf_hvr_0782_missing_cost_field_fails_closed():
    cost = _cost()
    cost.pop("total_bps")
    assert runtime_parity_to_cost_boundary_receipt(_parity(), cost)["status"] == "REJECTED"


def test_asf_hvr_0783_null_cost_field_fails_closed():
    incomplete = _cost(total_bps=None, unmeasured=["total_bps"])
    assert runtime_parity_to_cost_boundary_receipt(_parity(), incomplete)["status"] == "PROVEN"
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost(unmeasured=None))["status"] == "REJECTED"


def test_asf_hvr_0784_cost_schema_is_required():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost(schema_version="wrong"))["status"] == "REJECTED"


def test_asf_hvr_0785_invalid_runtime_parity_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt(_parity(economics_match=False), _cost())["status"] == "REJECTED"


def test_asf_hvr_0786_future_runtime_warning_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt(_parity(warnings=("FUTURE_DATA",)), _cost())["status"] == "REJECTED"


def test_asf_hvr_0787_risk_divergence_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt(_parity(risk_match=False), _cost())["status"] == "REJECTED"


def test_asf_hvr_0788_pnl_context_merge_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt(_parity(pnl_may_merge=True), _cost())["status"] == "REJECTED"


def test_asf_hvr_0789_unmeasured_costs_are_not_promoted():
    cost = _cost(status="UNMEASURABLE")
    assert runtime_parity_to_cost_boundary_receipt(_parity(), cost)["status"] == "PROVEN"


def test_asf_hvr_0790_real_execution_costs_are_rejected():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost(real_execution=True))["status"] == "REJECTED"


def test_asf_hvr_0791_cost_paper_flag_is_required():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost(paper_only=False))["status"] == "REJECTED"


def test_asf_hvr_0792_cost_unmeasured_must_be_a_list():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost(unmeasured="fees_bps"))["status"] == "REJECTED"


def test_asf_hvr_0793_empty_costs_are_rejected():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), {})["status"] == "REJECTED"


def test_asf_hvr_0794_missing_parity_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt(None, _cost())["status"] == "REJECTED"


def test_asf_hvr_0795_invalid_parity_type_fails_closed():
    assert runtime_parity_to_cost_boundary_receipt({}, _cost())["status"] == "REJECTED"


def test_asf_hvr_0796_join_is_paper_only():
    result = runtime_parity_to_cost_boundary_receipt(_parity(), _cost())
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_asf_hvr_0797_join_never_promotes():
    assert runtime_parity_to_cost_boundary_receipt(_parity(), _cost())["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_asf_hvr_0798_join_reports_both_boundaries():
    result = runtime_parity_to_cost_boundary_receipt(_parity(), _cost())
    assert result["parity_status"] == "PROVEN"
    assert result["cost_status"] == "PROVEN"


def test_asf_hvr_0799_invalid_cost_keeps_fail_closed():
    result = runtime_parity_to_cost_boundary_receipt(_parity(), cost_components_safety_receipt({}))
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True


def test_asf_hvr_0800_green_status_without_boundary_proof_is_rejected():
    result = runtime_parity_to_cost_boundary_receipt(_parity(), {"status": "PROVEN"})
    assert result["status"] == "REJECTED"
    assert result["fail_closed"] is True
