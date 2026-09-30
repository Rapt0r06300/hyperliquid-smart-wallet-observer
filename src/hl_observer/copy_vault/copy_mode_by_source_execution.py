"""[COPY-VAULT pépite 282] COPY MODE BY SOURCE EXECUTION : un vault performant UNIQUEMENT grâce à ses maker
fills ne doit pas être évalué comme s'il était copiable instantanément en taker. On dérive un MODE de copie du
profil d'exécution : maker-dépendant → décote de confiance forte (l'alpha vient peut-être du rebate/placement,
pas du signal) ; taker-dominant → réplication directe plus crédible. Profil manquant → UNMEASURABLE. Pur,
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

MAKER_DEPENDANT = "MAKER_DEPENDANT"
DIRECT_TAKER = "DIRECT_TAKER"
MIXTE = "MIXTE"
UNMEASURABLE = "UNMEASURABLE"


def mode_copie(profil: dict[str, Any], *, seuil_maker: float = 0.7, seuil_taker: float = 0.7) -> dict[str, Any]:
    """taux_maker ≥ seuil_maker → MAKER_DEPENDANT (décote forte, alpha suspect en copie taker). taux_taker ≥
    seuil_taker → DIRECT_TAKER (décote faible). Entre les deux → MIXTE (décote moyenne). taux absent →
    UNMEASURABLE (on ne suppose pas copiable)."""
    if not isinstance(profil, dict):
        return {"mode": UNMEASURABLE, "raison": "PROFIL_INVALIDE"}
    tm = profil.get("taux_maker")
    tt = profil.get("taux_taker")
    if not isinstance(tm, (int, float)) or not isinstance(tt, (int, float)):
        return {"mode": UNMEASURABLE, "raison": "TAUX_NON_MESURE"}
    if tm >= seuil_maker:
        return {"mode": MAKER_DEPENDANT, "decote_confiance": 0.6, "copiable_taker_direct": False}
    if tt >= seuil_taker:
        return {"mode": DIRECT_TAKER, "decote_confiance": 0.1, "copiable_taker_direct": True}
    return {"mode": MIXTE, "decote_confiance": 0.3, "copiable_taker_direct": True}


__all__ = ["mode_copie", "MAKER_DEPENDANT", "DIRECT_TAKER", "MIXTE", "UNMEASURABLE"]
