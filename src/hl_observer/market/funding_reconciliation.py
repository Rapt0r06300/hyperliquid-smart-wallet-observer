"""RÉCONCILIATION FUNDING MULTI-SOURCES (idée #36) — comparer le funding d'un coin entre venues
(toutes déjà en bps/h), signaler les divergences aberrantes (source cassée), et construire le dict
{venue: funding} propre pour l'arb cross-venue. Deny-by-default : source douteuse écartée.
LECTURE SEULE. Aucun ordre.
"""
from __future__ import annotations

DIVERGENCE_ABERRANTE_BPS_H = 5.0     # au-delà, une venue est probablement cassée (unité ? stale ?)


def reconcilier(fundings_par_venue: dict) -> dict:
    """{venue: funding_bps_h} -> {ok: {venue: f}, ecartes: {venue: raison}, mediane, dispersion}.
    Une venue à None ou trop loin de la médiane est ÉCARTÉE (pas fabriquée, pas trustée)."""
    valides = {str(v): float(f) for v, f in (fundings_par_venue or {}).items()
               if isinstance(f, (int, float))}
    ecartes = {str(v): "funding_absent" for v, f in (fundings_par_venue or {}).items()
               if not isinstance(f, (int, float))}
    if not valides:
        return {"ok": {}, "ecartes": ecartes, "mediane": None, "dispersion": 0.0}
    vals = sorted(valides.values())
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    ok = {}
    for v, f in valides.items():
        if abs(f - med) > DIVERGENCE_ABERRANTE_BPS_H:
            ecartes[v] = "divergence_aberrante(%.3f vs med %.3f)" % (f, med)
        else:
            ok[v] = f
    dispersion = round(max(ok.values()) - min(ok.values()), 6) if ok else 0.0
    return {"ok": ok, "ecartes": ecartes, "mediane": round(med, 6), "dispersion": dispersion}


__all__ = ["reconcilier", "DIVERGENCE_ABERRANTE_BPS_H"]
