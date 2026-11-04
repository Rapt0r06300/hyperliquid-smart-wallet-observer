"""D17 — REBATE MAKER CIBLÉ : poster maker SEULEMENT là où le rebate bat la sélection adverse.

Poster passif rapporte un rebate MAIS expose à la sélection adverse : on est rempli surtout quand
le marché va CONTRE nous (le fill « gratuit » est un piège). L'espérance honnête de poster maker :

    EV_maker (bps) = prob_fill × rebate − selection_adverse

On ne poste que si EV_maker > 0 (+ marge). Sur notre venue, la sélection adverse DOMINE le rebate
pour la plupart des coins — c'est *exactement* pourquoi le market making y meurt (0/29). Ce module
ne ressuscite rien : il dit HONNÊTEMENT quand poster maker vaut le coup, et le plus souvent : non.

`prob_fill` vient de κ (fill_intensity) ; `selection_adverse` du markout/VPIN. PAPER only.
"""
from __future__ import annotations

import math


def ev_maker_bps(prob_fill: float, rebate_bps: float, selection_adverse_bps: float) -> float:
    """Espérance (bps) de poster maker = prob_fill × rebate − sélection adverse."""
    p = min(1.0, max(0.0, float(prob_fill)))
    return p * float(rebate_bps) - max(0.0, float(selection_adverse_bps))


def poster_maker(prob_fill: float, rebate_bps: float, selection_adverse_bps: float, *,
                 marge_min_bps: float = 0.0) -> bool:
    """True si poster maker a une espérance POSITIVE (rebate bat la sélection adverse) + marge."""
    return ev_maker_bps(prob_fill, rebate_bps, selection_adverse_bps) > float(marge_min_bps)


def rebate_without_fill_receipt(*, prob_fill: object, rebate_bps: object, selection_adverse_bps: object) -> dict[str, object]:
    """Keep rebate out of economics when no fill is observed."""

    try:
        probability, rebate, adverse = (float(value) for value in (prob_fill, rebate_bps, selection_adverse_bps))
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "expected_rebate_bps": None, "reason": "REBATE_INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (probability, rebate, adverse)) or not 0.0 <= probability <= 1.0 or rebate < 0.0 or adverse < 0.0:
        return {"status": "UNMEASURABLE", "expected_rebate_bps": None, "reason": "REBATE_INPUT_INVALID"}
    return {"status": "PROVEN", "expected_rebate_bps": round(probability * rebate, 8), "selection_adverse_bps": round(adverse, 8), "no_fill_rebate": 0.0}


__all__ = ["ev_maker_bps", "poster_maker"]
