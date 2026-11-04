"""[DATA pépite 256] TIMESTAMP-UNIT VALIDATOR : détecter automatiquement la confusion secondes/ms/µs/ns AVANT
qu'un signal soit classé « frais » à tort. Un timestamp en secondes interprété comme des ms (ou l'inverse)
fausse totalement l'âge d'un signal ; on infère l'unité par l'ordre de grandeur (epoch moderne) et on refuse si
elle ne correspond pas à l'unité attendue. Valeur non finie / hors plage → INCONNU. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

# Bornes d'un epoch « moderne » (~2001-2286) par unité, en valeur brute.
_BORNES = (
    ("s", 1.0e9, 1.0e10),
    ("ms", 1.0e12, 1.0e13),
    ("us", 1.0e15, 1.0e16),
    ("ns", 1.0e18, 1.0e19),
)


def detecter_unite(ts: Any) -> str:
    """Infère l'unité par ordre de grandeur. Hors de toute plage moderne → INCONNU (on ne devine pas)."""
    if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not math.isfinite(ts) or ts <= 0:
        return "INCONNU"
    for unite, lo, hi in _BORNES:
        if lo <= ts < hi:
            return unite
    return "INCONNU"


def valider(ts: Any, *, unite_attendue: str = "ms") -> dict[str, Any]:
    """Conforme uniquement si l'unité détectée == unité attendue. Toute divergence ou détection impossible →
    non conforme (fail-closed) : mieux vaut rejeter un timestamp ambigu que classer un vieux signal comme frais."""
    detectee = detecter_unite(ts)
    if detectee == "INCONNU":
        return {"conforme": False, "unite_detectee": "INCONNU", "raison": "HORS_PLAGE_OU_INVALIDE"}
    conforme = detectee == unite_attendue
    return {"conforme": conforme, "unite_detectee": detectee, "unite_attendue": unite_attendue,
            "raison": None if conforme else "UNITE_INATTENDUE"}


def normaliser_ms(ts: Any, *, allow_relative: bool = False) -> dict[str, Any]:
    """Normalize a timestamp only when its unit is provable.

    Relative test clocks are accepted only when the caller explicitly opts in;
    modern epoch values in seconds, microseconds, or nanoseconds are never
    silently converted into milliseconds.
    """

    if allow_relative and isinstance(ts, int) and not isinstance(ts, bool) and 0 < ts < 100_000_000_000:
        return {"conforme": True, "timestamp_ms": ts, "unite_detectee": "relative_ms"}
    result = valider(ts, unite_attendue="ms")
    if not result.get("conforme"):
        return {**result, "timestamp_ms": None}
    return {**result, "timestamp_ms": int(ts)}


__all__ = ["detecter_unite", "normaliser_ms", "valider"]
