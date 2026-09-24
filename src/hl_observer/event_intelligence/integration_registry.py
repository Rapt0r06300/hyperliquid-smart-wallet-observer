"""Canonical 120-idea bindings to Alina research modules and Dataset V2.

This registry is structural evidence only.  It deliberately cannot promote a
strategy, authorize an order, or claim positive PnL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from hl_observer.event_intelligence.idea_coverage import IDEA_COVERAGE

STRATEGY_FAMILIES = (
    "arbitrage",
    "copy_vault",
    "cross_venue_dislocation",
    "lead_lag",
)


@dataclass(frozen=True, slots=True)
class IdeaIntegration:
    idea_id: int
    title: str
    strategy_families: tuple[str, ...]
    dataset_families: tuple[str, ...]
    proof_state: str = "STRUCTURAL_ONLY"
    proof_of_pnl_allowed: bool = False
    real_execution: bool = False


def _strategy_families(idea_id: int) -> tuple[str, ...]:
    # Foundations, source quality and empirical validation constrain every
    # module.  Module-specific bridges retain their narrower ownership.
    if 45 <= idea_id <= 60:
        return ("arbitrage", "cross_venue_dislocation", "lead_lag")
    if 61 <= idea_id <= 63:
        return ("arbitrage", "cross_venue_dislocation")
    if 64 <= idea_id <= 68:
        return ("copy_vault",)
    return STRATEGY_FAMILIES


def _dataset_families(idea_id: int) -> tuple[str, ...]:
    families = ["external_events"]
    strategies = set(_strategy_families(idea_id))
    if "copy_vault" in strategies:
        families.extend(("copy_vault_fills", "copy_vault_l2", "copy_vault_positions"))
    if strategies.intersection({"lead_lag", "cross_venue_dislocation", "arbitrage"}):
        families.extend(
            (
                "bbo",
                "funding_settlement",
                "instrument_metadata",
                "l2Book",
                "open_interest",
                "trades",
            )
        )
    return tuple(dict.fromkeys(families))


EVENT_INTELLIGENCE_INTEGRATION = tuple(
    IdeaIntegration(
        idea_id=row.idea_id,
        title=row.title,
        strategy_families=_strategy_families(row.idea_id),
        dataset_families=_dataset_families(row.idea_id),
    )
    for row in IDEA_COVERAGE
)


def integration_contract() -> dict[str, object]:
    rows = [asdict(row) for row in EVENT_INTELLIGENCE_INTEGRATION]
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ids = [row.idea_id for row in EVENT_INTELLIGENCE_INTEGRATION]
    return {
        "schema": "alina.event_intelligence_integration.v1",
        "idea_count": len(ids),
        "coverage_complete": ids == list(range(1, 121)),
        "coverage_sha256": hashlib.sha256(encoded).hexdigest(),
        "linked_strategy_families": list(STRATEGY_FAMILIES),
        "dataset_families": sorted(
            {
                family
                for row in EVENT_INTELLIGENCE_INTEGRATION
                for family in row.dataset_families
            }
        ),
        "proof_state": "STRUCTURAL_ONLY",
        "proof_of_pnl_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


__all__ = [
    "EVENT_INTELLIGENCE_INTEGRATION",
    "IdeaIntegration",
    "STRATEGY_FAMILIES",
    "integration_contract",
]
