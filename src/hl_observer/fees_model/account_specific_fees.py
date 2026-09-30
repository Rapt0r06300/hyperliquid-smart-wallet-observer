"""[ALL lot2 #21] ACCOUNT-SPECIFIC FEES : quand l'API le permet, utiliser les frais RÉELS du compte/tier (obtenus
via un fetch trading-fees) plutôt que le barème PUBLIC générique. Deux comptes n'ont pas les mêmes frais ; chiffrer
un edge avec le barème public sur un compte à frais réduits (ou majorés) fausse le net. Aucun des deux connu →
UNMEASURABLE (jamais 0 supposé). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taux_effectif_bps(*, taux_compte_bps: Any = None, taux_public_bps: Any = None) -> dict[str, Any]:
    """Priorité au taux du compte s'il est connu, sinon le barème public. Aucun des deux → UNMEASURABLE."""
    if isinstance(taux_compte_bps, (int, float)):
        return {"taux_bps": float(taux_compte_bps), "source": "COMPTE"}
    if isinstance(taux_public_bps, (int, float)):
        return {"taux_bps": float(taux_public_bps), "source": "PUBLIC"}
    return {"taux_bps": UNMEASURABLE, "source": "AUCUN", "raison": "AUCUN_TAUX_CONNU"}


__all__ = ["taux_effectif_bps", "UNMEASURABLE"]
