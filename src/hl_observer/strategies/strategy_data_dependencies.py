"""AUD-049 / AUD-059 — Autorité UNIQUE des dépendances famille -> données REQUISES.

`strategies.active_scope` dit QUELLES familles peuvent matérialiser une économie paper.
Ce module dit, pour chacune, QUELLES sources de données lui sont REQUISES. Deny-by-default :
une famille inconnue n'a AUCUNE donnée « offerte », et une famille active dont une source requise
est absente n'est PAS data-ready (on refuse un faux vert faute de données).

Les identifiants de source sont les `nom` canoniques de `ops.preuve_de_vie.SOURCES_HARVEST`.
Read-only ; aucune exécution réelle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.strategies.active_scope import active_strategy_families

# Famille -> sources de données REQUISES (identifiants canoniques SOURCES_HARVEST).
_REQUISES: dict[str, frozenset[str]] = {
    # Copy-Vault suit les leaders : fills du leader (userFills) + prix/marks pour valoriser les positions.
    "copy_vault": frozenset({"userfills-live", "allmids-collector"}),
    # Lead-Lag est inter-venues (Binance -> HL) : le flux BBO HL+Binance est indispensable.
    "lead_lag": frozenset({"bbo-collector", "carnet-collector"}),
    # Cross-Venue compare deux venues. Le BBO prouve le prix top-of-book, mais
    # le carnet L2 est requis pour mesurer profondeur, capacite et slippage.
    "cross_venue_dislocation": frozenset({"bbo-collector", "carnet-collector"}),
}


def strategy_data_dependencies() -> dict[str, frozenset[str]]:
    """Manifeste immuable famille -> sources requises (copie défensive)."""
    return dict(_REQUISES)


def required_sources(family: str) -> frozenset[str]:
    """Sources REQUISES d'une famille. Deny-by-default : famille inconnue -> frozenset()."""
    return _REQUISES.get(str(family).strip().lower(), frozenset())


@dataclass(frozen=True, slots=True)
class DataReadiness:
    family: str
    ready: bool
    missing: frozenset[str]
    required: frozenset[str]


def evaluate_family_data_readiness(family: str, available_sources: Iterable[str]) -> DataReadiness:
    """Data-ready ssi TOUTES les sources requises sont disponibles. Deny-by-default : sans exigence
    déclarée, jamais « ready » (une famille inconnue ou non déclarée ne produit pas de faux vert)."""
    fam = str(family).strip().lower()
    req = required_sources(fam)
    avail = {str(s).strip().lower() for s in available_sources}
    missing = frozenset(s for s in req if s not in avail)
    ready = bool(req) and not missing
    return DataReadiness(family=fam, ready=ready, missing=missing, required=req)


def active_families_have_declared_dependencies() -> bool:
    """Invariant : CHAQUE famille active de l'autorité de scope a des dépendances déclarées."""
    return all(bool(required_sources(f)) for f in active_strategy_families())
