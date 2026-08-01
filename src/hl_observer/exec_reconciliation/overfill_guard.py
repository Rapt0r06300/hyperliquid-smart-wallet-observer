"""[EXEC pépite 201] OVERFILL GUARD : détecter EXPLICITEMENT filled_qty > requested_qty, conserver overfill_qty, et
empêcher qu'un overfill soit SILENCIEUSEMENT absorbé dans la position. Un overfill (on est rempli plus que demandé)
est une anomalie de venue qui, ignorée, gonfle la position sans trace. On l'isole et on le signale (Nautilus a dû
ajouter exactement cette protection). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def verifier(filled_qty: Any, requested_qty: Any) -> dict[str, Any]:
    """Signale un overfill si filled > requested ; renvoie overfill_qty = filled − requested. Données invalides →
    anomalie (on ne suppose jamais un fill conforme). L'overfill n'est JAMAIS absorbé en silence."""
    if not all(isinstance(x, (int, float)) for x in (filled_qty, requested_qty)) \
            or float(filled_qty) < 0 or float(requested_qty) < 0:
        return {"overfill": True, "raison": "QUANTITE_INVALIDE"}
    over = float(filled_qty) - float(requested_qty)
    if over > 1e-12:
        return {"overfill": True, "overfill_qty": round(over, 12), "requested": float(requested_qty),
                "filled": float(filled_qty), "raison": "FILLED_SUPERIEUR_A_REQUESTED"}
    return {"overfill": False, "overfill_qty": 0.0, "raison": "OK"}


__all__ = ["verifier"]
