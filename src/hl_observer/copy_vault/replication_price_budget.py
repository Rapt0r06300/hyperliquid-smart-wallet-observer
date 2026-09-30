"""[COPY-VAULT #72] REPLICATION-PRICE BUDGET : pour chaque leader, définir l'écart MAXIMUM autorisé entre le prix
de son fill et NOTRE prix exécutable. Si notre prix exécutable est trop loin du sien (le marché a bougé, on arrive
trop tard), la copie n'est plus fidèle et on refuse. Prix manquant → refus (jamais supposé dans le budget).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def dans_budget(prix_leader: Any, notre_prix_executable: Any, *, budget_bps: float) -> dict[str, Any]:
    """Écart = |notre_prix − prix_leader| / prix_leader × 1e4. Copie autorisée si écart ≤ budget. Prix invalide
    → refus."""
    if not all(isinstance(x, (int, float)) for x in (prix_leader, notre_prix_executable)) or float(prix_leader) <= 0:
        return {"ok": False, "ecart_bps": None, "raison": "PRIX_INVALIDE"}
    ecart = abs(float(notre_prix_executable) - float(prix_leader)) / float(prix_leader) * 1e4
    ok = ecart <= float(budget_bps)
    return {"ok": bool(ok), "ecart_bps": round(ecart, 4), "budget_bps": float(budget_bps),
            "raison": ("OK" if ok else "ECART_PRIX_HORS_BUDGET")}


__all__ = ["dans_budget"]
