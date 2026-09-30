"""[ARB pépite 230] LINEAR/INVERSE CONTRACT NORMALIZATION : unifier correctement delta/notional/PnL si une venue
représente le sous-jacent en contrat LINÉAIRE (notional = qty × prix) vs INVERSE (notional en devise de marge =
qty / prix, PnL non linéaire en prix). Comparer un linéaire et un inverse sans normaliser fausse le hedge. On ramène
tout à un notional en USD. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

LINEAIRE = "LINEAIRE"
INVERSE = "INVERSE"
UNMEASURABLE = "UNMEASURABLE"


def notional_usd(qty: Any, prix: Any, *, type_contrat: str, contract_size: float = 1.0) -> Any:
    """Notional en USD. Linéaire : qty×contract_size×prix. Inverse : qty×contract_size (déjà en USD, le contrat
    vaut X USD de sous-jacent). Prix invalide → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (qty, prix)) or float(prix) <= 0 or contract_size <= 0:
        return UNMEASURABLE
    t = str(type_contrat).upper()
    if t == LINEAIRE:
        return round(float(qty) * float(contract_size) * float(prix), 8)
    if t == INVERSE:
        return round(float(qty) * float(contract_size), 8)
    return UNMEASURABLE


def pnl_usd(qty: Any, prix_entree: Any, prix_sortie: Any, *, type_contrat: str,
            contract_size: float = 1.0) -> Any:
    """PnL en USD. Linéaire : qty×cs×(sortie−entree). Inverse : qty×cs×(1/entree − 1/sortie) (non linéaire).
    Prix invalide → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (qty, prix_entree, prix_sortie)) \
            or prix_entree <= 0 or prix_sortie <= 0 or contract_size <= 0:
        return UNMEASURABLE
    t = str(type_contrat).upper()
    if t == LINEAIRE:
        return round(float(qty) * contract_size * (float(prix_sortie) - float(prix_entree)), 8)
    if t == INVERSE:
        return round(float(qty) * contract_size * (1.0 / float(prix_entree) - 1.0 / float(prix_sortie)), 8)
    return UNMEASURABLE


__all__ = ["notional_usd", "pnl_usd", "LINEAIRE", "INVERSE", "UNMEASURABLE"]
