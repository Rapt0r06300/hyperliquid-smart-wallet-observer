"""OPTIMISEUR DE CARRY — augmenter le PnL du carry SANS augmenter le risque (idées #1/#2/#4/#15/#16).

Tout est PUR et deny-by-default. On ne fabrique aucune donnee : entrees manquantes -> facteur neutre
ou sens NEUTRE (pas de carry). PAPER only, aucun ordre.

  * Y1 (#1)  cout_entree_optimise_bps : entree MAKER (rebate, pas de demi-spread) -> break-even plus
             rapide. Honnete : le maker n'est pas garanti d'etre rempli ; si non rempli en maker,
             l'appelant DOIT retomber sur le cout taker (on ne suppose pas un fill gratuit).
  * Y2 (#2)  sens_carry : funding franchement positif -> NORMAL (long spot/short perp) ; franchement
             negatif -> INVERSE (short spot/long perp, on encaisse le funding negatif) ; proche 0 -> NEUTRE.
  * Y4/Y15/Y16 (#4/#15/#16)  taille_carry : facteur de taille = z-score(spike) x Kelly-frac(edge/var)
             x vol-target(plus quand calme), borne [plancher, plafond]. Grossir les surs, pas les risques.
"""
from __future__ import annotations

from hl_observer.funding.funding_previsionnel import TAUX_INTERET_BPS_H

# --- Y1 : couts d'entree (bps). Defauts prudents ; l'appelant passe les vrais frais HL. ---
FRAIS_MAKER_1_JAMBE_BPS = 1.5     # maker HL par jambe (approx ; source = fees/hyperliquid_fees)
FRAIS_TAKER_1_JAMBE_BPS = 4.5     # taker HL par jambe
SEUIL_FUNDING_NEUTRE_BPS_H = 0.02  # sous ce |funding|, le carry ne vaut pas le coup (NEUTRE)


def cout_entree_optimise_bps(base_bps: float, *, maker: bool = True,
                             frais_maker_1_jambe_bps: float = FRAIS_MAKER_1_JAMBE_BPS,
                             frais_taker_1_jambe_bps: float = FRAIS_TAKER_1_JAMBE_BPS,
                             spread_spot_bps: float = 0.0, spread_perp_bps: float = 0.0) -> float:
    """Cout d'entree des 2 jambes (bps). En MAKER on paie le frais maker et PAS le demi-spread
    (on POSTE au meilleur prix) ; en TAKER on paie le frais taker + le demi-spread des 2 jambes.
    La base joue POUR nous si le perp est plus cher (base>0). Jamais < 0 (un cout negatif serait un
    cadeau : on plafonne a 0)."""
    if maker:
        frais = 2.0 * float(frais_maker_1_jambe_bps)
        demi_spread = 0.0
    else:
        frais = 2.0 * float(frais_taker_1_jambe_bps)
        demi_spread = 0.5 * (float(spread_spot_bps) + float(spread_perp_bps))
    return max(0.0, frais + demi_spread - float(base_bps))


def break_even_heures(cout_entree_bps: float, funding_bps_h: float) -> float | None:
    """Heures pour rembourser le cout d'entree via le funding horaire. None si funding <= 0."""
    f = abs(float(funding_bps_h))
    return (float(cout_entree_bps) / f) if f > 0 else None


# --- Y2 : sens du carry ---
def sens_carry(funding_bps_h: float | None, *, seuil_bps_h: float = SEUIL_FUNDING_NEUTRE_BPS_H) -> str:
    """NORMAL (funding+ franc) / INVERSE (funding- franc) / NEUTRE (proche 0 ou inconnu)."""
    if funding_bps_h is None:
        return "NEUTRE"
    f = float(funding_bps_h)
    if f > float(seuil_bps_h):
        return "NORMAL"       # long spot + short perp : le short encaisse le funding positif
    if f < -float(seuil_bps_h):
        return "INVERSE"      # short spot + long perp : le long encaisse le funding negatif
    return "NEUTRE"


def funding_encaisse_bps_h(funding_bps_h: float | None) -> float:
    """Ce qu'on ENCAISSE (>=0) une fois du bon cote : |funding| si franc, sinon 0."""
    if funding_bps_h is None:
        return 0.0
    return abs(float(funding_bps_h)) if sens_carry(funding_bps_h) != "NEUTRE" else 0.0


# --- Y4/Y15/Y16 : facteurs de taille (chacun neutre = 1.0 quand l'entree manque) ---
def facteur_zscore(zscore: float | None, funding_bps_h: float | None = None) -> float:
    """Y4 : funding qui spike (z eleve) -> on capte plus ; qui s'evapore (z tres bas) -> on reduit.

    🔴 GARDE DU PLANCHER (21/07, mesure) — un z-score calcule AU PLANCHER PROTOCOLAIRE ne
    mesure rien. La formule publique d'Hyperliquid est F = premium + clamp(0,125 − premium,
    ±5) : tant que |premium| < ~5 bps, F vaut EXACTEMENT 0,125 pour TOUS les coins. Un coin
    dont l'historique traine sous le plancher affiche alors un z eleve... alors qu'il n'y a,
    par construction de la venue, RIEN d'inhabituel a capter.

    Mesure du 21/07 sur les 8 coins de la shortlist, tous au plancher :
        correlation facteur_taille <-> rendement net = −0,596
    Autrement dit : on mettait le PLUS de capital sur les MOINS rentables (STABLE, rendement
    le plus faible, recevait le plus gros facteur 1,27 ; BTC, le meilleur, 1,01).

    Donc : au plancher (ou en dessous), le z-score n'a aucun contenu -> facteur neutre 1,0.
    Au-dessus, il redevient ce qu'il a toujours ete : un signal d'intensite du funding.
    Argument non fourni -> comportement d'avant (on ne casse aucun appelant).
    """
    if zscore is None:
        return 1.0
    if isinstance(funding_bps_h, (int, float)) and not isinstance(funding_bps_h, bool):
        if float(funding_bps_h) <= TAUX_INTERET_BPS_H:
            return 1.0
    z = float(zscore)
    if z >= 2.0:
        return 1.5
    if z <= -1.0:
        return 0.5
    return 1.0 + 0.25 * max(0.0, min(2.0, z))   # progressif entre 0 et +2


def facteur_kelly(edge_bps: float | None, variance_bps2: float | None, *,
                  fraction: float = 0.25, plafond: float = 1.5) -> float:
    """Y15 : Kelly fractionnaire ~ edge / variance, borne. Variance nulle/absente -> neutre (1.0)."""
    if edge_bps is None or variance_bps2 is None or float(variance_bps2) <= 0:
        return 1.0
    k = float(fraction) * float(edge_bps) / float(variance_bps2)
    return max(0.0, min(float(plafond), k))


def facteur_vol(vol_realisee: float | None, vol_cible: float | None, *, plafond: float = 1.5) -> float:
    """Y16 : vol-target = vol_cible / vol_realisee (plus de taille quand calme). Borne, neutre si absent."""
    if vol_realisee is None or vol_cible is None or float(vol_realisee) <= 0:
        return 1.0
    return max(0.2, min(float(plafond), float(vol_cible) / float(vol_realisee)))


def taille_carry(notional_base_usd: float, *, zscore: float | None = None,
                 edge_bps: float | None = None, variance_bps2: float | None = None,
                 vol_realisee: float | None = None, vol_cible: float | None = None,
                 plancher: float = 0.25, plafond: float = 2.0) -> float:
    """Notional final = base x (z-score x Kelly x vol-target), borne [plancher, plafond] x base.
    Deny-by-default : chaque entree absente -> son facteur = 1.0 (aucune amplification fabriquee)."""
    f = facteur_zscore(zscore) * facteur_kelly(edge_bps, variance_bps2) * facteur_vol(vol_realisee, vol_cible)
    f = max(float(plancher), min(float(plafond), f))
    return max(0.0, float(notional_base_usd)) * f


__all__ = [
    "cout_entree_optimise_bps", "break_even_heures", "sens_carry", "funding_encaisse_bps_h",
    "facteur_zscore", "facteur_kelly", "facteur_vol", "taille_carry",
    "FRAIS_MAKER_1_JAMBE_BPS", "FRAIS_TAKER_1_JAMBE_BPS", "SEUIL_FUNDING_NEUTRE_BPS_H",
]
