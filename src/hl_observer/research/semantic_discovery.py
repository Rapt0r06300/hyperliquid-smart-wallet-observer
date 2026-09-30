"""Deterministic local semantic candidate generation for Discovery V3.2."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.research.hypothesis_ledger import FAMILIES
from hl_observer.research.process_memory import candidate_memory_effect

_COMPONENTS = (
    ("events", "event"),
    ("contexts", "context"),
    ("data_surfaces", "data_surface"),
    ("temporal_operators", "temporal_operator"),
    ("regimes", "regime"),
    ("targets", "target"),
    ("executions", "execution"),
)
_SEMANTIC_FIELDS = {singular for _, singular in _COMPONENTS}


def _clean_values(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non-empty list")
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name} entries must be non-empty strings")
        normalized = " ".join(item.split())
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            output.append(normalized)
    return output


def _bounded_number(value: Any, name: str, low: float, high: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return number


def _validate_optional_metadata(family: str, components: Mapping[str, Any]) -> None:
    allowed_by_field = {
        singular: {
            value.casefold()
            for value in _clean_values(components.get(plural), f"{family}.{plural}")
        }
        for plural, singular in _COMPONENTS
    }
    rules = components.get("invalid_combinations", [])
    if not isinstance(rules, list):
        raise ValueError(f"{family}.invalid_combinations must be a list")
    for rule in rules:
        if not isinstance(rule, Mapping) or not rule:
            raise ValueError(f"{family}.invalid_combinations entries must be objects")
        if not set(rule).issubset(_SEMANTIC_FIELDS):
            raise ValueError(f"{family}.invalid_combinations contains unknown fields")
        for key, value in rule.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{family}.invalid_combinations.{key} must be text")
            normalized = " ".join(value.split()).casefold()
            if normalized not in allowed_by_field[key]:
                raise ValueError(
                    f"{family}.invalid_combinations.{key} must use a declared axis value"
                )

    hints = components.get("priority_hints", {})
    if not isinstance(hints, Mapping):
        raise ValueError(f"{family}.priority_hints must be an object")
    bounds = {
        "data_feasibility": (0.0, 1.0),
        "falsification_cost": (0.0, 1.0),
        "executable_headroom": (-1.0, 1.0),
    }
    for name, (low, high) in bounds.items():
        values = hints.get(name, {})
        if not isinstance(values, Mapping):
            raise ValueError(f"{family}.priority_hints.{name} must be an object")
        for key, value in values.items():
            _bounded_number(value, f"{family}.priority_hints.{name}.{key}", low, high)


def load_catalog(path: str | Path) -> dict[str, Any]:
    """Load and structurally validate the versioned semantic component catalog."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("families"), dict):
        raise ValueError("catalog must contain a families object")
    for family, components in payload["families"].items():
        if family not in FAMILIES:
            raise ValueError(f"unknown family in catalog: {family}")
        if not isinstance(components, dict):
            raise ValueError(f"catalog family {family} must be an object")
        for plural, _ in _COMPONENTS:
            _clean_values(components.get(plural), f"{family}.{plural}")
        _validate_optional_metadata(family, components)
    return payload


def _semantic_key(parts: Iterable[str]) -> str:
    joined = "\x1f".join(part.casefold().strip() for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _hint(
    components: Mapping[str, Any], group: str, key: str, default: float
) -> float:
    hints = components.get("priority_hints", {})
    if not isinstance(hints, Mapping):
        return default
    values = hints.get(group, {})
    if not isinstance(values, Mapping):
        return default
    value = values.get(key, default)
    bounds = (-1.0, 1.0) if group == "executable_headroom" else (0.0, 1.0)
    try:
        return _bounded_number(value, f"priority_hints.{group}.{key}", *bounds)
    except ValueError:
        return default


def _plan_from_values(
    family: str, values: tuple[str, ...], components: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {
        singular: value
        for (_, singular), value in zip(_COMPONENTS, values, strict=True)
    }
    semantic_key = _semantic_key((family, *values))
    mechanism_signature = _semantic_key(
        (
            family,
            fields["event"],
            fields["data_surface"],
            fields["target"],
            fields["execution"],
        )
    )
    mechanism = (
        f"{fields['event']} on {fields['data_surface']} predicts {fields['target']} "
        f"via {fields['temporal_operator']}"
    )
    return {
        "family": family,
        **fields,
        "mechanism": mechanism,
        "mechanism_signature": mechanism_signature,
        "semantic_key": semantic_key,
        "archetype_key": _semantic_key(
            (family, fields["event"], fields["data_surface"], fields["temporal_operator"])
        ),
        "data_feasibility": _hint(
            components, "data_feasibility", fields["data_surface"], 0.5
        ),
        "falsification_cost": _hint(
            components, "falsification_cost", fields["event"], 0.5
        ),
        "executable_headroom_hint": _hint(
            components, "executable_headroom", fields["execution"], 0.0
        ),
    }


def _matches_invalid_rule(plan: Mapping[str, Any], rule: Mapping[str, Any]) -> bool:
    return all(
        str(plan.get(key, "")).casefold() == str(value).casefold()
        for key, value in rule.items()
    )


def generate_semantic_plans(
    catalog: Mapping[str, Any], family: str, limit: int, seed: int
) -> list[dict[str, Any]]:
    """Generate a deterministic, validated and exact-deduplicated local pool."""
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {sorted(FAMILIES)}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    families = catalog.get("families")
    if not isinstance(families, Mapping) or family not in families:
        raise ValueError(f"catalog does not define family {family}")
    components = families[family]
    if not isinstance(components, Mapping):
        raise ValueError(f"catalog family {family} must be an object")
    _validate_optional_metadata(family, components)
    axes = [
        _clean_values(components.get(plural), f"{family}.{plural}")
        for plural, _ in _COMPONENTS
    ]
    rules = components.get("invalid_combinations", [])

    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for values in itertools.product(*axes):
        plan = _plan_from_values(family, values, components)
        if any(_matches_invalid_rule(plan, rule) for rule in rules):
            continue
        if plan["semantic_key"] in seen:
            continue
        seen.add(plan["semantic_key"])
        plans.append(plan)
    plans.sort(key=lambda plan: _semantic_key((str(seed), plan["semantic_key"])))
    return plans[:limit]


def _casefold_list(value: Any) -> set[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray, Mapping)):
        return set()
    return {
        str(item).casefold().strip()
        for item in value
        if isinstance(item, str) and item.strip()
    }


def _semantic_mismatch_fields(
    plan: Mapping[str, Any], record: Mapping[str, Any]
) -> set[str]:
    if record.get("family") != plan.get("family"):
        return set(_SEMANTIC_FIELDS)
    mechanism = str(record.get("mechanism") or "").casefold()
    surfaces = _casefold_list(record.get("data_surfaces", []))
    conditioning = _casefold_list(record.get("conditioning", []))
    mismatches: set[str] = set()
    if str(plan["event"]).casefold() not in mechanism:
        mismatches.add("event")
    if str(plan["data_surface"]).casefold() not in surfaces:
        mismatches.add("data_surface")
    if str(plan["temporal_operator"]).casefold() != str(
        record.get("temporal_operator") or ""
    ).casefold():
        mismatches.add("temporal_operator")
    if str(plan["context"]).casefold() not in conditioning:
        mismatches.add("context")
    if str(plan["regime"]).casefold() not in conditioning:
        mismatches.add("regime")
    if str(plan["target"]).casefold() != str(
        record.get("prediction_target") or ""
    ).casefold():
        mismatches.add("target")
    if str(plan["execution"]).casefold() != str(
        record.get("execution_translation") or ""
    ).casefold():
        mismatches.add("execution")
    return mismatches


def _semantic_distance_to_ledger(
    plan: Mapping[str, Any], record: Mapping[str, Any]
) -> float:
    return len(_semantic_mismatch_fields(plan, record)) / len(_COMPONENTS)


def _novelty(plan: Mapping[str, Any], ledger: list[Mapping[str, Any]]) -> float:
    same_family = [item for item in ledger if item.get("family") == plan.get("family")]
    if not same_family:
        return 1.0
    return min(_semantic_distance_to_ledger(plan, item) for item in same_family)


def _is_parameter_only_duplicate(
    plan: Mapping[str, Any], ledger: list[Mapping[str, Any]]
) -> bool:
    for record in ledger:
        if record.get("family") != plan.get("family"):
            continue
        mismatches = _semantic_mismatch_fields(plan, record)
        if not mismatches or mismatches <= {"temporal_operator"}:
            return True
    return False


def rank_semantic_plans(
    plans: Iterable[Mapping[str, Any]],
    ledger_records: Iterable[Mapping[str, Any]],
    process_records: Iterable[Mapping[str, Any]],
    shortlist: int,
) -> list[dict[str, Any]]:
    """Filter, score and greedily diversify a deterministic research shortlist."""
    if not isinstance(shortlist, int) or isinstance(shortlist, bool) or shortlist <= 0:
        raise ValueError("shortlist must be a positive integer")
    ledger = list(ledger_records)
    process = list(process_records)
    surface_coverage = Counter(
        surface.casefold()
        for record in ledger
        for surface in record.get("data_surfaces", [])
        if isinstance(surface, str)
    )

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in plans:
        plan = dict(raw)
        key = plan.get("semantic_key")
        if not isinstance(key, str) or key in seen:
            continue
        seen.add(key)

        if _is_parameter_only_duplicate(plan, ledger):
            continue
        novelty = _novelty(plan, ledger)
        effect = candidate_memory_effect(
            {
                "family": plan["family"],
                "mechanism_signature": plan["mechanism_signature"],
                "context": [plan["context"], plan["regime"]],
                "retest_evidence": plan.get("retest_evidence", []),
            },
            process,
        )
        if effect["veto"]:
            continue

        surface = str(plan["data_surface"]).casefold()
        undercoverage = 1.0 / (1.0 + surface_coverage.get(surface, 0))
        feasibility = float(plan.get("data_feasibility", 0.5))
        cost_efficiency = 1.0 - float(plan.get("falsification_cost", 0.5))
        headroom = (float(plan.get("executable_headroom_hint", 0.0)) + 1.0) / 2.0
        components = {
            "novelty": round(novelty, 6),
            "undercoverage": round(undercoverage, 6),
            "data_feasibility": round(feasibility, 6),
            "falsification_efficiency": round(cost_efficiency, 6),
            "headroom_hint": round(headroom, 6),
            "memory_boost": effect["boost"],
        }
        score = (
            0.35 * novelty
            + 0.20 * undercoverage
            + 0.20 * feasibility
            + 0.15 * cost_efficiency
            + 0.10 * headroom
            + effect["boost"]
        )
        stable_tiebreak = int(key[:8], 16) / 0xFFFFFFFF
        plan["priority_components"] = components
        plan["priority_score"] = round(score + (0.000001 * stable_tiebreak), 6)
        plan["memory_boost"] = effect["boost"]
        plan["memory_matches"] = effect["matching_records"]
        candidates.append(plan)

    candidates.sort(key=lambda item: (-item["priority_score"], item["semantic_key"]))
    selected: list[dict[str, Any]] = []
    used_archetypes: set[str] = set()
    for candidate in candidates:
        if candidate["archetype_key"] in used_archetypes:
            continue
        selected.append(candidate)
        used_archetypes.add(candidate["archetype_key"])
        if len(selected) >= shortlist:
            return selected
    for candidate in candidates:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) >= shortlist:
            break
    return selected


__all__ = ["generate_semantic_plans", "load_catalog", "rank_semantic_plans"]
