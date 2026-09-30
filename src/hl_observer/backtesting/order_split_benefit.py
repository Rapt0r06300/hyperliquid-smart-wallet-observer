"""DÉCOUPAGE D'ORDRE — utile, ou théâtre ? La réponse honnête pour un book de 500 $.

L'idée « découper un gros ordre en tranches (TWAP/VWAP) réduit l'impact » vient des gros ordres
institutionnels. On la teste sur NOTRE réalité (notional ≈ 500 $) au lieu de la copier.

🔑 Fait dur, tiré de notre propre modèle d'impact (`market_impact.impact_bps`, **linéaire en
participation** : coût = k·taille/profondeur) :

- Sur un **carnet statique** (pas de temps pour qu'il se recharge), découper ne réduit RIEN : le
  coût est proportionnel à la participation *totale*, invariante au découpage. Pire, si consommer
  amincit le carnet, les dernières tranches coûtent PLUS.
- Le découpage n'aide que si de la **liquidité fraîche** arrive entre les tranches (on étale dans le
  temps). C'est le vrai mécanisme du TWAP — pas une magie de convexité.
- À **500 $** de notional sur un carnet normal, l'impact est **négligeable** (< 1 bps). Le découpage
  n'est alors pas le combat : ce n'est pas là qu'est notre edge.

Ce module MESURE tout ça au lieu de l'affirmer. Module PUR ; il réutilise `market_impact` (pas de
2ᵉ modèle d'impact). Une mesure n'est pas un ordre.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hl_observer.market.market_impact import K_IMPACT_DEFAUT_BPS, impact_bps

SEUIL_IMPACT_NEGLIGEABLE_BPS = 1.0     # sous 1 bps, l'impact n'est pas le sujet
GAIN_MINIMAL_UTILE_BPS = 0.5           # en-dessous, le découpage ne « vaut pas la peine »


@dataclass(frozen=True, slots=True)
class VerdictDecoupage:
    impact_unique_bps: float | None
    impact_decoupe_bps: float | None
    gain_bps: float | None             # unique − découpé ; > 0 = le découpage aide
    aide: bool
    motif: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "impact_unique_bps": self.impact_unique_bps,
            "impact_decoupe_bps": self.impact_decoupe_bps,
            "gain_bps": self.gain_bps,
            "aide": self.aide,
            "motif": self.motif,
            "real_execution": False,
        }


def impact_decoupe_bps(
    taille_notional: float,
    profondeur_notional: float,
    *,
    n_tranches: int,
    liquidite_fraiche_par_tranche: float = 0.0,
    k: float = K_IMPACT_DEFAUT_BPS,
) -> float | None:
    """Impact total (bps) en découpant en `n_tranches` égales.

    Entre deux tranches, `liquidite_fraiche_par_tranche` (notional) s'ajoute au carnet — c'est ce qui
    peut rendre le découpage utile. À 0, le carnet ne fait que se vider : découper n'aide pas.
    Renvoie `None` si la profondeur est inconnue (INSUFFICIENT_DATA, jamais un 0 silencieux).
    """
    if profondeur_notional is None or float(profondeur_notional) <= 0.0:
        return None
    n = int(n_tranches)
    if n < 1:
        return None
    tranche = float(taille_notional) / n
    total = 0.0
    consomme = 0.0
    for i in range(n):
        profondeur_courante = (
            float(profondeur_notional) - consomme + float(liquidite_fraiche_par_tranche) * i
        )
        imp = impact_bps(tranche, max(1e-9, profondeur_courante), k=k)
        if imp is None:
            return None
        total += imp
        consomme += tranche
    return total


def evaluer_decoupage(
    taille_notional: float,
    profondeur_notional: float,
    *,
    n_tranches: int = 4,
    liquidite_fraiche_par_tranche: float = 0.0,
    seuil_negligeable_bps: float = SEUIL_IMPACT_NEGLIGEABLE_BPS,
    k: float = K_IMPACT_DEFAUT_BPS,
) -> VerdictDecoupage:
    """Découper cet ordre vaut-il la peine ? Renvoie le gain mesuré et un verdict honnête."""
    unique = impact_bps(taille_notional, profondeur_notional, k=k)
    if unique is None:
        return VerdictDecoupage(None, None, None, False, "PROFONDEUR_INCONNUE")

    if unique < float(seuil_negligeable_bps):
        return VerdictDecoupage(
            unique, unique, 0.0, False,
            "IMPACT_NEGLIGEABLE_A_CE_NOTIONAL",   # le cas 500 $ : ce n'est pas le combat
        )

    decoupe = impact_decoupe_bps(
        taille_notional, profondeur_notional, n_tranches=n_tranches,
        liquidite_fraiche_par_tranche=liquidite_fraiche_par_tranche, k=k,
    )
    if decoupe is None:
        return VerdictDecoupage(unique, None, None, False, "PROFONDEUR_INCONNUE")

    gain = unique - decoupe
    if gain > GAIN_MINIMAL_UTILE_BPS:
        motif = "LE_DECOUPAGE_AIDE_GRACE_A_LA_LIQUIDITE_FRAICHE"
        aide = True
    else:
        motif = "CARNET_STATIQUE_LE_DECOUPAGE_N_AIDE_PAS"
        aide = False
    return VerdictDecoupage(unique, decoupe, gain, aide, motif)


__all__ = [
    "GAIN_MINIMAL_UTILE_BPS", "SEUIL_IMPACT_NEGLIGEABLE_BPS",
    "VerdictDecoupage", "evaluer_decoupage", "impact_decoupe_bps",
]
