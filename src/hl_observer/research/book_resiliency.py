"""ALPHA P26 — RÉSILIENCE du carnet après choc (burst agressif / slice TWAP / liquidation / spread shock).

Après un choc, on mesure la vitesse de reconstitution de la profondeur : demi-vie de récupération, fraction
de profondeur restaurée, tilt de côté. Sert à distinguer CONTINUATION (le carnet ne se reconstitue pas, le
prix continue) vs REVERSAL (il se reconstitue, le prix revient). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def resilience(profondeur_apres: Sequence[float], *, profondeur_avant: float, dt_s: float = 1.0) -> dict[str, Any]:
    """Depuis la profondeur post-choc (série) et la profondeur pré-choc, calcule récupération + demi-vie."""
    if not profondeur_apres or profondeur_avant <= 0:
        return {"fraction_restauree": UNMEASURABLE, "demi_vie_s": UNMEASURABLE, "regime": UNMEASURABLE}
    finale = profondeur_apres[-1]
    frac = finale / profondeur_avant
    creux = min(profondeur_apres)
    # demi-vie de récupération : temps pour combler la moitié du creux vers l'avant
    cible = creux + 0.5 * (profondeur_avant - creux)
    demi_vie = None
    for t, p in enumerate(profondeur_apres):
        if p >= cible:
            demi_vie = t * dt_s
            break
    regime = "REVERSAL" if frac >= 0.8 else ("CONTINUATION" if frac <= 0.4 else "MIXTE")
    return {"fraction_restauree": round(frac, 4),
            "demi_vie_s": (round(demi_vie, 3) if demi_vie is not None else UNMEASURABLE),
            "creux": round(creux, 4), "regime": regime}


__all__ = ["resilience", "UNMEASURABLE"]
