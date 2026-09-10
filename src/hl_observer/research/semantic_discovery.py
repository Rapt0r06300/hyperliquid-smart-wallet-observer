"""Deterministic local semantic candidate generation for Discovery V3.2."""
from __future__ import annotations

import hashlib
import itertools
import json
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
    return payload


def _semantic_key(parts: Iterable[str]) -> str:
    joined = "\x1f".join(part.casefold().strip() for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _plan_from_values(family: str, values: tuple[str, ...]) -> dict[str, Any]:
    fields = {singular: value for (_, singular), value in zip(_COMPONENTS, values, strict=True)}
    semantic_key = _semantic_key((family, *values))
    mechanism_signature = _semantic_key(
        (family, fields["event"], fields["data_surface"], fields["target"], fields["execution"])
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
    }


def generate_semantic_plans(
    catalog: Mapping[str, Any], family: str, limit: int, seed: int
) -> list[dict[str, Any]]:
    """Generate a deterministic, exact-deduplicated local candidate pool."""
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
    axes = [_clean_values(components.get(plural), f"{family}.{plural}") for plural, _ in _COMPONENTS]

    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for values in itertools.product(*axes):
        plan = _plan_from_values(family, values)
        if plan["semantic_key"] in seen:
            continue
        seen.add(plan["semantic_key"])
        plans.append(plan)
    plans.sort(key=lambda plan: _semantic_key((str(seed), plan["semantic_key"])))
    return plans[:limit]


def _ledger_duplicate(plan: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
    semantic_key = record.get("semantic_key")
    if isinstance(semantic_key, str) and semantic_key == plan["semantic_key"]:
        return True
    mechanism = record.get("mechanism")
    return isinstance(mechanism, str) and mechanism.casefold().strip() == str(
        plan["mechanism"]
    ).casefold().strip()


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
        surface
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
        if any(_ledger_duplicate(plan, record) for record in ledger):
            continue
        effect = candidate_memory_effect(
            {
                "family": plan["family"],
                "mechanism_signature": plan["mechanism_signature"],
                "context": [plan["context"]],
                "retest_evidence": plan.get("retest_evidence", []),
            },
            process,
        )
        if effect["veto"]:
            continue
        undercoverage = 1.0 / (1.0 + surface_coverage.get(str(plan["data_surface"]), 0))
        stable_tiebreak = int(key[:8], 16) / 0xFFFFFFFF
        score = 1.0 + (0.20 * undercoverage) + effect["boost"] + (0.001 * stable_tiebreak)
        plan["priority_score"] = round(score, 6)
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
