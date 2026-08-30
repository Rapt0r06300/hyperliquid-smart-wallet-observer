"""Canonical provenance and dependency lineage for economic numbers.

The registry is deliberately pure: no network, exchange client, key or signing
surface.  It records what a paper/replay run believed, why it believed it and
which formula produced every derived value.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

JsonScalar = str | int | float | bool | None
FormulaEvaluator = Callable[[Mapping[str, JsonScalar]], JsonScalar]


class AssumptionClassification(StrEnum):
    OBSERVED = "OBSERVED"
    CONFIGURED = "CONFIGURED"
    ASSUMPTION = "ASSUMPTION"
    CONSERVATIVE_DEFAULT = "CONSERVATIVE_DEFAULT"
    STRESS = "STRESS"
    DERIVED = "DERIVED"


class EconomicRunMode(StrEnum):
    EXPLORATORY = "EXPLORATORY"
    CERTIFIABLE = "CERTIFIABLE"
    OOS = "OOS"
    FORWARD = "FORWARD"
    PROMOTION = "PROMOTION"


class ZeroCostReason(StrEnum):
    EMBEDDED_IN_EXECUTABLE_PRICE = "EMBEDDED_IN_EXECUTABLE_PRICE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MEASURED_ZERO = "MEASURED_ZERO"
    BELOW_RESOLUTION = "BELOW_RESOLUTION"
    MISSING_UNMEASURABLE = "MISSING_UNMEASURABLE"


class MaturityStage(StrEnum):
    BUILT = "BUILT"
    ECONOMIC_AUDIT_PASS = "ECONOMIC_AUDIT_PASS"
    STRESS_PASS = "STRESS_PASS"
    OOS_PASS = "OOS_PASS"
    FORWARD_PASS = "FORWARD_PASS"
    GUARDIAN_PROMOTABLE = "GUARDIAN_PROMOTABLE"


CERTIFIABLE_MODES = frozenset(
    {
        EconomicRunMode.CERTIFIABLE,
        EconomicRunMode.OOS,
        EconomicRunMode.FORWARD,
        EconomicRunMode.PROMOTION,
    }
)


def is_certifiable_mode(mode: EconomicRunMode | str) -> bool:
    try:
        parsed = EconomicRunMode(str(mode).strip().upper())
    except ValueError as exc:
        raise ValueError(f"mode economique inconnu: {mode!r}") from exc
    return parsed in CERTIFIABLE_MODES


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"type non serialisable dans le registre economique: {type(value)!r}")


def hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EconomicConfigError(ValueError):
    """Fail-closed configuration error with a machine-readable reason."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "UNMEASURABLE_CONFIG_INVALID",
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "field": self.field, "message": str(self)}


@dataclass(frozen=True, slots=True)
class EconomicAssumption:
    assumption_id: str
    name: str
    value: JsonScalar
    unit: str
    family_scope: tuple[str, ...]
    classification: AssumptionClassification
    source_ref: str
    source_hash: str
    observed_at: str | None
    effective_from: str | None
    valid_until: str | None
    revalidate_after: str | None
    owner: str
    formula_id: str | None = None
    fallback_reason: str | None = None
    certification_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.assumption_id or len(self.assumption_id) > 160:
            raise ValueError("assumption_id vide ou trop long")
        if not self.name or not self.unit or not self.family_scope or not self.owner:
            raise ValueError(f"hypothese economique incomplete: {self.assumption_id}")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(f"valeur non finie: {self.assumption_id}")
        if len(self.source_hash) != 64 or any(c not in "0123456789abcdef" for c in self.source_hash):
            raise ValueError(f"source_hash invalide: {self.assumption_id}")
        if self.classification is AssumptionClassification.OBSERVED and not self.observed_at:
            raise ValueError(f"observed_at requis: {self.assumption_id}")
        if self.classification is AssumptionClassification.DERIVED and not self.formula_id:
            raise ValueError(f"formula_id requis: {self.assumption_id}")
        if (
            self.classification is AssumptionClassification.CONSERVATIVE_DEFAULT
            and not self.fallback_reason
        ):
            raise ValueError(f"fallback_reason requis: {self.assumption_id}")
        if self.certification_eligible and not self.source_ref:
            raise ValueError(f"source_ref requis pour certification: {self.assumption_id}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "family_scope": list(self.family_scope),
            "classification": self.classification.value,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "observed_at": self.observed_at,
            "effective_from": self.effective_from,
            "valid_until": self.valid_until,
            "revalidate_after": self.revalidate_after,
            "owner": self.owner,
            "formula_id": self.formula_id,
            "fallback_reason": self.fallback_reason,
            "certification_eligible": self.certification_eligible,
        }


def make_assumption(
    *,
    assumption_id: str,
    name: str,
    value: JsonScalar,
    unit: str,
    family_scope: Sequence[str],
    classification: AssumptionClassification,
    source_ref: str,
    observed_at: str | None = None,
    effective_from: str | None = None,
    valid_until: str | None = None,
    revalidate_after: str | None = None,
    owner: str = "HyperSmart",
    formula_id: str | None = None,
    fallback_reason: str | None = None,
    certification_eligible: bool = False,
    source_hash: str | None = None,
) -> EconomicAssumption:
    canonical_source = {
        "source_ref": source_ref,
        "value": value,
        "unit": unit,
        "classification": classification.value,
        "observed_at": observed_at,
        "effective_from": effective_from,
    }
    return EconomicAssumption(
        assumption_id=assumption_id,
        name=name,
        value=value,
        unit=unit,
        family_scope=tuple(sorted({str(item) for item in family_scope if str(item)})),
        classification=classification,
        source_ref=source_ref,
        source_hash=source_hash or hash_payload(canonical_source),
        observed_at=observed_at,
        effective_from=effective_from,
        valid_until=valid_until,
        revalidate_after=revalidate_after,
        owner=owner,
        formula_id=formula_id,
        fallback_reason=fallback_reason,
        certification_eligible=bool(certification_eligible),
    )


@dataclass(frozen=True, slots=True)
class FormulaDefinition:
    formula_id: str
    output_assumption_id: str
    parent_ids: tuple[str, ...]
    expression: str
    unit: str
    version: str
    reality_model_version: str

    def __post_init__(self) -> None:
        if not self.formula_id or not self.output_assumption_id or not self.parent_ids:
            raise ValueError("formule economique incomplete")
        if self.output_assumption_id in self.parent_ids:
            raise ValueError(f"auto-dependance interdite: {self.formula_id}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "output_assumption_id": self.output_assumption_id,
            "parent_ids": list(self.parent_ids),
            "expression": self.expression,
            "unit": self.unit,
            "version": self.version,
            "reality_model_version": self.reality_model_version,
        }


@dataclass(frozen=True, slots=True)
class CostComponentReceipt:
    component: str
    amount_usd: float
    zero_reason: ZeroCostReason | None
    formula_id: str
    reality_model_version: str
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.amount_usd) or self.amount_usd < 0:
            raise ValueError(f"cout invalide: {self.component}")
        if self.amount_usd == 0.0 and self.zero_reason is None:
            raise ValueError(f"zero_reason requis: {self.component}")
        if self.amount_usd != 0.0 and self.zero_reason is not None:
            raise ValueError(f"zero_reason interdit pour un cout non nul: {self.component}")

    @property
    def certification_eligible(self) -> bool:
        return self.zero_reason is not ZeroCostReason.MISSING_UNMEASURABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "amount_usd": self.amount_usd,
            "zero_reason": self.zero_reason.value if self.zero_reason is not None else None,
            "formula_id": self.formula_id,
            "reality_model_version": self.reality_model_version,
            "provenance_ids": list(self.provenance_ids),
            "certification_eligible": self.certification_eligible,
        }


class EconomicAssumptionRegistry:
    """In-memory formula DAG whose snapshot is deterministic and auditable."""

    def __init__(self) -> None:
        self._assumptions: dict[str, EconomicAssumption] = {}
        self._formulas: dict[str, FormulaDefinition] = {}
        self._evaluators: dict[str, FormulaEvaluator] = {}

    def register(self, assumption: EconomicAssumption) -> EconomicAssumption:
        previous = self._assumptions.get(assumption.assumption_id)
        if previous is not None and previous != assumption:
            raise ValueError(f"hypothese deja declaree: {assumption.assumption_id}")
        self._assumptions[assumption.assumption_id] = assumption
        return assumption

    def replace_parent(self, assumption: EconomicAssumption) -> None:
        previous = self._assumptions.get(assumption.assumption_id)
        if previous is None:
            raise KeyError(assumption.assumption_id)
        if previous.classification is AssumptionClassification.DERIVED:
            raise ValueError("une valeur derivee se remplace par recompute_all()")
        self._assumptions[assumption.assumption_id] = assumption

    def register_formula(
        self,
        definition: FormulaDefinition,
        evaluator: FormulaEvaluator,
        *,
        name: str,
        family_scope: Sequence[str],
        owner: str = "HyperSmart",
        certification_eligible: bool = True,
    ) -> EconomicAssumption:
        previous = self._formulas.get(definition.formula_id)
        if previous is not None and previous != definition:
            raise ValueError(f"formule deja declaree: {definition.formula_id}")
        missing = [parent for parent in definition.parent_ids if parent not in self._assumptions]
        if missing:
            raise KeyError(f"parents manquants pour {definition.formula_id}: {missing}")
        self._formulas[definition.formula_id] = definition
        self._evaluators[definition.formula_id] = evaluator
        return self._evaluate_and_store(
            definition,
            name=name,
            family_scope=family_scope,
            owner=owner,
            certification_eligible=certification_eligible,
        )

    def _evaluate_and_store(
        self,
        definition: FormulaDefinition,
        *,
        name: str | None = None,
        family_scope: Sequence[str] | None = None,
        owner: str | None = None,
        certification_eligible: bool | None = None,
    ) -> EconomicAssumption:
        parents = {parent: self._assumptions[parent].value for parent in definition.parent_ids}
        value = self._evaluators[definition.formula_id](parents)
        previous = self._assumptions.get(definition.output_assumption_id)
        eligible = (
            all(self._assumptions[parent].certification_eligible for parent in definition.parent_ids)
            if certification_eligible is None
            else bool(certification_eligible)
            and all(self._assumptions[parent].certification_eligible for parent in definition.parent_ids)
        )
        material = {
            "formula": definition.as_dict(),
            "parents": {
                parent: self._assumptions[parent].as_dict() for parent in definition.parent_ids
            },
            "value": value,
        }
        derived = make_assumption(
            assumption_id=definition.output_assumption_id,
            name=name or (previous.name if previous else definition.output_assumption_id),
            value=value,
            unit=definition.unit,
            family_scope=family_scope or (previous.family_scope if previous else ("GLOBAL",)),
            classification=AssumptionClassification.DERIVED,
            source_ref=f"formula:{definition.formula_id}@{definition.version}",
            source_hash=hash_payload(material),
            owner=owner or (previous.owner if previous else "HyperSmart"),
            formula_id=definition.formula_id,
            certification_eligible=eligible,
        )
        self._assumptions[derived.assumption_id] = derived
        return derived

    def recompute_all(self) -> None:
        pending = dict(self._formulas)
        done: set[str] = set()
        while pending:
            progressed = False
            for formula_id, definition in tuple(pending.items()):
                parent_formulas = {
                    self._assumptions[parent].formula_id
                    for parent in definition.parent_ids
                    if self._assumptions[parent].classification is AssumptionClassification.DERIVED
                }
                if any(parent_formula not in done for parent_formula in parent_formulas):
                    continue
                self._evaluate_and_store(definition)
                done.add(formula_id)
                pending.pop(formula_id)
                progressed = True
            if not progressed:
                raise ValueError(f"cycle de formules economiques: {sorted(pending)}")

    def assert_consistent(self) -> None:
        for formula_id, definition in self._formulas.items():
            parents = {parent: self._assumptions[parent].value for parent in definition.parent_ids}
            expected = self._evaluators[formula_id](parents)
            actual = self._assumptions[definition.output_assumption_id]
            if actual.formula_id != formula_id:
                raise ValueError(f"lineage de formule incoherente: {definition.output_assumption_id}")
            if isinstance(expected, (int, float)) and isinstance(actual.value, (int, float)):
                equal = math.isclose(float(expected), float(actual.value), abs_tol=1e-12)
            else:
                equal = expected == actual.value
            if not equal:
                raise ValueError(
                    f"STALE_DERIVED_ECONOMIC_VALUE:{definition.output_assumption_id}:"
                    f"expected={expected!r}:actual={actual.value!r}"
                )

    def get(self, assumption_id: str) -> EconomicAssumption:
        try:
            return self._assumptions[assumption_id]
        except KeyError as exc:
            raise KeyError(f"hypothese economique inconnue: {assumption_id}") from exc

    def provenance_chain(self, assumption_id: str) -> tuple[str, ...]:
        ordered: list[str] = []
        visiting: set[str] = set()

        def walk(current: str) -> None:
            if current in visiting:
                raise ValueError(f"cycle de provenance: {current}")
            visiting.add(current)
            assumption = self.get(current)
            if assumption.formula_id:
                definition = self._formulas[assumption.formula_id]
                for parent in definition.parent_ids:
                    walk(parent)
            if current not in ordered:
                ordered.append(current)
            visiting.remove(current)

        walk(assumption_id)
        return tuple(ordered)

    def snapshot(self) -> dict[str, Any]:
        self.assert_consistent()
        return {
            "schema": "hypersmart.economic_assumption_snapshot.v1",
            "assumptions": [
                self._assumptions[key].as_dict() for key in sorted(self._assumptions)
            ],
            "formulas": [self._formulas[key].as_dict() for key in sorted(self._formulas)],
        }

    def snapshot_hash(self) -> str:
        return hash_payload(self.snapshot())

    def certification_receipt(self, required_ids: Iterable[str]) -> dict[str, Any]:
        required = tuple(sorted(set(required_ids)))
        failures: list[dict[str, str]] = []
        for assumption_id in required:
            assumption = self._assumptions.get(assumption_id)
            if assumption is None:
                failures.append({"assumption_id": assumption_id, "reason": "MISSING_ASSUMPTION"})
            elif not assumption.certification_eligible:
                failures.append(
                    {"assumption_id": assumption_id, "reason": "NOT_CERTIFICATION_ELIGIBLE"}
                )
        try:
            self.assert_consistent()
        except ValueError as exc:
            failures.append({"assumption_id": "*", "reason": str(exc)})
        return {
            "schema": "hypersmart.economic_certification_receipt.v1",
            "ready": not failures,
            "required_ids": list(required),
            "failures": failures,
            "assumption_snapshot_hash": self.snapshot_hash() if not failures else None,
        }

    def require_certifiable(self, required_ids: Iterable[str]) -> dict[str, Any]:
        receipt = self.certification_receipt(required_ids)
        if not receipt["ready"]:
            raise EconomicConfigError(
                f"hypotheses economiques non certifiables: {receipt['failures']}",
                code="UNMEASURABLE_ASSUMPTION_PROVENANCE",
            )
        return receipt


__all__ = [
    "AssumptionClassification",
    "CERTIFIABLE_MODES",
    "CostComponentReceipt",
    "EconomicAssumption",
    "EconomicAssumptionRegistry",
    "EconomicConfigError",
    "EconomicRunMode",
    "FormulaDefinition",
    "MaturityStage",
    "ZeroCostReason",
    "hash_payload",
    "is_certifiable_mode",
    "make_assumption",
]
