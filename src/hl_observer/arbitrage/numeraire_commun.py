"""[ARB #5] NUMÉRAIRE COMMUN : convertir CHAQUE prix, frais et PnL vers un quote asset canonique (défaut USD)
AVANT toute comparaison. Comparer un prix coté en USDT à un prix coté en USDC sans conversion = comparer des
choux et des carottes. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
NUMERAIRE_DEFAUT = "USD"


def vers_numeraire(montant: Any, quote_asset: str, *, taux_vers_numeraire: Mapping[str, float],
                   numeraire: str = NUMERAIRE_DEFAUT) -> Any:
    """Convertit `montant` (prix/frais/PnL coté en `quote_asset`) vers le numéraire via un taux EXÉCUTABLE.
    `taux_vers_numeraire[quote_asset]` = combien vaut 1 unité de quote_asset dans le numéraire. Manquant → UNMEASURABLE
    (jamais supposé 1:1)."""
    if not isinstance(montant, (int, float)) or isinstance(montant, bool):
        return UNMEASURABLE
    qa = str(quote_asset).upper()
    if qa == str(numeraire).upper():
        return round(float(montant), 10)
    taux = taux_vers_numeraire.get(qa)
    if not isinstance(taux, (int, float)) or taux <= 0:
        return UNMEASURABLE                                # taux inconnu -> on ne fabrique pas de conversion
    return round(float(montant) * float(taux), 10)


def comparable(prix_a: Any, quote_a: str, prix_b: Any, quote_b: str, *,
               taux_vers_numeraire: Mapping[str, float], numeraire: str = NUMERAIRE_DEFAUT) -> dict[str, Any]:
    """Ramène deux prix cotés dans des quotes potentiellement différents au MÊME numéraire avant comparaison."""
    na = vers_numeraire(prix_a, quote_a, taux_vers_numeraire=taux_vers_numeraire, numeraire=numeraire)
    nb = vers_numeraire(prix_b, quote_b, taux_vers_numeraire=taux_vers_numeraire, numeraire=numeraire)
    mesurable = isinstance(na, (int, float)) and isinstance(nb, (int, float))
    return {"prix_a_num": na, "prix_b_num": nb, "numeraire": numeraire, "comparable": mesurable,
            "ecart_num": (round(na - nb, 10) if mesurable else UNMEASURABLE)}


__all__ = ["vers_numeraire", "comparable", "UNMEASURABLE", "NUMERAIRE_DEFAUT"]
