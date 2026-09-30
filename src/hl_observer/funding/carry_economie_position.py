"""L'ÉCONOMIE D'UNE POSITION, JAMBE PAR JAMBE (P1-1, 21/07).

CE QUI MANQUAIT
---------------
L'audit du carry a dû répondre `DATA_MISSING` à cinq des quinze questions de la mission :
hedge ratio réel, delta résiduel en dollars, frais spot et perp séparés, spread par jambe,
slippage par jambe. La raison est simple : **la position ne stockait qu'un notionnel et un
coût d'entrée agrégé**. Impossible de dire *où* part l'argent.

Conséquence directe : on affirmait « delta-neutre » sur la foi d'un constructeur qui refuse
les positions déséquilibrées — c'est-à-dire **par construction, jamais par mesure**. Une
affirmation qu'on ne peut pas vérifier n'est pas une preuve, c'est une habitude.

CE QUE CE MODULE FAIT
---------------------
Il décompose, à l'ouverture, ce que la position coûte **par jambe** :

    frais_spot_bps   = maker spot  (4,0 bps, doc officielle HL tier 0)
    frais_perp_bps   = maker perp  (1,5 bps)
    spread_spot_bps  = ce que le VWAP d'achat paie AU-DESSUS du mid
    base_subie_bps   = la base à l'entrée (positive = elle nous PAIE)

et il conserve les **quantités par jambe**, seule façon de mesurer plus tard la dérive du
hedge (P1-2) au lieu de la supposer.

HONNÊTETÉ DU MODÈLE
-------------------
  * le **slippage perp** n'est PAS mesuré : on ne dispose pas du carnet perp à l'entrée.
    Il est déclaré `None`, jamais estimé à zéro — un zéro fabriqué mentirait sur le coût réel.
  * le hedge ratio vaut 1,0 **par construction** (`build_delta_neutral_position` refuse le
    déséquilibre). Le champ existe pour que la dérive PUISSE être mesurée ensuite ; il est
    étiqueté `MODELISE` tant qu'aucune quantité réelle ne l'a confirmé.
  * la somme des postes doit redonner le `cout_entree_bps` déjà calculé par le moteur. Si
    elle diverge, c'est le module qui a tort — un test le vérifie.

PAPER only : décomposer un coût n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.funding.delta_neutral_carry import (COUT_MAKER_2_JAMBES_BPS, MAKER_BPS,
                                                     MAKER_SPOT_BPS)

#: état du hedge ratio : mesuré sur des quantités réelles, ou imposé par le constructeur.
HEDGE_MESURE = "MESURE"
HEDGE_MODELISE = "MODELISE"


def _nombre(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f else f


def decomposer_entree(*, notional_usdt: float, base_bps: float | None,
                      perp_px: float | None = None, spot_px: float | None = None,
                      spot_mid_px: float | None = None) -> dict[str, Any]:
    """Le coût d'entrée, poste par poste. Aucun poste inventé : ce qui n'est pas mesurable
    reste `None`.

    `spot_px` est le prix de fill retenu (VWAP d'achat) ; `spot_mid_px` le mid au même
    instant. Leur écart EST le spread réellement payé sur la jambe spot — le seul poste
    qu'on sait isoler, et c'est justement celui qui pèse 3,3× les frais.
    """
    n = max(0.0, float(notional_usdt or 0.0))
    b = _nombre(base_bps)
    vwap, mid = _nombre(spot_px), _nombre(spot_mid_px)
    spread_spot = None
    if vwap is not None and mid is not None and mid > 0:
        spread_spot = round((vwap - mid) / mid * 1e4, 4)
    return {
        "frais_spot_bps": MAKER_SPOT_BPS,
        "frais_perp_bps": MAKER_BPS,
        "frais_2_jambes_bps": COUT_MAKER_2_JAMBES_BPS,
        "spread_spot_bps": spread_spot,
        # non mesurable : on ne dispose pas du carnet perp à l'entrée. `None`, jamais 0.
        "spread_perp_bps": None,
        "slippage_spot_bps": None,
        "slippage_perp_bps": None,
        "base_subie_bps": b,
        "frais_spot_usd": round(n * MAKER_SPOT_BPS / 1e4, 6),
        "frais_perp_usd": round(n * MAKER_BPS / 1e4, 6),
        "spread_spot_usd": (round(n * spread_spot / 1e4, 6)
                            if spread_spot is not None else None),
        "postes_non_mesures": ["spread_perp", "slippage_spot", "slippage_perp"],
    }


def quantites_par_jambe(*, notional_usdt: float, perp_px: float | None,
                        spot_px: float | None) -> dict[str, Any]:
    """Les quantités RÉELLES de chaque jambe. Sans elles, la neutralité ne peut être
    que supposée — et c'est exactement ce qu'on reprochait au reste du projet."""
    n = max(0.0, float(notional_usdt or 0.0))
    p, s = _nombre(perp_px), _nombre(spot_px)
    qte_perp = round(n / p, 10) if p and p > 0 else None
    qte_spot = round(n / s, 10) if s and s > 0 else None
    return {"quantite_perp": qte_perp, "quantite_spot": qte_spot,
            "prix_perp_entree": p, "prix_spot_entree": s}


def hedge_ratio(position: dict[str, Any]) -> dict[str, Any]:
    """{ratio, statut, delta_usd}. `ratio = notionnel spot / notionnel perp`.

    Statut `MESURE` seulement si les DEUX quantités et les DEUX prix existent. Sinon
    `MODELISE` : le constructeur impose l'égalité, on n'a rien vérifié.
    """
    qp, qs = _nombre(position.get("quantite_perp")), _nombre(position.get("quantite_spot"))
    pp = _nombre(position.get("prix_perp_courant")) or _nombre(position.get("prix_perp_entree"))
    ps = _nombre(position.get("prix_spot_courant")) or _nombre(position.get("prix_spot_entree"))
    if not (qp and qs and pp and ps and qp > 0 and pp > 0 and ps > 0):
        return {"ratio": 1.0, "statut": HEDGE_MODELISE, "delta_usd": None,
                "note": "quantites ou prix par jambe absents : neutralite SUPPOSEE, pas mesuree"}
    val_spot, val_perp = qs * ps, qp * pp
    return {"ratio": round(val_spot / val_perp, 6), "statut": HEDGE_MESURE,
            "delta_usd": round(val_spot - val_perp, 6),
            "note": "long spot %.4f $ vs short perp %.4f $" % (val_spot, val_perp)}


def enrichir(position: dict[str, Any], *, base_bps: float | None = None,
             perp_px: float | None = None, spot_px: float | None = None,
             spot_mid_px: float | None = None) -> dict[str, Any]:
    """Ajoute l'économie détaillée à une position, sans jamais écraser ce qui existe.
    Retourne une COPIE : une position est un fait, on ne la mute pas en passant."""
    p = dict(position)
    n = _nombre(p.get("notional_usdt")) or 0.0
    b = base_bps if base_bps is not None else _nombre(p.get("base_bps_entree"))
    p.update(decomposer_entree(notional_usdt=n, base_bps=b, perp_px=perp_px,
                               spot_px=spot_px, spot_mid_px=spot_mid_px))
    p.update(quantites_par_jambe(notional_usdt=n,
                                 perp_px=perp_px if perp_px is not None
                                 else _nombre(p.get("entry_perp_px")),
                                 spot_px=spot_px))
    p["hedge"] = hedge_ratio(p)
    return p


def coherence_avec_le_moteur(position: dict[str, Any],
                             tolerance_bps: float = 0.01) -> dict[str, Any]:
    """La décomposition redonne-t-elle le `cout_entree_bps` du moteur ?

    Le moteur calcule `cout_entree = frais_2_jambes − base`. Si notre somme diverge, c'est
    NOUS qui avons tort : un second calcul du même coût qui ne retombe pas sur le premier
    est un deuxième standard, et le projet en a déjà payé le prix.
    """
    moteur = _nombre(position.get("cout_entree_bps"))
    frais = _nombre(position.get("frais_2_jambes_bps"))
    base = _nombre(position.get("base_subie_bps"))
    if moteur is None or frais is None or base is None:
        return {"coherent": None, "motif": "donnee absente : rien a comparer"}
    recompose = frais - base
    ecart = abs(recompose - moteur)
    return {"coherent": ecart <= float(tolerance_bps), "ecart_bps": round(ecart, 6),
            "moteur_bps": moteur, "recompose_bps": round(recompose, 6)}


__all__ = ["HEDGE_MESURE", "HEDGE_MODELISE", "decomposer_entree", "quantites_par_jambe",
           "hedge_ratio", "enrichir", "coherence_avec_le_moteur"]
