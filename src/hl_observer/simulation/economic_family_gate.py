"""Gate économique commune aux trois familles actives HyperSmart.

La cible +4 USD est INDÉPENDANTE par famille. Une somme globale positive ne
peut jamais compenser une famille non prouvée. Ce module ne crée ni signal,
ni fill, ni ordre : il ne fait qu'agréger les preuves paper existantes.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .economic_objective import CANONICAL_FAMILIES, TARGET_NET_USD, canonical_family, evaluate_objective


def evaluate_all_families(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Évalue les 3 familles séparément et échoue fermé sur toute ambiguïté."""
    by_family: dict[str, Mapping[str, Any]] = {}
    duplicate_families: list[str] = []
    unexpected_families: list[str] = []

    for row in rows:
        family = canonical_family(row.get("family"))
        if family not in CANONICAL_FAMILIES:
            unexpected_families.append(family)
            continue
        if family in by_family:
            duplicate_families.append(family)
            continue
        by_family[family] = row

    missing_families = [family for family in CANONICAL_FAMILIES if family not in by_family]
    results = {
        family: evaluate_objective(by_family[family], target_net_usd=TARGET_NET_USD)
        for family in CANONICAL_FAMILIES
        if family in by_family
    }
    proof_net_by_family = {
        family: result.get("proof_net_pnl_usd")
        for family, result in results.items()
    }
    family_status = {
        family: result.get("objective_status")
        for family, result in results.items()
    }

    issues: list[str] = []
    issues.extend(f"MISSING_FAMILY:{family}" for family in missing_families)
    issues.extend(f"DUPLICATE_FAMILY:{family}" for family in sorted(set(duplicate_families)))
    issues.extend(f"UNEXPECTED_FAMILY:{family}" for family in sorted(set(unexpected_families)))
    for family in CANONICAL_FAMILIES:
        result = results.get(family)
        if result is not None and result.get("objective_status") != "ATTEINT":
            issues.append(f"FAMILY_TARGET_NOT_REACHED:{family}")

    display_total = sum(
        float(value) for value in proof_net_by_family.values() if value is not None
    )
    all_reached = not issues and len(results) == len(CANONICAL_FAMILIES)
    return {
        "target_net_usd_per_family": TARGET_NET_USD,
        "canonical_families": list(CANONICAL_FAMILIES),
        "family_status": family_status,
        "proof_net_by_family": proof_net_by_family,
        "display_total_proof_net_usd": round(display_total, 8),
        "global_compensation_allowed": False,
        "all_families_independently_reached": all_reached,
        "objective_status": "ATTEINT" if all_reached else "NON_ATTEINT",
        "objective_reasons": list(dict.fromkeys(issues)),
        "family_results": results,
    }


__all__ = ["evaluate_all_families"]
