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


def ev_maker_bps(prob_fill: float, rebate_bps: float, selection_adverse_bps: float) -> float:
    """Espérance (bps) de poster maker = prob_fill × rebate − sélection adverse."""
    p = min(1.0, max(0.0, float(prob_fill)))
    return p * float(rebate_bps) - max(0.0, float(selection_adverse_bps))


def poster_maker(prob_fill: float, rebate_bps: float, selection_adverse_bps: float, *,
                 marge_min_bps: float = 0.0) -> bool:
    """True si poster maker a une espérance POSITIVE (rebate bat la sélection adverse) + marge."""
    return ev_maker_bps(prob_fill, rebate_bps, selection_adverse_bps) > float(marge_min_bps)


__all__ = ["ev_maker_bps", "poster_maker"]
