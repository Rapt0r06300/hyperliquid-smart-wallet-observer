"""Authorities for runtime and economic data dependencies by strategy family.

Two notions are deliberately distinct:
- runtime readiness: enough data to observe/detect a strategy safely;
- economic readiness: enough data to certify executable/liquidatable net PnL.

The economic layer is stricter because L2 depth is required to measure capacity
and slippage. Keeping both authorities separate prevents an economic proof
requirement from accidentally disabling a signal pipeline that can still be
observed from BBO data. Unknown families remain deny-by-default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.strategies.active_scope import active_strategy_families

# Runtime observation dependencies. These preserve the existing production
# semantics used by READY_STRATEGIES.
_RUNTIME_REQUIRED: dict[str, frozenset[str]] = {
    "copy_vault": frozenset({"userfills-live", "allmids-collector"}),
    "lead_lag": frozenset({"bbo-collector"}),
    "cross_venue_dislocation": frozenset({"bbo-collector"}),
}

# Economic proof dependencies. L2 depth is mandatory where executable
# slippage/capacity must be measured before LIQUIDATABLE_NET can become true.
_ECONOMIC_REQUIRED: dict[str, frozenset[str]] = {
    "copy_vault": frozenset({"userfills-live", "allmids-collector", "carnet-collector"}),
    "lead_lag": frozenset({"bbo-collector", "carnet-collector"}),
    "cross_venue_dislocation": frozenset({"bbo-collector", "carnet-collector"}),
}


def strategy_data_dependencies() -> dict[str, frozenset[str]]:
    """Runtime observation dependency manifest (defensive copy)."""
    return dict(_RUNTIME_REQUIRED)


def economic_strategy_data_dependencies() -> dict[str, frozenset[str]]:
    """Economic/liquidatable-net dependency manifest (defensive copy)."""
    return dict(_ECONOMIC_REQUIRED)


def required_sources(family: str) -> frozenset[str]:
    """Runtime sources required by a family. Unknown -> empty (deny-by-default)."""
    return _RUNTIME_REQUIRED.get(str(family).strip().lower(), frozenset())


def economic_required_sources(family: str) -> frozenset[str]:
    """Sources required to certify executable economic evidence."""
    return _ECONOMIC_REQUIRED.get(str(family).strip().lower(), frozenset())


@dataclass(frozen=True, slots=True)
class DataReadiness:
    family: str
    ready: bool
    missing: frozenset[str]
    required: frozenset[str]


def _evaluate(family: str, available_sources: Iterable[str], required: frozenset[str]) -> DataReadiness:
    fam = str(family).strip().lower()
    avail = {str(s).strip().lower() for s in available_sources}
    missing = frozenset(source for source in required if source not in avail)
    return DataReadiness(
        family=fam,
        ready=bool(required) and not missing,
        missing=missing,
        required=required,
    )


def evaluate_family_data_readiness(family: str, available_sources: Iterable[str]) -> DataReadiness:
    """Runtime data readiness used by the production strategy readiness gate."""
    fam = str(family).strip().lower()
    return _evaluate(fam, available_sources, required_sources(fam))


def evaluate_family_economic_readiness(family: str, available_sources: Iterable[str]) -> DataReadiness:
    """Stricter readiness used only for economic/liquidatable-net certification."""
    fam = str(family).strip().lower()
    return _evaluate(fam, available_sources, economic_required_sources(fam))


def active_families_have_declared_dependencies() -> bool:
    return all(bool(required_sources(family)) for family in active_strategy_families())


def active_families_have_declared_economic_dependencies() -> bool:
    return all(bool(economic_required_sources(family)) for family in active_strategy_families())


__all__ = [
    "DataReadiness",
    "active_families_have_declared_dependencies",
    "active_families_have_declared_economic_dependencies",
    "economic_required_sources",
    "economic_strategy_data_dependencies",
    "evaluate_family_data_readiness",
    "evaluate_family_economic_readiness",
    "required_sources",
    "strategy_data_dependencies",
]
