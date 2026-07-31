"""CHANTIER #69 — MAKER queue/toxicity sur VRAIE TAPE HF (débloqué par le recorder #64).

Sur une tape HF (carnet + trades signés), pour chaque ordre maker simulé : queue devant, volume agressif
traversant, cancellations, depletion → fill / partial / non-fill (research.queue_model), PUIS sélection
ADVERSE (on est rempli précisément quand le marché tourne contre nous) → toxicité → E[PnL|fill]
(research.maker_toxicity). Le maker n'est autorisé que si E[PnL|fill] > 0.

Discipline honnête : tant que la tape n'est pas la VRAIE tape HF (`tape_reelle=False`), le bloc n'est PAS
« prouvé économiquement » même s'il mesure. Sans épisodes → BLOCKED_EXTERNAL. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.research.maker_toxicity import esperance_pnl_fill_bps, maker_autorise, toxicity_score
from hl_observer.research.queue_model import fill_probabiliste, fill_risk_averse

BLOCKED = "BLOCKED_EXTERNAL"
_LONG = ("B", "BUY", "LONG", "1")


def _median(xs: Sequence[float]) -> float | None:
    v = sorted(float(x) for x in xs if isinstance(x, (int, float)))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def evaluer_episode(ep: Mapping[str, Any], *, maker_fee_bps: float, spread_capture_bps_defaut: float) -> dict[str, Any]:
    """Un épisode maker : {queue_ahead, volume_traversant, cancels_devant?, side, mid_at_post, mid_after,
    edge_brut_bps?, spread_capture_bps?, queue_depletion?}. Rend fill + toxicité (adverse) + E[PnL|fill]."""
    qa, vt = ep.get("queue_ahead"), ep.get("volume_traversant")
    filled = fill_risk_averse(qa, vt).get("fill")             # baseline prudente (jamais 'touché = rempli')
    p_fill = fill_probabiliste(qa, vt, cancels_devant=float(ep.get("cancels_devant", 0.0))).get("p_fill")
    res = {"filled": filled, "p_fill": p_fill}
    if filled is not True:
        res["e_pnl_fill_bps"] = None
        return res
    side = str(ep.get("side", "")).strip().upper()
    long = any(side.startswith(x) for x in _LONG)
    m0, m1 = ep.get("mid_at_post"), ep.get("mid_after")
    markout_bps = None
    if isinstance(m0, (int, float)) and isinstance(m1, (int, float)) and m0 > 0:
        sens = 1.0 if long else -1.0
        markout_bps = sens * (m1 / m0 - 1.0) * 1e4          # >0 favorable, <0 sélection ADVERSE (toxique)
    # seule une markout ADVERSE (négative) est toxique ; une markout favorable n'ajoute pas de toxicité
    tilt = (max(0.0, -markout_bps) if isinstance(markout_bps, (int, float)) else None)
    tox = toxicity_score(queue_depletion=ep.get("queue_depletion"), microprice_tilt_bps=tilt).get("toxicity")
    spread_cap = float(ep.get("spread_capture_bps", spread_capture_bps_defaut))
    edge = float(ep.get("edge_brut_bps", spread_cap))
    e_pnl = esperance_pnl_fill_bps(edge, tox, spread_capture_bps=spread_cap, maker_fee_bps=maker_fee_bps)
    res.update({"markout_bps": (round(markout_bps, 4) if markout_bps is not None else None),
                "toxicity": tox, "e_pnl_fill_bps": e_pnl, "maker_autorise": maker_autorise(e_pnl)})
    return res


def experience_maker_tape(episodes: Sequence[Mapping[str, Any]] | None, *, maker_fee_bps: float = 1.0,
                          spread_capture_bps: float = 2.0, tape_reelle: bool = False) -> dict[str, Any]:
    """Agrège les épisodes maker en un verdict. Sans épisodes → BLOCKED_EXTERNAL. Un E[PnL|fill] médian ≤ 0
    = KILL (fill toxique). Positif mais tape non réelle = MORE_DATA (mesuré, VRAIE tape HF requise pour preuve)."""
    if not episodes:
        return {"verdict": BLOCKED, "manque": "vraie tape HF (carnet + trades signés) du recorder #64",
                "real_execution": False}
    evals = [evaluer_episode(e, maker_fee_bps=maker_fee_bps, spread_capture_bps_defaut=spread_capture_bps)
             for e in episodes]
    fills = [e for e in evals if e.get("filled") is True]
    e_pnls = [e["e_pnl_fill_bps"] for e in fills if isinstance(e.get("e_pnl_fill_bps"), (int, float))]
    toxs = [e["toxicity"] for e in fills if isinstance(e.get("toxicity"), (int, float))]
    e_pnl_med = _median(e_pnls)
    if not fills or e_pnl_med is None:
        verdict = "MORE_DATA"
    elif e_pnl_med <= 0:
        verdict = "KILL"                                     # sélection adverse : le fill maker est toxique
    else:
        verdict = "CANDIDAT" if tape_reelle else "MORE_DATA"  # positif, mais tape réelle requise pour la preuve
    return {"verdict": verdict, "n_episodes": len(episodes), "n_fills": len(fills),
            "fill_rate": round(len(fills) / len(episodes), 4),
            "toxicity_mediane": (round(_median(toxs), 4) if toxs else None),
            "e_pnl_fill_median_bps": (round(e_pnl_med, 4) if e_pnl_med is not None else None),
            "n_maker_autorises": sum(1 for e in fills if e.get("maker_autorise")),
            "preuve_economique": bool(tape_reelle and verdict == "CANDIDAT"),
            "tape_reelle": bool(tape_reelle), "real_execution": False}


__all__ = ["evaluer_episode", "experience_maker_tape", "BLOCKED"]
