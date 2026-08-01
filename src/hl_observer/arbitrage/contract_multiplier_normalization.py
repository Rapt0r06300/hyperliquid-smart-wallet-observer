"""[ARB pépite 229] CONTRACT MULTIPLIER NORMALIZATION : normaliser l'exposition par contract_size × qty, JAMAIS
comparer naïvement les quantités affichées. « 1 contrat » sur une venue peut valoir 100 unités de sous-jacent et
« 1 contrat » sur une autre 1 unité ; comparer les quantités brutes croit couvert alors qu'on ne l'est pas.
Exposition réelle = qty × contract_size. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def exposition(qty: Any, *, contract_size: float) -> Any:
    """Exposition en unités de sous-jacent = qty × contract_size. Entrée invalide → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (qty, contract_size)) or contract_size <= 0:
        return UNMEASURABLE
    return round(float(qty) * float(contract_size), 12)


def apparie(*, qty_a: Any, contract_size_a: float, qty_b: Any, contract_size_b: float,
            tolerance: float = 1e-9) -> dict[str, Any]:
    """Deux jambes sont appariées si leurs EXPOSITIONS (qty×contract_size) coïncident, pas leurs quantités brutes.
    Donnée invalide → non apparié (prudence)."""
    ea = exposition(qty_a, contract_size=contract_size_a)
    eb = exposition(qty_b, contract_size=contract_size_b)
    if ea == UNMEASURABLE or eb == UNMEASURABLE:
        return {"apparie": False, "raison": "EXPOSITION_NON_MESURABLE"}
    ok = abs(ea - eb) <= float(tolerance)
    return {"apparie": bool(ok), "exposition_a": ea, "exposition_b": eb, "ecart": round(ea - eb, 12),
            "raison": ("OK" if ok else "EXPOSITIONS_DIFFERENTES")}


__all__ = ["exposition", "apparie", "UNMEASURABLE"]
