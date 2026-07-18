"""FUNDING MULTI-VENUES (idées #1/#2) — le même coin a un funding différent sur chaque venue. Pour
CHAQUE coin, toutes les PAIRES de venues (long où funding bas, short où haut) sont des carries
delta-neutres candidats -> BEAUCOUP plus d'ouvertures qu'avec HL seul. Pur, prêt pour les flux
(l'appelant fournit le funding par venue, lecture seule). PAPER only, aucun ordre.
"""
from __future__ import annotations

from itertools import combinations

SEUIL_DISPERSION_BPS_H = 0.02
HORIZON_DEFAUT_H = 720.0


def classer_carries_multi_venue(coin: str, funding_par_venue: dict[str, float], *,
                                cout_entree_bps: float, horizon_h: float = HORIZON_DEFAUT_H,
                                seuil_bps_h: float = SEUIL_DISPERSION_BPS_H) -> list[dict]:
    """Toutes les paires de venues viables pour ce coin, triées par gain net décroissant.
    Funding manquant/non numérique sur une venue -> venue ignorée (on ne devine pas)."""
    venues = {v: float(f) for v, f in (funding_par_venue or {}).items()
              if isinstance(f, (int, float))}
    out: list[dict] = []
    for a, b in combinations(sorted(venues), 2):
        fa, fb = venues[a], venues[b]
        capture = abs(fa - fb)
        if capture <= float(seuil_bps_h):
            continue
        long_v, short_v = (a, b) if fa <= fb else (b, a)   # long où funding bas, short où haut
        gain = capture * float(horizon_h) - float(cout_entree_bps)
        if gain <= 0:
            continue
        out.append({"coin": str(coin).upper(), "long_venue": long_v, "short_venue": short_v,
                    "capture_bps_h": round(capture, 6), "gain_net_bps": round(gain, 3),
                    "break_even_h": round(float(cout_entree_bps) / capture, 2),
                    "paper_only": True, "real_execution": False})
    out.sort(key=lambda x: -x["gain_net_bps"])
    return out


def compter_opportunites(univers: dict[str, dict[str, float]], *, cout_entree_bps: float) -> int:
    """Combien d'ouvertures candidates au total sur tout l'univers {coin: {venue: funding}} ?
    Sert à mesurer l'ÉLARGISSEMENT du terrain de jeu (plus de venues = plus d'ouvertures)."""
    return sum(len(classer_carries_multi_venue(c, fv, cout_entree_bps=cout_entree_bps))
               for c, fv in (univers or {}).items())


__all__ = ["classer_carries_multi_venue", "compter_opportunites",
           "SEUIL_DISPERSION_BPS_H", "HORIZON_DEFAUT_H"]
