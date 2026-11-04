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
                   seuil_demote: float = 0.5, seuil_pause: float = 0.2,
                   evidence_timestamp_ms: int | None = None,
                   now_ms: int | None = None,
                   proof_ttl_ms: int | None = None) -> dict[str, Any]:
    """Baseline = moyenne hors fenêtre récente ; récent = moyenne fenêtre. Chute relative → PAUSE/DEMOTE."""
    v = [float(x) for x in serie_net_bps]
    stale = False
    if evidence_timestamp_ms is not None or now_ms is not None or proof_ttl_ms is not None:
        try:
            stale = (
                evidence_timestamp_ms is None
                or now_ms is None
                or proof_ttl_ms is None
                or int(evidence_timestamp_ms) <= 0
                or int(now_ms) < int(evidence_timestamp_ms)
                or int(proof_ttl_ms) <= 0
                or int(now_ms) - int(evidence_timestamp_ms) > int(proof_ttl_ms)
            )
        except (TypeError, ValueError, OverflowError):
            stale = True
    if len(v) < 2 * fenetre:
        return {"statut": "MORE_DATA", "raison": "serie trop courte", "n": len(v)}
    baseline = v[:-fenetre]
    recent = v[-fenetre:]
    mb = statistics.mean(baseline)
    mr = statistics.mean(recent)
    if mb <= 0:
        status = "PAUSE" if stale else ("OK" if mr <= 0 else "AMELIORATION")
        return {"statut": status, "baseline_bps": round(mb, 4), "recent_bps": round(mr, 4),
                "proof_stale": stale, "nouvelles_entrees_suspendues": stale}
    chute = (mb - mr) / mb                                # chute relative du edge
    if chute >= seuil_demote:
        statut = "DEMOTE"
    elif chute >= seuil_pause:
        statut = "PAUSE"
    else:
        statut = "OK"
    if stale and statut == "OK":
        statut = "PAUSE"
    return {"statut": statut, "baseline_bps": round(mb, 4), "recent_bps": round(mr, 4),
            "chute_relative": round(chute, 4), "proof_stale": stale,
            "nouvelles_entrees_suspendues": stale}


__all__ = ["detecter_drift", "UNMEASURABLE"]
