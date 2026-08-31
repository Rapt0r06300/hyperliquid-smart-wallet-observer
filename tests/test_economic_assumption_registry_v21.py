from __future__ import annotations

from copy import deepcopy

import pytest

from hl_observer.config.frais_venues import hypothese_frais_taker
from hl_observer.economics.assumptions import (
    AssumptionClassification,
    CostComponentReceipt,
    EconomicConfigError,
    EconomicRunMode,
    MaturityStage,
    ZeroCostReason,
    make_assumption,
)
from hl_observer.economics.families import (
    build_copy_vault_contract,
    build_cross_venue_contract,
    build_lead_lag_contract,
)
from hl_observer.economics.proof_binding import (
    ECONOMIC_POLICY_VERSION,
    audit_cross_artifact_numeric_consistency,
    audit_economic_contract_receipt,
    audit_maturity_chain,
    build_maturity_transition,
)


def test_cross_venue_formula_dag_recalcule_tous_les_descendants() -> None:
    contract = build_cross_venue_contract(mode=EconomicRunMode.CERTIFIABLE)
    registry = contract.registry
    initial_hash = registry.snapshot_hash()
    initial_notional = registry.get("cross_venue.paper_notional_usd").value
    assert registry.get("cross_venue.round_trip_fee_bps").value == 18.0
    assert registry.get("cross_venue.minimum_entry_edge_bps").value == 30.0

    registry.replace_parent(
        make_assumption(
            assumption_id="fee.taker.hyperliquid.bps",
            name="Frais taker Hyperliquid par fill",
            value=6.0,
            unit="bps_per_fill",
            family_scope=("COPY_VAULT", "LEAD_LAG", "CROSS_VENUE"),
            classification=AssumptionClassification.CONFIGURED,
            source_ref="test:fee-mutation",
            owner="test",
            certification_eligible=True,
        )
    )
    with pytest.raises(ValueError, match="STALE_DERIVED_ECONOMIC_VALUE"):
        registry.assert_consistent()

    registry.recompute_all()
    assert registry.get("cross_venue.round_trip_fee_bps").value == 21.0
    assert registry.get("cross_venue.minimum_entry_edge_bps").value == 33.0
    assert registry.get("cross_venue.paper_notional_usd").value == initial_notional
    assert registry.snapshot_hash() != initial_hash
    assert registry.require_certifiable(contract.required_ids)["ready"] is True


def test_les_trois_familles_partagent_la_meme_autorite_de_frais() -> None:
    cross = build_cross_venue_contract(mode=EconomicRunMode.CERTIFIABLE)
    lead = build_lead_lag_contract(mode=EconomicRunMode.CERTIFIABLE)
    copy = build_copy_vault_contract(
        mode=EconomicRunMode.CERTIFIABLE,
        notional_usd=150.0,
        copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0,
        max_target_lag_ms=30_000.0,
    )

    for contract in (cross, lead, copy):
        receipt = contract.receipt()
        assert receipt["certification"]["ready"] is True
        assert len(receipt["assumption_snapshot_hash"]) == 64
    assert cross.registry.get("fee.taker.hyperliquid.bps").value == 4.5
    assert lead.registry.get("lead_lag.round_trip_fee_bps").value == 9.0
    assert copy.registry.get("copy_vault.round_trip_fee_bps").value == 9.0


def test_override_explicite_invalide_echoue_en_certifiable(monkeypatch) -> None:
    monkeypatch.setenv("HYPERSMART_FEE_HYPERLIQUID_BPS", "invalide")
    exploratory = hypothese_frais_taker("HL", mode=EconomicRunMode.EXPLORATORY)
    assert exploratory.value == 4.5
    assert exploratory.certification_eligible is False
    assert exploratory.fallback_reason == (
        "INVALID_EXPLICIT_OVERRIDE:HYPERSMART_FEE_HYPERLIQUID_BPS"
    )

    with pytest.raises(EconomicConfigError) as caught:
        hypothese_frais_taker("HL", mode=EconomicRunMode.CERTIFIABLE)
    assert caught.value.code == "UNMEASURABLE_CONFIG_INVALID"
    assert caught.value.field == "HYPERSMART_FEE_HYPERLIQUID_BPS"


def test_venue_inconnue_echoue_fermee_en_certifiable() -> None:
    with pytest.raises(EconomicConfigError, match="venue de frais inconnue"):
        hypothese_frais_taker("VENUE_INCONNUE", mode=EconomicRunMode.OOS)


def test_un_cout_zero_exige_une_raison_machine_readable() -> None:
    with pytest.raises(ValueError, match="zero_reason requis"):
        CostComponentReceipt(
            component="slippage",
            amount_usd=0.0,
            zero_reason=None,
            formula_id="test.v1",
            reality_model_version="test.v1",
            provenance_ids=("test.assumption",),
        )

    embedded = CostComponentReceipt(
        component="spread",
        amount_usd=0.0,
        zero_reason=ZeroCostReason.EMBEDDED_IN_EXECUTABLE_PRICE,
        formula_id="executable_price.v1",
        reality_model_version="test.v1",
        provenance_ids=("book.bid", "book.ask"),
    )
    missing = CostComponentReceipt(
        component="latency",
        amount_usd=0.0,
        zero_reason=ZeroCostReason.MISSING_UNMEASURABLE,
        formula_id="latency.v1",
        reality_model_version="test.v1",
        provenance_ids=("runtime.latency",),
    )
    assert embedded.certification_eligible is True
    assert missing.certification_eligible is False


def test_chaque_famille_produit_un_bundle_economique_reconstructible() -> None:
    contracts = (
        build_cross_venue_contract(mode=EconomicRunMode.CERTIFIABLE),
        build_lead_lag_contract(mode=EconomicRunMode.CERTIFIABLE),
        build_copy_vault_contract(
            mode=EconomicRunMode.CERTIFIABLE,
            notional_usd=150.0,
            copy_delay_ms=60_000.0,
            max_reference_lag_ms=30_000.0,
            max_target_lag_ms=30_000.0,
        ),
    )

    for contract in contracts:
        receipt = contract.receipt()
        audit = audit_economic_contract_receipt(
            receipt, expected_family=contract.family
        )
        assert audit["ready"] is True
        assert audit["issues"] == []
        assert receipt["policy_version"] == ECONOMIC_POLICY_VERSION
        assert receipt["economic_evidence_bundle"]["maturity_stage"] == "BUILT"
        assert set(receipt["numeric_provenance_pointers"]) == set(
            contract.required_ids
        )


def test_toute_mutation_du_bundle_ou_de_la_lineage_est_detectee() -> None:
    receipt = build_cross_venue_contract(
        mode=EconomicRunMode.CERTIFIABLE
    ).receipt()

    mutated_formula = deepcopy(receipt)
    mutated_formula["formula_manifest"][0]["expression"] = "tampered"
    assert audit_economic_contract_receipt(mutated_formula)["ready"] is False
    assert "FORMULA_SNAPSHOT_HASH_MISMATCH" in audit_economic_contract_receipt(
        mutated_formula
    )["issues"]

    mutated_pointer = deepcopy(receipt)
    key = mutated_pointer["required_assumption_ids"][0]
    mutated_pointer["numeric_provenance_pointers"][key]["terminal_value"] = -1
    pointer_audit = audit_economic_contract_receipt(mutated_pointer)
    assert pointer_audit["ready"] is False
    assert "NUMERIC_PROVENANCE_HASH_MISMATCH" in pointer_audit["issues"]

    mutated_bundle = deepcopy(receipt)
    mutated_bundle["economic_evidence_bundle"]["policy_version"] = "stale"
    bundle_audit = audit_economic_contract_receipt(mutated_bundle)
    assert bundle_audit["ready"] is False
    assert "ECONOMIC_EVIDENCE_BUNDLE_HASH_MISMATCH" in bundle_audit["issues"]


def test_maturite_ne_peut_etre_inferee_ni_sauter_une_etape() -> None:
    with pytest.raises(ValueError, match="non adjacente"):
        build_maturity_transition(
            family="COPY_VAULT",
            from_stage=MaturityStage.BUILT,
            to_stage=MaturityStage.OOS_PASS,
            evidence_refs=("audit.json#ok",),
        )

    audit_pass = build_maturity_transition(
        family="COPY_VAULT",
        from_stage=MaturityStage.BUILT,
        to_stage=MaturityStage.ECONOMIC_AUDIT_PASS,
        evidence_refs=("audit.json#ledger_valid",),
    )
    stress_pass = build_maturity_transition(
        family="COPY_VAULT",
        from_stage=MaturityStage.ECONOMIC_AUDIT_PASS,
        to_stage=MaturityStage.STRESS_PASS,
        evidence_refs=("stress.json#passed",),
        previous_transition_hash=audit_pass["transition_hash"],
    )
    result = audit_maturity_chain("copy_vault", (audit_pass, stress_pass))
    assert result["ready"] is True
    assert result["stage"] == MaturityStage.STRESS_PASS.value

    tampered = deepcopy(stress_pass)
    tampered["previous_transition_hash"] = "0" * 64
    invalid = audit_maturity_chain("copy_vault", (audit_pass, tampered))
    assert invalid["ready"] is False
    assert "MATURITY_PREVIOUS_HASH_MISMATCH:2" in invalid["issues"]


def test_consistance_numerique_inter_artefacts_resout_une_autorite_unique() -> None:
    authority = {"net_pnl_usd": 4.25, "fees_usd": 0.75}
    valid = audit_cross_artifact_numeric_consistency(
        authority_name="family_ledger",
        authority_values=authority,
        artifacts={
            "scoreboard": dict(authority),
            "evidence_bundle": dict(authority),
            "report": dict(authority),
        },
        fields=authority,
    )
    assert valid["ready"] is True

    invalid = audit_cross_artifact_numeric_consistency(
        authority_name="family_ledger",
        authority_values=authority,
        artifacts={"scoreboard": {**authority, "net_pnl_usd": 4.5}},
        fields=authority,
    )
    assert invalid["ready"] is False
    assert "ARTIFACT_VALUE_MISMATCH:scoreboard:net_pnl_usd" in invalid["issues"]
