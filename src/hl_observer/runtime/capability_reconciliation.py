"""Fail-closed reconciliation of declared and effectively loaded capabilities.

This module is a bootstrap attestation surface, not a plugin loader.  It binds
the exact read-only connector/tool surface to a run and a full Git SHA.  A
missing required capability, an unexplained count mismatch or a failed canary
blocks readiness before research or paper execution starts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hl_observer.economics.assumptions import hash_payload

RECONCILIATION_SCHEMA = "hypersmart.capability_reconciliation.v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,159}$")


class CapabilityKind(StrEnum):
    TOOL = "TOOL"
    CONNECTOR = "CONNECTOR"
    SKILL = "SKILL"
    VENUE = "VENUE"


class CapabilityDispositionKind(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    INTENTIONALLY_DISABLED = "INTENTIONALLY_DISABLED"


class EntitlementClass(StrEnum):
    PUBLIC_ZERO_EURO = "PUBLIC_ZERO_EURO"
    LOCAL_ZERO_EURO = "LOCAL_ZERO_EURO"
    OPTIONAL_PAID = "OPTIONAL_PAID"
    USER_PROVIDED = "USER_PROVIDED"
    UNKNOWN = "UNKNOWN"


ZERO_EURO_ENTITLEMENTS = frozenset(
    {EntitlementClass.PUBLIC_ZERO_EURO, EntitlementClass.LOCAL_ZERO_EURO}
)


class CapabilityReconciliationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _identifier(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not IDENTIFIER_RE.fullmatch(text):
        raise CapabilityReconciliationError(
            "CAPABILITY_IDENTIFIER_INVALID", f"{field} invalide: {text!r}"
        )
    return text


def _nonempty(value: object, *, field: str, maximum: int = 500) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise CapabilityReconciliationError(
            "CAPABILITY_METADATA_INVALID", f"{field} vide ou trop long"
        )
    return text


@dataclass(frozen=True, slots=True)
class DeclaredCapability:
    capability_id: str
    kind: CapabilityKind
    required: bool
    expected_operations: tuple[str, ...]
    expected_schema: str
    read_only_required: bool = True
    entitlement: EntitlementClass = EntitlementClass.PUBLIC_ZERO_EURO
    license_class: str = "PUBLIC_API_TERMS"
    redistribution: str = "DERIVED_RECEIPTS_ONLY"
    preferred_authority: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.capability_id, field="capability_id")
        if not self.expected_operations:
            raise CapabilityReconciliationError(
                "CAPABILITY_OPERATIONS_EMPTY", self.capability_id
            )
        for operation in self.expected_operations:
            _identifier(operation, field="expected_operation")
        _identifier(self.expected_schema, field="expected_schema")
        _nonempty(self.license_class, field="license_class")
        _nonempty(self.redistribution, field="redistribution")
        if self.preferred_authority is not None:
            _identifier(self.preferred_authority, field="preferred_authority")

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "required": self.required,
            "expected_operations": list(self.expected_operations),
            "expected_schema": self.expected_schema,
            "read_only_required": self.read_only_required,
            "entitlement": self.entitlement.value,
            "license_class": self.license_class,
            "redistribution": self.redistribution,
            "preferred_authority": self.preferred_authority,
        }


@dataclass(frozen=True, slots=True)
class ConnectorReadinessCanary:
    manifest_schema_parses: bool
    registered: bool
    operations: tuple[str, ...]
    authorization_scope_sufficient: bool
    returned_schema: str
    semantic_canary_passed: bool
    read_only: bool

    def failures(self, declaration: DeclaredCapability) -> tuple[str, ...]:
        failures: list[str] = []
        if not self.manifest_schema_parses:
            failures.append("MANIFEST_SCHEMA_INVALID")
        if not self.registered:
            failures.append("NOT_REGISTERED")
        missing = sorted(set(declaration.expected_operations) - set(self.operations))
        if missing:
            failures.append("MISSING_OPERATIONS:" + ",".join(missing))
        if not self.authorization_scope_sufficient:
            failures.append("AUTHORIZATION_SCOPE_INSUFFICIENT")
        if self.returned_schema != declaration.expected_schema:
            failures.append("RETURNED_SCHEMA_MISMATCH")
        if not self.semantic_canary_passed:
            failures.append("SEMANTIC_CANARY_FAILED")
        if declaration.read_only_required and not self.read_only:
            failures.append("READ_ONLY_CONTRACT_FAILED")
        return tuple(failures)

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_schema_parses": self.manifest_schema_parses,
            "registered": self.registered,
            "operations": list(self.operations),
            "authorization_scope_sufficient": self.authorization_scope_sufficient,
            "returned_schema": self.returned_schema,
            "semantic_canary_passed": self.semantic_canary_passed,
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class LoadedCapability:
    capability_id: str
    kind: CapabilityKind
    canary: ConnectorReadinessCanary
    adapter_version: str
    actual_authority: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.capability_id, field="capability_id")
        _nonempty(self.adapter_version, field="adapter_version")
        if self.actual_authority is not None:
            _identifier(self.actual_authority, field="actual_authority")

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "canary": self.canary.as_dict(),
            "adapter_version": self.adapter_version,
            "actual_authority": self.actual_authority,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDisposition:
    capability_id: str
    disposition: CapabilityDispositionKind
    reason: str
    evidence_ref: str

    def __post_init__(self) -> None:
        _identifier(self.capability_id, field="capability_id")
        _nonempty(self.reason, field="reason")
        _identifier(self.evidence_ref, field="evidence_ref")

    def as_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class SourceSubstitutionReceipt:
    capability_id: str
    preferred_authority: str
    actual_authority: str
    reason: str
    evidence_ref: str

    def __post_init__(self) -> None:
        _identifier(self.capability_id, field="capability_id")
        _identifier(self.preferred_authority, field="preferred_authority")
        _identifier(self.actual_authority, field="actual_authority")
        if self.preferred_authority == self.actual_authority:
            raise CapabilityReconciliationError(
                "SOURCE_SUBSTITUTION_REDUNDANT", self.capability_id
            )
        _nonempty(self.reason, field="reason")
        _identifier(self.evidence_ref, field="evidence_ref")

    def as_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "preferred_authority": self.preferred_authority,
            "actual_authority": self.actual_authority,
            "reason": self.reason,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class CapabilityReconciliation:
    run_id: str
    state_version: str
    declared: tuple[DeclaredCapability, ...]
    loaded: tuple[LoadedCapability, ...]
    dispositions: tuple[CapabilityDisposition, ...]
    substitutions: tuple[SourceSubstitutionReceipt, ...]
    counts: Mapping[str, int]
    blocking_reasons: tuple[str, ...]
    surface_digest: str
    schema: str = RECONCILIATION_SCHEMA

    @property
    def ready(self) -> bool:
        return not self.blocking_reasons

    def require_ready(self) -> CapabilityReconciliation:
        if not self.ready:
            raise CapabilityReconciliationError(
                "CAPABILITY_SURFACE_NOT_READY", "; ".join(self.blocking_reasons)
            )
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "state_version": self.state_version,
            "declared": [item.as_dict() for item in self.declared],
            "loaded": [item.as_dict() for item in self.loaded],
            "dispositions": [item.as_dict() for item in self.dispositions],
            "substitutions": [item.as_dict() for item in self.substitutions],
            "counts": dict(self.counts),
            "blocking_reasons": list(self.blocking_reasons),
            "ready": self.ready,
            "surface_digest": self.surface_digest,
        }

    def bind_to_run_receipt(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        if str(receipt.get("run_id") or "") != self.run_id:
            raise CapabilityReconciliationError(
                "CAPABILITY_RUN_BINDING_MISMATCH", "run_id différent"
            )
        if str(receipt.get("state_version") or "").lower() != self.state_version:
            raise CapabilityReconciliationError(
                "CAPABILITY_RUN_BINDING_MISMATCH", "state_version différent"
            )
        bound = dict(receipt)
        bound["capability_surface_digest"] = self.surface_digest
        bound["capability_counts"] = dict(self.counts)
        bound["capability_ready"] = self.ready
        return bound


def _unique_by_id(items: Sequence[Any], *, category: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for item in items:
        capability_id = item.capability_id
        if capability_id in indexed:
            raise CapabilityReconciliationError(
                "CAPABILITY_DUPLICATE", f"{category}:{capability_id}"
            )
        indexed[capability_id] = item
    return indexed


def reconcile_capabilities(
    *,
    run_id: str,
    state_version: str,
    declared: Sequence[DeclaredCapability],
    loaded: Sequence[LoadedCapability],
    dispositions: Sequence[CapabilityDisposition] = (),
    substitutions: Sequence[SourceSubstitutionReceipt] = (),
) -> CapabilityReconciliation:
    """Reconcile the complete declared surface without silently filling gaps."""

    run_id = _identifier(run_id, field="run_id")
    state_version = str(state_version or "").strip().lower()
    if not SHA_RE.fullmatch(state_version):
        raise CapabilityReconciliationError(
            "CAPABILITY_STATE_VERSION_INVALID", "SHA Git complet requis"
        )

    declared_map = _unique_by_id(declared, category="declared")
    loaded_map = _unique_by_id(loaded, category="loaded")
    disposition_map = _unique_by_id(dispositions, category="disposition")
    substitution_map = _unique_by_id(substitutions, category="substitution")
    reasons: list[str] = []

    unknown_loaded = sorted(set(loaded_map) - set(declared_map))
    unknown_dispositions = sorted(set(disposition_map) - set(declared_map))
    unknown_substitutions = sorted(set(substitution_map) - set(declared_map))
    for capability_id in unknown_loaded:
        reasons.append(f"UNDECLARED_LOADED:{capability_id}")
    for capability_id in unknown_dispositions:
        reasons.append(f"UNDECLARED_DISPOSITION:{capability_id}")
    for capability_id in unknown_substitutions:
        reasons.append(f"UNDECLARED_SUBSTITUTION:{capability_id}")

    for capability_id, declaration in declared_map.items():
        loaded_item = loaded_map.get(capability_id)
        disposition = disposition_map.get(capability_id)
        if loaded_item is not None and disposition is not None:
            reasons.append(f"CAPABILITY_DOUBLE_STATE:{capability_id}")
            continue
        if loaded_item is None and disposition is None:
            reasons.append(f"CAPABILITY_MISSING:{capability_id}")
            continue
        if disposition is not None:
            if declaration.required:
                reasons.append(
                    f"REQUIRED_{disposition.disposition.value}:{capability_id}"
                )
            continue
        if loaded_item is None:
            continue
        if loaded_item.kind != declaration.kind:
            reasons.append(f"CAPABILITY_KIND_MISMATCH:{capability_id}")
        for failure in loaded_item.canary.failures(declaration):
            reasons.append(f"CANARY_{failure}:{capability_id}")
        if declaration.required and declaration.entitlement not in ZERO_EURO_ENTITLEMENTS:
            reasons.append(f"ZERO_EURO_ROUTE_MISSING:{capability_id}")

        preferred = declaration.preferred_authority
        actual = loaded_item.actual_authority
        substitution = substitution_map.get(capability_id)
        if preferred and actual and preferred != actual:
            if substitution is None:
                reasons.append(f"SILENT_SOURCE_SUBSTITUTION:{capability_id}")
            elif (
                substitution.preferred_authority != preferred
                or substitution.actual_authority != actual
            ):
                reasons.append(f"SOURCE_SUBSTITUTION_MISMATCH:{capability_id}")
        elif substitution is not None:
            reasons.append(f"UNEXPECTED_SOURCE_SUBSTITUTION:{capability_id}")

    counts = {
        "expected": len(declared_map),
        "loaded": len(loaded_map),
        "unavailable": sum(
            item.disposition == CapabilityDispositionKind.UNAVAILABLE
            for item in disposition_map.values()
        ),
        "intentionally_disabled": sum(
            item.disposition == CapabilityDispositionKind.INTENTIONALLY_DISABLED
            for item in disposition_map.values()
        ),
    }
    if counts["expected"] != (
        counts["loaded"] + counts["unavailable"] + counts["intentionally_disabled"]
    ):
        reasons.append("CAPABILITY_COUNT_MISMATCH")

    normalized_declared = tuple(sorted(declared_map.values(), key=lambda item: item.capability_id))
    normalized_loaded = tuple(sorted(loaded_map.values(), key=lambda item: item.capability_id))
    normalized_dispositions = tuple(
        sorted(disposition_map.values(), key=lambda item: item.capability_id)
    )
    normalized_substitutions = tuple(
        sorted(substitution_map.values(), key=lambda item: item.capability_id)
    )
    digest_payload = {
        "schema": RECONCILIATION_SCHEMA,
        "run_id": run_id,
        "state_version": state_version,
        "declared": [item.as_dict() for item in normalized_declared],
        "loaded": [item.as_dict() for item in normalized_loaded],
        "dispositions": [item.as_dict() for item in normalized_dispositions],
        "substitutions": [item.as_dict() for item in normalized_substitutions],
        "counts": counts,
        "blocking_reasons": sorted(set(reasons)),
    }
    return CapabilityReconciliation(
        run_id=run_id,
        state_version=state_version,
        declared=normalized_declared,
        loaded=normalized_loaded,
        dispositions=normalized_dispositions,
        substitutions=normalized_substitutions,
        counts=counts,
        blocking_reasons=tuple(sorted(set(reasons))),
        surface_digest=hash_payload(digest_payload),
    )
