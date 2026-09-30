"""[CROSS-VENUE #10] FEE-TOKEN NORMALIZATION : convertir les commissions prélevées dans un AUTRE token (BNB,
HYPE, points…) vers le numéraire du PnL, à leur prix exécutable. Une remise « payée en BNB » n'est pas gratuite :
elle coûte le prix du BNB. Réutilise numeraire_commun.vers_numeraire. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.arbitrage.numeraire_commun import UNMEASURABLE, vers_numeraire


def frais_vers_numeraire(montant_frais: Any, fee_token: str, *, taux_vers_numeraire: Mapping[str, float],
                         numeraire: str = "USD") -> Any:
    """Convertit une commission libellée en `fee_token` vers le numéraire du PnL via son prix exécutable.
    Token inconnu (pas de taux) → UNMEASURABLE : on ne considère jamais un frais en token comme « gratuit »."""
    return vers_numeraire(montant_frais, fee_token, taux_vers_numeraire=taux_vers_numeraire, numeraire=numeraire)


def frais_total_numeraire(frais: list[Mapping[str, Any]], *, taux_vers_numeraire: Mapping[str, float],
                          numeraire: str = "USD") -> dict[str, Any]:
    """Somme des commissions hétérogènes ramenées au numéraire. Chaque frais = {montant, token}. Un frais non
    convertible marque le total UNMEASURABLE (on ne sous-estime jamais le coût en ignorant un token inconnu)."""
    total = 0.0
    details = []
    incomplet = False
    for f in frais or []:
        conv = frais_vers_numeraire(f.get("montant"), f.get("token", numeraire),
                                    taux_vers_numeraire=taux_vers_numeraire, numeraire=numeraire)
        details.append({"token": f.get("token"), "montant": f.get("montant"), "numeraire": conv})
        if isinstance(conv, (int, float)):
            total += conv
        else:
            incomplet = True
    return {"total_numeraire": (UNMEASURABLE if incomplet else round(total, 10)),
            "numeraire": numeraire, "details": details, "incomplet": incomplet}


__all__ = ["frais_vers_numeraire", "frais_total_numeraire"]
