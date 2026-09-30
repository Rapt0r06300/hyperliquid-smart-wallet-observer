"""[COPY-VAULT lot2 #56] NORMALIZED LEVERAGE DRIFT : détecter quand le leader augmente BRUTALEMENT son levier
effectif SANS augmenter proportionnellement son alpha apparent. Un trader qui double son levier sans que son edge
suive prend simplement plus de risque pour le même signal — dangereux à copier tel quel. On compare la hausse de
levier à la hausse d'alpha. Données invalides → drift suspect (prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def detecter(*, levier_avant: Any, levier_apres: Any, alpha_avant: Any, alpha_apres: Any,
             tolerance: float = 1.2) -> dict[str, Any]:
    """Suspect si le levier croît nettement plus vite que l'alpha (ratio de croissance levier / croissance alpha
    > tolerance). Données invalides ou alpha non croissant avec levier croissant → suspect. Pur."""
    if not all(isinstance(x, (int, float)) for x in (levier_avant, levier_apres, alpha_avant, alpha_apres)) \
            or float(levier_avant) <= 0 or float(alpha_avant) <= 0:
        return {"suspect": True, "raison": "DONNEE_INVALIDE"}
    croissance_levier = float(levier_apres) / float(levier_avant)
    croissance_alpha = float(alpha_apres) / float(alpha_avant)
    if croissance_levier <= 1.0 + 1e-9:
        return {"suspect": False, "raison": "LEVIER_NON_AUGMENTE"}
    ratio = croissance_levier / croissance_alpha if croissance_alpha > 0 else float("inf")
    suspect = ratio > float(tolerance)
    return {"suspect": bool(suspect), "croissance_levier": round(croissance_levier, 4),
            "croissance_alpha": round(croissance_alpha, 4), "ratio": round(ratio, 4) if ratio != float("inf") else "INF",
            "raison": ("LEVIER_SANS_ALPHA" if suspect else "PROPORTIONNE")}


__all__ = ["detecter"]
