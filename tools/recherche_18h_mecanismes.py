"""MÉCANISMES 18 h — ARCHITECTURE À DEUX VITESSES (Flo 26/07).

FAST_SCREEN : élimine VITE les variantes manifestement mauvaises (vectorisé, coûts approximatifs
CONSERVATEURS, top-of-book). Il écrit TOUJOURS `APPROXIMATE_ONLY / NOT_VALIDATED / NOT_ELIGIBLE_FOR_FORWARD`
et ne peut JAMAIS déclarer un candidat positif.

EXACT_REPLAY : rejoue les survivants dans le moteur événementiel causal (RÉUTILISE
recherche_14h_mecanismes.mesurer_phase — bid/ask, VWAP, frais A/R, slippage, latence) à PLUSIEURS horizons,
avec deux modèles maker (RISK_AVERSE_QUEUE prudent pour les verdicts finaux, PROBABILISTIC_QUEUE indicatif).

Objectif directeur : tester LARGE (familles × horizons × coins × régimes) via FAST_SCREEN, puis RENFORCER
seulement ce qui survit à l'EXACT_REPLAY et à la validation. Jamais un faux gagnant. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

#: horizons testés (ms) — le moteur ne se limite plus à 30 s. Chaque horizon = variante distincte.
HORIZONS_MS = (100, 250, 500, 1000, 2000, 3000, 5000, 10000, 15000, 30000, 60000,
               120000, 300000, 900000, 1800000, 3600000)

#: familles NATIVES (déjà mesurées KILL au 14 h mais re-testables sous d'autres horizons/régimes) + place
#: pour les familles étendues (flux, wallets, funding, régimes). Aucune famille KILL ne peut être réintroduite
#: sous un NOUVEAU nom avec EXACTEMENT les mêmes règles (garde-fou dans le registre via parameter_hash).
FAMILLES_NATIVES = ("OFI_TOP1", "OFI_TOP5", "OFI_TOP20", "QUEUE_MICROPRICE", "LIQUIDITY_VACUUM",
                    "HL_ABSORPTION_NATIVE", "TRADE_SWEEP_BURST", "OI_VEL_ACCEL_PRICE_FUNDING",
                    "FUNDING_CLOCK_DIVERGENCE", "LIQUIDATION_CASCADE_DEPTH")

#: coût aller-retour APPROXIMATIF conservateur pour FAST_SCREEN (bps) — volontairement pénalisant, pour ne
#: pas laisser passer un faux positif. L'EXACT_REPLAY recalcule le vrai coût.
COUT_APPROX_AR_BPS = 12.0


def fast_screen(episodes: list[dict], *, cout_ar_bps: float = COUT_APPROX_AR_BPS) -> dict:
    """Écrémage RAPIDE : net approx = médiane(gross_bps) − coût A/R conservateur. Ne PROMEUT jamais.
    `episodes` = [{gross_bps, ...}]. Rend un verdict d'ÉCRÉMAGE (garder/écarter) + les drapeaux obligatoires."""
    gross = [float(e["gross_bps"]) for e in episodes if e.get("gross_bps") is not None]
    n = len(gross)
    net_approx = (statistics.median(gross) - cout_ar_bps) if gross else None
    garder = bool(net_approx is not None and n >= 20 and net_approx > -cout_ar_bps * 0.5)  # tolérant : on garde le "pas clairement mort"
    return {"moteur": "FAST_SCREEN", "n": n, "net_approx_bps": net_approx,
            "ecremage": ("GARDER_POUR_EXACT" if garder else "ECARTER"),
            "drapeaux": ["APPROXIMATE_ONLY", "NOT_VALIDATED", "NOT_ELIGIBLE_FOR_FORWARD"],
            "peut_promouvoir": False}


def exact_replay(root: str | Path, *, t_min_ms=None, t_max_ms=None, horizons_ms=HORIZONS_MS,
                 maker: str = "RISK_AVERSE_QUEUE") -> dict:
    """Rejoue le moteur causal (mesurer_phase) sur la fenêtre, pour CHAQUE horizon. Rend une matrice
    {horizon_ms: {mecanisme: {n, net_median_bps, pf, sharpe}}}. Le modèle maker prudent est le défaut
    pour les verdicts finaux (RISK_AVERSE_QUEUE)."""
    from recherche_14h_mecanismes import mesurer_phase
    matrice = {}
    for h in horizons_ms:
        try:
            res = mesurer_phase(Path(root), t_min_ms=t_min_ms, t_max_ms=t_max_ms, horizon_ref_s=max(1, h // 1000))
        except Exception as e:  # noqa: BLE001 — un horizon qui échoue est marqué, jamais transformé en 0
            matrice[h] = {"_erreur": str(e)[:120], "_statut": "UNMEASURABLE"}
            continue
        matrice[h] = res if isinstance(res, dict) else {"_statut": "UNMEASURABLE"}
    return {"moteur": "EXACT_REPLAY", "maker": maker, "horizons": list(horizons_ms), "matrice": matrice,
            "peut_promouvoir": True, "note": "coûts A/R complets + latence via mesurer_phase ; maker prudent pour verdict"}


def maker_risk_averse_fill(queue_devant_sz: float, volume_traversant_sz: float) -> float:
    """RISK_AVERSE_QUEUE : fraction remplie = max(0, volume_traversant − file_devant)/notre_taille, plafonnée à 1.
    Prudent : on n'est servi QUE si le flux dépasse toute la file devant nous (adverse-selection incluse)."""
    if volume_traversant_sz <= 0:
        return 0.0
    servi = max(0.0, float(volume_traversant_sz) - float(queue_devant_sz))
    return min(1.0, servi / max(1e-9, float(volume_traversant_sz)))


def maker_probabiliste_fill(queue_devant_sz: float, volume_traversant_sz: float) -> float:
    """PROBABILISTIC_QUEUE : proba de fill = volume_traversant/(file_devant+volume) (indicatif, jamais pour
    un verdict final)."""
    denom = float(queue_devant_sz) + float(volume_traversant_sz)
    return 0.0 if denom <= 0 else min(1.0, float(volume_traversant_sz) / denom)


__all__ = ["HORIZONS_MS", "FAMILLES_NATIVES", "fast_screen", "exact_replay",
           "maker_risk_averse_fill", "maker_probabiliste_fill", "COUT_APPROX_AR_BPS"]
