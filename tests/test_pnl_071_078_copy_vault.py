from __future__ import annotations

import copy

from hl_observer.backtesting.copy_vault_closure_gate import (
    ClosureCriterion,
    EvidenceRecord,
    NOT_PROVEN,
    build_closure_matrix,
)
from hl_observer.backtesting.copy_vault_scientific_controls import (
    extreme_trade_robustness_receipt,
    oos_retuning_revocation_receipt,
)
from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.economics.proof_binding import (
    audit_cross_artifact_numeric_consistency,
    audit_economic_contract_receipt,
)
from hl_observer.research.alpha_factory import TrialRegistry, metriques_distribution, ligne_canonique
from hl_observer.simulation.ledger_integrity import ledger_integrity_receipt


def _copy_vault_receipt() -> dict[str, object]:
    return build_copy_vault_contract(
        mode=EconomicRunMode.CERTIFIABLE,
        notional_usd=150.0,
        copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0,
        max_target_lag_ms=30_000.0,
    ).receipt()


def test_pnl071_assumption_snapshot_is_indivisible() -> None:
    receipt = _copy_vault_receipt()
    tampered = copy.deepcopy(receipt)
    assumptions = tampered["assumption_snapshot"]["assumptions"]  # type: ignore[index]
    assumptions[0]["value"] = f"{assumptions[0]['value']}-mutated"  # type: ignore[index]

    audit = audit_economic_contract_receipt(tampered, expected_family="COPY_VAULT")

    assert audit["ready"] is False
    assert "ASSUMPTION_SNAPSHOT_HASH_MISMATCH" in audit["issues"]


def test_pnl072_candidate_and_baseline_share_strict_periods() -> None:
    matching = audit_cross_artifact_numeric_consistency(
        authority_name="baseline-window",
        authority_values={"window_start_ms": 100, "window_end_ms": 200},
        artifacts={"candidate": {"window_start_ms": 100, "window_end_ms": 200}},
        fields=("window_start_ms", "window_end_ms"),
    )
    divergent = audit_cross_artifact_numeric_consistency(
        authority_name="baseline-window",
        authority_values={"window_start_ms": 100, "window_end_ms": 200},
        artifacts={"candidate": {"window_start_ms": 100, "window_end_ms": 201}},
        fields=("window_start_ms", "window_end_ms"),
    )

    assert matching["ready"] is True
    assert divergent["ready"] is False
    assert "ARTIFACT_VALUE_MISMATCH:candidate:window_end_ms" in divergent["issues"]


def test_pnl073_negative_trials_remain_in_append_only_registry(tmp_path) -> None:
    registry = TrialRegistry(str(tmp_path / "trials.jsonl"))
    negative = ligne_canonique(
        "negative-trial",
        config_frozen={"threshold": 1},
        verdict="KILL",
        net_bps=-12.5,
        oos="REJECTED",
        notes="negative result retained",
    )
    positive = ligne_canonique(
        "positive-trial",
        config_frozen={"threshold": 2},
        verdict="CANDIDAT",
        net_bps=3.5,
        oos="PENDING",
    )

    registry.record(negative)
    registry.record(positive)
    rows = registry.load()

    assert len(rows) == 2
    assert any(row["verdict"] == "KILL" and row["net_bps"] == -12.5 for row in rows)


def test_pnl074_top_winners_are_removed_without_dropping_losses() -> None:
    receipt = extreme_trade_robustness_receipt(
        [{"net_pnl_bps": value} for value in (30.0, 20.0, 10.0, -5.0, -2.0)],
        top_n=3,
    )

    assert receipt["status"] == "PROVEN"
    assert receipt["removed_top_n"] == 3
    assert receipt["trimmed_mean"] == -3.5


def test_pnl075_block_bootstrap_distribution_keeps_negative_tail_visible() -> None:
    distribution = metriques_distribution([10.0, -4.0, 2.0, -8.0, 1.0], es_q=0.4)

    assert distribution["n"] == 5
    assert distribution["es"] == -6.0
    assert distribution["es"] < 0


def test_pnl076_oos_retuning_revokes_promotion() -> None:
    receipt = oos_retuning_revocation_receipt(
        [
            {"episode_id": "oos-1", "used_for_tuning": False},
            {"episode_id": "oos-2", "used_for_tuning": True},
        ]
    )

    assert receipt["status"] == "REJECTED"
    assert receipt["violations"] == ["oos-2"]


def test_pnl077_gap_in_closure_run_refuses_promotion() -> None:
    report = build_closure_matrix(
        "PNL-077",
        [
            ClosureCriterion(
                "gap_free_run",
                ("local_receipt",),
                required_claims={"gap_free": True},
            )
        ],
        [
            EvidenceRecord(
                kind="local_receipt",
                source="safe://run/pnl-077",
                head_sha="0" * 40,
                evidence_status="VERIFIED",
                paper_read_only=True,
                real_execution=False,
                claims={"gap_free": False},
            )
        ],
        expected_head_sha="0" * 40,
    )

    assert report["status"] == NOT_PROVEN
    assert report["closure_allowed"] is False
    assert report["recommended_agiflow_state"] == "Testing"
    assert (
        "gap_free_run:local_receipt:CLAIM_MISMATCH:gap_free"
        in report["missing_evidence"]
    )


def test_pnl078_every_pnl_cell_has_a_unique_hash_chained_trade() -> None:
    receipt = ledger_integrity_receipt(
        [
            {"event_id": "trade-1", "record_type": "FILL", "net_pnl_usd": 0.25},
            {"event_id": "trade-2", "record_type": "FILL", "net_pnl_usd": -0.10},
        ],
        session_id="pnl-078-paper",
    )

    assert receipt["status"] == "PROVEN"
    assert receipt["event_count"] == 2
    assert receipt["unique_event_ids"] == 2
    assert receipt["hash_chained"] is True
