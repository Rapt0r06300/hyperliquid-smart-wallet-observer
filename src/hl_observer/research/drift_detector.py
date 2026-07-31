"""ALPHA P42 — DÉTECTEUR de drift d'alpha : le edge se dégrade-t-il ? Rupture → PAUSE/DEMOTE, jamais retune silencieux.

Compare une fenêtre récente à la baseline (début de série) sur le net edge. Chute significative → DEMOTE ;
légère → PAUSE ; stable → OK. On ne re-optimise JAMAIS en douce ; on suspend et on signale. Pur, 0 réseau.
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def detecter_drift(serie_net_bps: Sequence[float], *, fenetre: int = 20,
                   seuil_demote: float = 0.5, seuil_pause: float = 0.2) -> dict[str, Any]:
    """Baseline = moyenne hors fenêtre récente ; récent = moyenne fenêtre. Chute relative → PAUSE/DEMOTE."""
    v = [float(x) for x in serie_net_bps]
    if len(v) < 2 * fenetre:
        return {"statut": "MORE_DATA", "raison": "serie trop courte", "n": len(v)}
    baseline = v[:-fenetre]
    recent = v[-fenetre:]
    mb = statistics.mean(baseline)
    mr = statistics.mean(recent)
    if mb <= 0:
        return {"statut": "OK" if mr <= 0 else "AMELIORATION", "baseline_bps": round(mb, 4), "recent_bps": round(mr, 4)}
    chute = (mb - mr) / mb                                # chute relative du edge
    if chute >= seuil_demote:
        statut = "DEMOTE"
    elif chute >= seuil_pause:
        statut = "PAUSE"
    else:
        statut = "OK"
    return {"statut": statut, "baseline_bps": round(mb, 4), "recent_bps": round(mr, 4),
            "chute_relative": round(chute, 4)}


__all__ = ["detecter_drift", "UNMEASURABLE"]
