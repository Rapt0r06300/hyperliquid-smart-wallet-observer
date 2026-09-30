"""Copy-Vault universe/survivorship integrity gate.

Family-local, deterministic and PAPER/READ-ONLY. The gate reuses canonical
wallet-integrity primitives and fails closed when the declared research universe
or entity normalization evidence is incomplete.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.research.wallet_integrity import (
    correction_survivorship,
    detecter_sybils,
    inclure_wallets_liquides,
)

SCHEMA_VERSION = "hypersmart.copy_vault_universe_integrity.v1"


def _wallet(value: object) -> str:
    return str(value or "").strip().lower()


def evaluate_copy_vault_universe_integrity(
    *,
    complete_universe: Sequence[str],
    observed_survivors: Sequence[str],
    cohort: Sequence[Mapping[str, Any]],
    correlations: Mapping[tuple[str, str], float],
    entity_groups: Mapping[str, str],
) -> dict[str, Any]:
    """Return fail-closed Copy-Vault universe and entity-integrity evidence."""

    universe = sorted({_wallet(wallet) for wallet in complete_universe if _wallet(wallet)})
    survivors = sorted({_wallet(wallet) for wallet in observed_survivors if _wallet(wallet)})
    cohort_rows = [dict(row) for row in cohort if _wallet(row.get("wallet"))]
    cohort_wallets = sorted({_wallet(row.get("wallet")) for row in cohort_rows})
    groups = {
        _wallet(wallet): str(group or "").strip()
        for wallet, group in entity_groups.items()
        if _wallet(wallet)
    }
    normalized_correlations: dict[tuple[str, str], float] = {}
    invalid_correlation_evidence = False
    for pair, value in correlations.items():
        try:
            left, right = pair
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            invalid_correlation_evidence = True
            continue
        left_wallet = _wallet(left)
        right_wallet = _wallet(right)
        if not left_wallet or not right_wallet:
            invalid_correlation_evidence = True
            continue
        normalized_correlations[(left_wallet, right_wallet)] = numeric

    reasons: list[str] = []
    if invalid_correlation_evidence:
        reasons.append("CORRELATION_EVIDENCE_INVALID")
    if not universe:
        reasons.append("UNIVERSE_NOT_DECLARED")

    universe_set = set(universe)
    survivor_set = set(survivors)
    cohort_set = set(cohort_wallets)
    outside = sorted(survivor_set - universe_set)
    missing_from_cohort = sorted(universe_set - cohort_set)
    if outside:
        reasons.append("SURVIVOR_OUTSIDE_UNIVERSE")
    if missing_from_cohort:
        reasons.append("COHORT_COVERAGE_INCOMPLETE")

    survivorship = correction_survivorship(universe, survivors)
    liquidation_evidence = inclure_wallets_liquides(cohort_rows)
    if liquidation_evidence.get("cohorte_suspecte") is True:
        reasons.append("LIQUIDATED_WALLET_COVERAGE_UNPROVEN")
    sybils = detecter_sybils(normalized_correlations)
    unresolved_sybil_pairs: list[tuple[str, str]] = []
    for left, right in sybils["sybils_suspects"]:
        left_group = groups.get(left, "")
        right_group = groups.get(right, "")
        if not left_group or not right_group or left_group != right_group:
            unresolved_sybil_pairs.append((left, right))
    if unresolved_sybil_pairs:
        reasons.append("SYBIL_ENTITY_NORMALIZATION_MISSING")

    return {
        "schema_version": SCHEMA_VERSION,
        "eligible": not reasons,
        "reasons": reasons,
        "complete_universe": universe,
        "observed_survivors": survivors,
        "cohort_wallets": cohort_wallets,
        "survivors_outside_universe": outside,
        "missing_from_cohort": missing_from_cohort,
        "survivorship": survivorship,
        "cohort_liquidation_evidence": liquidation_evidence,
        "sybil_detection": sybils,
        "unresolved_sybil_pairs": unresolved_sybil_pairs,
        "entity_normalization_proven": not unresolved_sybil_pairs,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "evaluate_copy_vault_universe_integrity"]
