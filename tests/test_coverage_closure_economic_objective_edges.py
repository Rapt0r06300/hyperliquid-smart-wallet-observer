from __future__ import annotations

import math

import hl_observer.simulation.economic_objective as objective


def _segment(*, net: float = 2.3, count: int = 2, hash_char: str = "b", **overrides):
    row = {
        "gross_pnl_usd": net + 0.4,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": net,
        "sample_count": count,
        "trade_ids_count": count,
        "duplicate_trade_ids": 0,
        "trade_ids_sha256": hash_char * 64,
        "liquidatable_net": True,
    }
    row.update(overrides)
    return row


def _proof(**overrides):
    row = {
        "family": "lead_lag",
        "paper_read_only": True,
        "real_execution": False,
        "starting_capital_usd": 1000.0,
        "parameters_frozen": True,
        "opened_positions": 4,
        "closed_positions": 4,
        "gross_pnl_usd": 5.8,
        "fees_usd": 0.3,
        "spread_cost_usd": 0.3,
        "slippage_cost_usd": 0.3,
        "latency_cost_usd": 0.3,
        "net_pnl_usd": 4.6,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 4,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(net=2.3, hash_char="b", no_lookahead=True),
        "forward": _segment(net=2.3, hash_char="c", post_freeze=True),
        "placebos": {"beaten": True},
    }
    row.update(overrides)
    return row


def test_number_and_family_normalisation_edges() -> None:
    assert objective.canonical_family(" Copy-Vault ") == "copy_vault"
    assert objective.canonical_family("lead lag") == "lead_lag"
    assert objective.canonical_family(None) == ""
    assert objective._number("1.25") == 1.25
    assert objective._number(None) is None
    assert objective._number("bad") is None
    assert objective._number(math.nan) is None
    assert objective._number(math.inf) is None
    assert objective._number(-math.inf) is None


def test_segment_economics_fails_closed_for_missing_cost_identity_and_liquidation() -> None:
    issues: list[str] = []
    assert objective._segment_economics(None, label="OOS", issues=issues) is None
    assert issues == []

    issues = []
    segment = _segment(
        fees_usd=None,
        spread_cost_usd=-0.1,
        liquidatable_net=False,
        duplicate_trade_ids=1,
        trade_ids_count=1,
        trade_ids_sha256="short",
    )
    assert objective._segment_economics(segment, label="OOS", issues=issues) is None
    assert "OOS_UNMEASURED:fees_usd" in issues
    assert "OOS_NEGATIVE_COST:spread_cost_usd" in issues
    assert "OOS_NOT_LIQUIDATABLE_NET" in issues
    assert "OOS_DUPLICATE_TRADE_IDENTITIES" in issues
    assert "OOS_TRADE_ID_PROOF_INCOMPLETE" in issues


def test_segment_economics_rejects_reconciliation_and_accepts_uppercase_liquidatable() -> None:
    issues: list[str] = []
    bad = _segment(net=99.0)
    assert objective._segment_economics(bad, label="FORWARD", issues=issues) is None
    assert "FORWARD_ECONOMIC_RECONCILIATION_FAILED" in issues

    issues = []
    good = _segment()
    good.pop("liquidatable_net")
    good["LIQUIDATABLE_NET"] = True
    result = objective._segment_economics(good, label="FORWARD", issues=issues)
    assert result is not None
    assert issues == []


def test_cross_provenance_reports_each_missing_atomic_proof() -> None:
    issues: list[str] = []
    objective._validate_cross_provenance({}, issues)
    assert set(issues) == {
        "CROSS_VENUE_CERTIFIED_ATOMIC_SOURCE_MISSING",
        "CROSS_VENUE_CERTIFIED_SNAPSHOT_PROOF_MISSING",
        "CROSS_VENUE_MAPPING_PROOF_MISSING",
        "CROSS_VENUE_SKEW_PROOF_MISSING",
        "CROSS_VENUE_FOUR_FILL_CONTRACT_MISSING",
    }


def test_top_level_contract_rejects_unknown_family_capital_positions_and_freeze() -> None:
    result = objective.evaluate_objective(
        _proof(
            family="carry",
            paper_read_only=False,
            real_execution=True,
            starting_capital_usd=999.0,
            parameters_frozen=False,
            opened_positions=0,
            closed_positions=None,
        )
    )
    reasons = result["objective_reasons"]
    assert "NON_CANONICAL_OR_INACTIVE_FAMILY" in reasons
    assert "NOT_PAPER_READ_ONLY" in reasons
    assert "INVALID_STARTING_CAPITAL" in reasons
    assert "PARAMETERS_NOT_FROZEN_BEFORE_EVALUATION" in reasons
    assert "POSITIONS_NOT_FULLY_OPENED_AND_CLOSED" in reasons
    assert result["eligible_net_pnl_usd"] is None


def test_copy_generalisation_requires_measured_positive_heldout_net() -> None:
    result = objective.evaluate_objective(
        _proof(
            family="copy_vault",
            vault_generalization={"sample_count": 20, "net_bps": None},
        )
    )
    assert "COPY_HELDOUT_VAULT_NET_MISSING" in result["objective_reasons"]


def test_top_level_cost_and_trade_identity_failures_are_explicit() -> None:
    result = objective.evaluate_objective(
        _proof(
            gross_pnl_usd=None,
            fees_usd=-0.1,
            liquidatable_net=False,
            duplicate_trade_ids=2,
            trade_ids_count=3,
            trade_ids_sha256="bad",
        )
    )
    reasons = result["objective_reasons"]
    assert "UNMEASURED:gross_pnl_usd" in reasons
    assert "NEGATIVE_COST:fees_usd" in reasons
    assert "NOT_LIQUIDATABLE_NET" in reasons
    assert "DUPLICATE_TRADE_IDENTITIES" in reasons
    assert "TRADE_ID_PROOF_INCOMPLETE" in reasons


def test_oos_failure_modes_cover_missing_negative_and_no_lookahead() -> None:
    missing = objective.evaluate_objective(_proof(oos=None))
    assert "OOS_PROOF_MISSING" in missing["objective_reasons"]

    negative = objective.evaluate_objective(
        _proof(oos=_segment(net=-0.1, gross_pnl_usd=0.3, no_lookahead=True))
    )
    assert "OOS_NET_NOT_POSITIVE" in negative["objective_reasons"]

    causal_missing = objective.evaluate_objective(_proof(oos=_segment(net=2.3)))
    assert "OOS_NO_LOOKAHEAD_PROOF_MISSING" in causal_missing["objective_reasons"]


def test_forward_failure_modes_cover_missing_negative_and_post_freeze() -> None:
    missing = objective.evaluate_objective(_proof(forward=None))
    assert "FORWARD_POST_FREEZE_PROOF_MISSING" in missing["objective_reasons"]

    negative = objective.evaluate_objective(
        _proof(forward=_segment(net=-0.1, gross_pnl_usd=0.3, post_freeze=True))
    )
    assert "FORWARD_NET_NOT_POSITIVE" in negative["objective_reasons"]

    freeze_missing = objective.evaluate_objective(_proof(forward=_segment(net=2.3)))
    assert "FORWARD_NOT_PROVEN_POST_FREEZE" in freeze_missing["objective_reasons"]


def test_placebo_and_target_threshold_fail_closed_without_hiding_proof_net() -> None:
    placebo = objective.evaluate_objective(_proof(placebos={"beaten": False}))
    assert "PLACEBO_NOT_BEATEN" in placebo["objective_reasons"]
    assert placebo["proof_net_pnl_usd"] == 4.6
    assert placebo["eligible_net_pnl_usd"] is None

    below = objective.evaluate_objective(
        _proof(
            oos=_segment(net=1.9, gross_pnl_usd=2.3, hash_char="d", no_lookahead=True),
            forward=_segment(net=2.0, gross_pnl_usd=2.4, hash_char="e", post_freeze=True),
        )
    )
    assert below["proof_net_pnl_usd"] == 3.9
    assert "TARGET_NET_USD_NOT_REACHED" in below["objective_reasons"]

    exact = objective.evaluate_objective(
        _proof(
            oos=_segment(net=2.0, gross_pnl_usd=2.4, hash_char="f", no_lookahead=True),
            forward=_segment(net=2.0, gross_pnl_usd=2.4, hash_char="0", post_freeze=True),
        )
    )
    assert exact["proof_net_pnl_usd"] == 4.0
    assert exact["objective_status"] == "ATTEINT"
    assert exact["eligible_net_pnl_usd"] == 4.0
