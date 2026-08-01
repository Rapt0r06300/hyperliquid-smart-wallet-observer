"""[ALL #87] CANONICAL OrderCandidate : TOUTE intention passe par le MÊME objet pré-validé avant le PaperEngine —
quantité, côté, prix, maker/taker, budget, contraintes. Un point d'entrée unique garantit qu'aucune intention
non validée n'atteint le moteur. Un champ manquant ou incohérent → candidat REFUSÉ, jamais transmis. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

_COTES = ("BUY", "SELL")
_TYPES = ("MAKER", "TAKER")


def creer_candidat(*, coin: Any, cote: Any, quantite: Any, prix: Any, type_exec: Any,
                   budget_disponible: Any) -> dict[str, Any]:
    """Valide et canonicalise une intention. Refuse si un champ est absent/incohérent, si la quantité/prix ≤ 0,
    ou si le notional dépasse le budget disponible. Le candidat retourné est le SEUL format accepté en aval."""
    erreurs = []
    if not coin:
        erreurs.append("COIN_MANQUANT")
    c = str(cote).upper()
    if c not in _COTES:
        erreurs.append("COTE_INVALIDE")
    t = str(type_exec).upper()
    if t not in _TYPES:
        erreurs.append("TYPE_EXEC_INVALIDE")
    if not isinstance(quantite, (int, float)) or float(quantite) <= 0:
        erreurs.append("QUANTITE_INVALIDE")
    if not isinstance(prix, (int, float)) or float(prix) <= 0:
        erreurs.append("PRIX_INVALIDE")
    if not isinstance(budget_disponible, (int, float)):
        erreurs.append("BUDGET_INVALIDE")
    if erreurs:
        return {"valide": False, "erreurs": erreurs}
    notional = float(quantite) * float(prix)
    if notional > float(budget_disponible) + 1e-9:
        return {"valide": False, "erreurs": ["NOTIONAL_DEPASSE_BUDGET"], "notional": round(notional, 8)}
    return {"valide": True, "coin": str(coin).upper(), "cote": c, "quantite": float(quantite),
            "prix": float(prix), "type_exec": t, "notional": round(notional, 8)}


__all__ = ["creer_candidat"]
