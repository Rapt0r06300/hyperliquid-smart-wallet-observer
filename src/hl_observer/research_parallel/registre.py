"""REGISTRE DE PLUGINS du laboratoire. Tout nouveau module de recherche s'ENREGISTRE ici — plus jamais
besoin de toucher le lanceur. Plafond DUR de 12 variantes pré-enregistrées au total (anti-fishing).

Un plugin est PUR côté déclaration : il expose un `tick(contexte) -> list[dict]` qui rend des lignes de
ledger (signaux shadow), et la liste FIGÉE de ses variantes. Il peut lever une exception : le superviseur
l'isole (le labo ne casse jamais). Deny-by-default : sans plugin enregistré, le labo n'émet rien.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

MAX_VARIANTES_TOTAL = 12        # plafond dur (mandat Flo 25/07) — aucun retuning/ajout au-delà


@dataclass(frozen=True)
class Plugin:
    id: str
    categorie: str                       # data | signal | router
    variantes: tuple                     # ids de variantes PRÉ-ENREGISTRÉES (figées)
    tick: Callable                       # tick(contexte)->list[dict] ; peut lever (isolé par le superviseur)
    exige: tuple = field(default=())     # sources de données requises (ex: ("bbo","asset_ctx"))


_REGISTRE: dict[str, Plugin] = {}


def enregistrer(plugin: Plugin) -> Plugin:
    """Enregistre un plugin. Refuse un id dupliqué OU un dépassement du plafond de variantes (deny-by-default)."""
    if plugin.id in _REGISTRE:
        raise ValueError("plugin déjà enregistré: %s" % plugin.id)
    total = total_variantes() + len([v for v in plugin.variantes])
    if total > MAX_VARIANTES_TOTAL:
        raise ValueError("plafond de %d variantes dépassé (%d) — aucun ajout" % (MAX_VARIANTES_TOTAL, total))
    _REGISTRE[plugin.id] = plugin
    return plugin


def lister() -> list[Plugin]:
    return list(_REGISTRE.values())


def obtenir(pid: str) -> Plugin | None:
    return _REGISTRE.get(pid)


def total_variantes() -> int:
    return sum(len(p.variantes) for p in _REGISTRE.values())


def reset_pour_tests() -> None:
    """Vide le registre — RÉSERVÉ aux tests (le runtime ne réinitialise jamais)."""
    _REGISTRE.clear()


__all__ = ["Plugin", "enregistrer", "lister", "obtenir", "total_variantes", "reset_pour_tests",
           "MAX_VARIANTES_TOTAL"]
