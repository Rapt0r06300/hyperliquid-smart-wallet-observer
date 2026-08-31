from __future__ import annotations

import pytest

from hl_observer.runtime.capability_reconciliation import (
    CapabilityDisposition,
    CapabilityDispositionKind,
    CapabilityKind,
    CapabilityReconciliationError,
    ConnectorReadinessCanary,
    DeclaredCapability,
    EntitlementClass,
    LoadedCapability,
    SourceSubstitutionReceipt,
    reconcile_capabilities,
)

SHA = "a" * 40


def _declared(
    capability_id: str = "connector:hyperliquid-info",
    *,
    required: bool = True,
    entitlement: EntitlementClass = EntitlementClass.PUBLIC_ZERO_EURO,
    preferred_authority: str = "hyperliquid",
) -> DeclaredCapability:
    return DeclaredCapability(
        capability_id=capability_id,
        kind=CapabilityKind.CONNECTOR,
        required=required,
        expected_operations=("allMids",),
        expected_schema="hypersmart.all_mids.v1",
        entitlement=entitlement,
        preferred_authority=preferred_authority,
    )


def _loaded(
    capability_id: str = "connector:hyperliquid-info",
    *,
    actual_authority: str = "hyperliquid",
    semantic_canary_passed: bool = True,
) -> LoadedCapability:
    return LoadedCapability(
        capability_id=capability_id,
        kind=CapabilityKind.CONNECTOR,
        adapter_version="official-info.v3",
        actual_authority=actual_authority,
        canary=ConnectorReadinessCanary(
            manifest_schema_parses=True,
            registered=True,
            operations=("allMids",),
            authorization_scope_sufficient=True,
            returned_schema="hypersmart.all_mids.v1",
            semantic_canary_passed=semantic_canary_passed,
            read_only=True,
        ),
    )


def test_reconciliation_positive_is_deterministic_and_binds_run_receipt():
    first = reconcile_capabilities(
        run_id="run-capabilities-1",
        state_version=SHA,
        declared=[_declared()],
        loaded=[_loaded()],
    )
    second = reconcile_capabilities(
        run_id="run-capabilities-1",
        state_version=SHA,
        declared=[_declared()],
        loaded=[_loaded()],
    )
    assert first.require_ready().surface_digest == second.surface_digest
    assert first.counts == {
        "expected": 1,
        "loaded": 1,
        "unavailable": 0,
        "intentionally_disabled": 0,
    }
    bound = first.bind_to_run_receipt(
        {"run_id": "run-capabilities-1", "state_version": SHA, "paper": True}
    )
    assert bound["capability_surface_digest"] == first.surface_digest
    assert bound["capability_ready"] is True


def test_required_missing_and_failed_semantic_canary_block_readiness():
    missing = reconcile_capabilities(
        run_id="missing",
        state_version=SHA,
        declared=[_declared()],
        loaded=[],
    )
    assert "CAPABILITY_MISSING:connector:hyperliquid-info" in missing.blocking_reasons
    assert "CAPABILITY_COUNT_MISMATCH" in missing.blocking_reasons
    with pytest.raises(CapabilityReconciliationError, match="CAPABILITY_SURFACE_NOT_READY"):
        missing.require_ready()

    failed = reconcile_capabilities(
        run_id="bad-canary",
        state_version=SHA,
        declared=[_declared()],
        loaded=[_loaded(semantic_canary_passed=False)],
    )
    assert any("SEMANTIC_CANARY_FAILED" in reason for reason in failed.blocking_reasons)


def test_undeclared_loaded_and_paid_required_route_block():
    receipt = reconcile_capabilities(
        run_id="undeclared",
        state_version=SHA,
        declared=[_declared(entitlement=EntitlementClass.OPTIONAL_PAID)],
        loaded=[_loaded(), _loaded("connector:surprise")],
    )
    assert "UNDECLARED_LOADED:connector:surprise" in receipt.blocking_reasons
    assert "ZERO_EURO_ROUTE_MISSING:connector:hyperliquid-info" in receipt.blocking_reasons


def test_optional_disabled_needs_explicit_reason_and_is_counted():
    optional = _declared("connector:optional", required=False)
    disposition = CapabilityDisposition(
        capability_id=optional.capability_id,
        disposition=CapabilityDispositionKind.INTENTIONALLY_DISABLED,
        reason="réseau explicitement désactivé pour le replay local",
        evidence_ref="bootstrap:offline-policy",
    )
    receipt = reconcile_capabilities(
        run_id="optional-disabled",
        state_version=SHA,
        declared=[optional],
        loaded=[],
        dispositions=[disposition],
    )
    assert receipt.ready is True
    assert receipt.counts["intentionally_disabled"] == 1
    with pytest.raises(CapabilityReconciliationError, match="CAPABILITY_METADATA_INVALID"):
        CapabilityDisposition(
            capability_id=optional.capability_id,
            disposition=CapabilityDispositionKind.INTENTIONALLY_DISABLED,
            reason="",
            evidence_ref="bootstrap:offline-policy",
        )


def test_source_substitution_must_be_explicit_and_exact():
    declaration = _declared(preferred_authority="hyperliquid")
    fallback = _loaded(actual_authority="local-cache")
    silent = reconcile_capabilities(
        run_id="silent-fallback",
        state_version=SHA,
        declared=[declaration],
        loaded=[fallback],
    )
    assert "SILENT_SOURCE_SUBSTITUTION:connector:hyperliquid-info" in silent.blocking_reasons

    explicit = reconcile_capabilities(
        run_id="explicit-fallback",
        state_version=SHA,
        declared=[declaration],
        loaded=[fallback],
        substitutions=[
            SourceSubstitutionReceipt(
                capability_id=declaration.capability_id,
                preferred_authority="hyperliquid",
                actual_authority="local-cache",
                reason="replay hors ligne lié au snapshot canonique",
                evidence_ref="dataset:sha256-deadbeef",
            )
        ],
    )
    assert explicit.ready is True


def test_digest_changes_when_loaded_adapter_changes_and_binding_is_strict():
    first = reconcile_capabilities(
        run_id="run-versioned",
        state_version=SHA,
        declared=[_declared()],
        loaded=[_loaded()],
    )
    changed = LoadedCapability(
        capability_id=_loaded().capability_id,
        kind=_loaded().kind,
        canary=_loaded().canary,
        adapter_version="official-info.v4",
        actual_authority="hyperliquid",
    )
    second = reconcile_capabilities(
        run_id="run-versioned",
        state_version=SHA,
        declared=[_declared()],
        loaded=[changed],
    )
    assert first.surface_digest != second.surface_digest
    with pytest.raises(CapabilityReconciliationError, match="CAPABILITY_RUN_BINDING_MISMATCH"):
        first.bind_to_run_receipt({"run_id": "other", "state_version": SHA})
