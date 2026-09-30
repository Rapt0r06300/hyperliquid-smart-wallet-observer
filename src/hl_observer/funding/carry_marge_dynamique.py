"""MARGE DYNAMIQUE DU CARRY — le seul levier de revenu qui n'augmente PAS le risque de liquidation.

LE CONSTAT (19/07)
------------------
    marge 50 $ × levier 1,5 = notional 75 $
    funding 0,125 bps/h  ->  0,00094 $/h  =  2,25 centimes / JOUR

Flo : « le PnL ne bouge jamais ». Il ne bougeait pas parce qu'il était **invisible** : 2 centimes
par jour, sur un dashboard à deux décimales, c'est zéro. Et sur 1 000 $ d'equity, on n'utilisait
que 75 $ — 92 % du capital dormait.

POURQUOI PAS SIMPLEMENT MONTER LE LEVIER
----------------------------------------
J'avais d'abord proposé « 1,5 -> 3, ça double le revenu ». **C'était léger de ma part.** Le levier
de 1,5 n'est pas arbitraire : il vient de la pire hausse MESURÉE sur HYPE (~29 %). À levier 3, la
jambe perp short serait liquidée sur ce même mouvement. Monter le levier, c'est acheter du revenu
avec du risque de ruine.

LA MARGE, ELLE, EST GRATUITE EN RISQUE
--------------------------------------
    notional = marge × levier
La distance à la liquidation dépend du **levier**, pas de la taille. Doubler la marge à levier
constant double le funding encaissé **sans rapprocher d'un centime le prix de liquidation**.
Le break-even en heures ne bouge pas non plus (coûts et revenus scalent ensemble) — seul le
montant en dollars devient visible.

CE QUE ÇA NE FAIT PAS
---------------------
Ça ne rend PAS une stratégie perdante gagnante : ça multiplie ce qui existe, dans les deux sens.
Si le carry est marginalement positif, il le devient visiblement ; s'il est négatif, la perte
grandit aussi. C'est pour ça que ce module vient APRÈS l'anti-churn, jamais avant.

GARDE-FOUS (aucun n'est décoratif)
----------------------------------
  * réserve de marge intouchable (on ne déploie jamais 100 % du capital) ;
  * plafond par coin : une position ne prend jamais tout le capital déployable ;
  * plancher : en dessous, la position n'a aucun sens (frais fixes, notionnel minimum de 10 $) ;
  * capital inconnu -> on retombe sur la marge par défaut. On ne devine pas un capital.

PAPER only : dimensionner une simulation n'est pas passer un ordre.
"""
from __future__ import annotations

#: part du capital jamais déployée (cohérent avec risk/margin_reserve).
RESERVE_FRAC_DEFAUT = 0.2
#: une seule position ne prend jamais plus que cette part du capital déployable (concentration).
PART_MAX_PAR_COIN = 0.40
#: en dessous, le notionnel devient trop petit pour être réaliste (minimum HL = 10 $).
MARGE_MIN_USD = 25.0
#: garde-fou dur : on ne dimensionne jamais au-delà, même si le calcul le suggère.
MARGE_MAX_USD = 2_000.0


def marge_par_position(*, capital_usd: float | None, n_positions_visees: int,
                       marge_defaut_usd: float = 50.0,
                       reserve_frac: float = RESERVE_FRAC_DEFAUT,
                       part_max_par_coin: float = PART_MAX_PAR_COIN,
                       marge_min_usd: float = MARGE_MIN_USD,
                       marge_max_usd: float = MARGE_MAX_USD) -> float:
    """La marge à engager PAR position, capital réel et concentration pris en compte.

    `capital_usd` absent ou absurde -> `marge_defaut_usd` (on ne devine JAMAIS un capital ;
    inventer un capital, ce serait inventer un PnL).
    """
    if not isinstance(capital_usd, (int, float)) or isinstance(capital_usd, bool):
        return float(marge_defaut_usd)
    capital = float(capital_usd)
    if capital != capital or capital <= 0:                 # NaN ou <= 0
        return float(marge_defaut_usd)

    deployable = capital * (1.0 - max(0.0, min(0.9, float(reserve_frac))))
    n = max(1, int(n_positions_visees))
    part_egale = deployable / n
    plafond_coin = deployable * max(0.05, min(1.0, float(part_max_par_coin)))

    marge = min(part_egale, plafond_coin, float(marge_max_usd))
    if marge < float(marge_min_usd):
        # Trop peu de capital pour cette répartition : on ne descend pas sous le plancher, on
        # préfère MOINS de positions correctement dimensionnées que N positions insignifiantes.
        marge = min(float(marge_min_usd), deployable, float(marge_max_usd))
    return round(max(0.0, marge), 2)


def revenu_journalier_usd(*, notional_usd: float, funding_bps_h: float) -> float:
    """Ce que la position rapporte PAR JOUR, en dollars. Le chiffre qui manquait au dashboard.

    75 $ à 0,125 bps/h -> 0,0225 $/jour. Affiché, ce nombre aurait évité une journée de doute.
    """
    return float(notional_usd) * float(funding_bps_h) / 1e4 * 24.0


__all__ = ["marge_par_position", "revenu_journalier_usd", "RESERVE_FRAC_DEFAUT",
           "PART_MAX_PAR_COIN", "MARGE_MIN_USD", "MARGE_MAX_USD"]
