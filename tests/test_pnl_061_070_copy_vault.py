from __future__ import annotations

import copy

import pytest

from hl_observer.backtesting.economic_hypotheses_v3 import (
    qualify_lead_lag_queue_maker_train_only,
)
from hl_observer.backtesting.fee_model import maker_rebate_receipt
from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.economics.proof_binding import (
    audit_cross_artifact_numeric_consistency,
    audit_economic_contract_receipt,
)
from hl_observer.economics.numeric import bps_to_quote_usd_receipt
from hl_observer.simulation.accounting_truth import fee_token_to_pnl_currency_receipt
from hl_observer.simulation.cost_breakdown import spread_not_double_counted_receipt
from hl_observer.simulation.fee_model import fee_tier_validity_receipt
from hl_observer.simulation.ledger_integrity import (
    seal_chain,
    verify_chain,
)


def _copy_vault_receipt() -> dict[str, object]:
    return build_copy_vault_contract(
        mode=EconomicRunMode.CERTIFIABLE,
        notional_usd=150.0,
        copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0,
        max_target_lag_ms=30_000.0,
    ).receipt()


def test_pnl061_fee_tier_is_valid_only_inside_its_effective_interval() -> None:
    valid = fee_tier_validity_receipt(
        fee_bps=4.5,
        valid_from_epoch_ms=100,
        valid_until_epoch_ms=200,
        as_of_epoch_ms=150,
        source="safe://fee-tier-v1",
    )
    expired = fee_tier_validity_receipt(
        fee_bps=4.5,
        valid_from_epoch_ms=100,
        valid_until_epoch_ms=200,
        as_of_epoch_ms=200,
        source="safe://fee-tier-v1",
    )

    assert valid["status"] == "PROVEN"
    assert expired["status"] == "UNMEASURABLE"


def test_pnl062_non_usd_quote_fee_requires_explicit_conversion() -> None:
    converted = fee_token_to_pnl_currency_receipt(
        fee_amount=2.0,
        fee_token="USDC",
        pnl_currency="USD",
        token_to_pnl_rate=0.999,
    )
    missing = fee_token_to_pnl_currency_receipt(
        fee_amount=2.0,
        fee_token="TOKEN",
        pnl_currency="USD",
        token_to_pnl_rate=None,
    )

    assert converted["status"] == "PROVEN"
    assert converted["fee_pnl_currency"] == 1.998
    assert missing["status"] == "UNMEASURABLE"


def test_pnl063_exceptional_cost_is_bounded_by_single_observed_mid_fill_delta() -> None:
    receipt = spread_not_double_counted_receipt(
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.2,
        side="BUY",
    )

    assert receipt["status"] == "PROVEN"
    assert receipt["spread_count"] == 1
    assert receipt["reconciles"] is True


def test_pnl064_paper_and_replay_artifacts_must_share_authoritative_scalars() -> None:
    matching = audit_cross_artifact_numeric_consistency(
        authority_name="paper-run",
        authority_values={"net_pnl_usd": 1.25, "fees_usd": 0.18},
        artifacts={
            "replay": {"net_pnl_usd": 1.25, "fees_usd": 0.18},
            "dashboard": {"net_pnl_usd": 1.25, "fees_usd": 0.18},
        },
        fields=("net_pnl_usd", "fees_usd"),
    )
    divergent = audit_cross_artifact_numeric_consistency(
        authority_name="paper-run",
        authority_values={"net_pnl_usd": 1.25},
        artifacts={"replay": {"net_pnl_usd": 1.26}},
        fields=("net_pnl_usd",),
    )

    assert matching["ready"] is True
    assert divergent["ready"] is False
    assert any("ARTIFACT_VALUE_MISMATCH" in issue for issue in divergent["issues"])


def test_pnl065_maker_favorable_fill_requires_queue_consumption_evidence() -> None:
    report = {
        "maker_queue_candidates": [
            {
                "coin": "ETH",
                "walk_forward_segment": "train",
                "lead_shock_bps": 30.0,
                "initial_qty_ahead": 1.0,
                "paper_order_qty": 1.0,
                "required_qty_for_full_fill": 2.0,
                "queue_events": [{"traded_qty_at_level": 2.0, "book_size_change": 0.0}],
                "liquidatable_net": True,
                "gross_pnl_usd": 2.0,
                "fees_usd": 0.1,
                "spread_cost_usd": 0.0,
                "slippage_cost_usd": 0.0,
                "latency_cost_usd": 0.0,
                "net_pnl_usd": 1.9,
            }
        ],
        "maker_queue_replay": {
            "latency_measured": True,
            "strong_shocks_seen": 1,
            "train_placebo_net_pnl_usd": 0.0,
        },
    }
    receipt = qualify_lead_lag_queue_maker_train_only(report, minimum_trades=1)
    missing = qualify_lead_lag_queue_maker_train_only(
        {"maker_queue_candidates": [{"coin": "ETH", "is_train": True}]}, minimum_trades=1
    )

    assert receipt["queue_proven_fills"] == 1
    assert missing["status"] == "MAKER_REPLAY_EVIDENCE_REQUIRED"


def test_pnl066_self_reported_proven_receipt_is_rechecked_by_hashes() -> None:
    receipt = _copy_vault_receipt()
    tampered = copy.deepcopy(receipt)
    tampered["certification"]["ready"] = False  # type: ignore[index]

    assert audit_economic_contract_receipt(receipt, expected_family="COPY_VAULT")["ready"] is True
    audited = audit_economic_contract_receipt(tampered, expected_family="COPY_VAULT")
    assert audited["ready"] is False
    assert "ECONOMIC_CERTIFICATION_NOT_READY" in audited["issues"]


def test_pnl067_mutating_one_ledger_event_breaks_the_frozen_chain() -> None:
    sealed = list(seal_chain([{"event_id": "fill-1", "record_type": "FILL", "value": 1}], session_id="paper"))
    sealed[0]["value"] = 2

    with pytest.raises(ValueError, match="event_hash mismatch"):
        verify_chain(sealed)


def test_pnl068_independent_oracle_must_match_the_authoritative_pnl() -> None:
    receipt = audit_cross_artifact_numeric_consistency(
        authority_name="ledger",
        authority_values={"net_pnl_usd": 2.0},
        artifacts={"independent_oracle": {"net_pnl_usd": 1.5}},
        fields=("net_pnl_usd",),
    )

    assert receipt["ready"] is False
    assert receipt["issues"] == ["ARTIFACT_VALUE_MISMATCH:independent_oracle:net_pnl_usd"]


def test_pnl069_dashboard_cannot_publish_decorative_profit() -> None:
    receipt = audit_cross_artifact_numeric_consistency(
        authority_name="ledger",
        authority_values={"net_pnl_usd": 2.0},
        artifacts={"dashboard": {"net_pnl_usd": 2.0}},
        fields=("net_pnl_usd",),
    )
    decorative = audit_cross_artifact_numeric_consistency(
        authority_name="ledger",
        authority_values={"net_pnl_usd": 2.0},
        artifacts={"dashboard": {"net_pnl_usd": 3.0}},
        fields=("net_pnl_usd",),
    )

    assert receipt["ready"] is True
    assert decorative["ready"] is False


def test_pnl070_partial_report_cannot_be_a_successful_economic_contract() -> None:
    receipt = _copy_vault_receipt()
    del receipt["economic_evidence_bundle"]

    audited = audit_economic_contract_receipt(receipt, expected_family="COPY_VAULT")

    assert audited["ready"] is False
    assert "ECONOMIC_EVIDENCE_BUNDLE_MISSING" in audited["issues"]

