"""ALLOCATION PAR RENDEMENT NET — arrêter de mettre le plus d'argent sur les moins rentables.

LA MESURE QUI A DÉCLENCHÉ CE MODULE (21/07)
-------------------------------------------
Positions vivantes, marge engagée VS rendement net journalier déjà calculé par le moteur :

    BTC      net 2,221 bps/j   ->  marge   25 $     (le MEILLEUR, le MOINS financé)
    STABLE   net 1,326 bps/j   ->  marge  126 $     (parmi les pires, le PLUS financé)
    corrélation facteur_taille <-> rendement net  =  −0,596

Le capital n'était pas mal réparti par hasard : `marge_par_position` divise le capital en
parts ÉGALES, et le seul modulateur (`facteur_taille`) est bâti sur le z-score du funding —
qui mesure « ce funding est-il inhabituel POUR CE COIN », une question sans rapport avec
« ce coin rapporte-t-il plus par dollar engagé ». Au plancher protocolaire, il mesurait même
du bruit (garde posée le même jour dans `carry_optimizer.facteur_zscore`).

CE QUE FAIT CE MODULE
---------------------
Il répartit le capital déployable proportionnellement à `gain_net_24h_bps ** exposant` —
le rendement net PAR DOLLAR DE CAPITAL IMMOBILISÉ, déjà calculé par `evaluer_carry_neutre`
(il contient donc DÉJÀ le levier, le coût d'entrée, la base et le verrou de liquidation).
Aucune nouvelle estimation, aucun paramètre inventé : on se contente d'utiliser un nombre
qu'on calculait déjà et qu'on jetait.

L'EXPOSANT, ET POURQUOI PAS PLUS
--------------------------------
Mesuré sur les 8 coins du 21/07 (gain du rendement moyen pondéré vs l'allocation actuelle) :

    part égale        +1,0 %      |   net^3   +14,9 %  (poids max 32 %)
    net^1             +5,4 %      |   net^5   +20,5 %  (poids max 40 % — au plafond)
    net^2            +10,0 %      |   « tout sur les 2 meilleurs »  +23,9 %

On prend **exposant 3** : la quasi-totalité du gain atteignable sans coller au plafond de
concentration. Aller plus loin achèterait ~9 points de rendement contre un risque
mono-coin (dépeg d'un token Unit, panne d'oracle, retournement de funding) que rien ne
compense — un carry delta-neutre a peu de variance directionnelle, mais ses accidents sont
COIN-SPÉCIFIQUES, donc concentrer les concentre aussi.

CE QUE ÇA NE FAIT PAS
---------------------
Ça n'augmente aucun levier, donc aucune distance de liquidation ne bouge. Ça ne crée pas de
rendement : ça déplace le même capital vers les lignes qui rapportent plus. Un rendement net
négatif reçoit ZÉRO (il ne devrait pas être ouvert du tout) — la barre n'est jamais baissée.

PAPER only : répartir une simulation n'est pas passer un ordre.
"""
from __future__ import annotations

from hl_observer.funding.carry_marge_dynamique import (MARGE_MAX_USD, MARGE_MIN_USD,
                                                       PART_MAX_PAR_COIN, RESERVE_FRAC_DEFAUT,
                                                       marge_par_position)

#: mesuré le 21/07 : +14,9 % de rendement pondéré sans coller au plafond de concentration.
EXPOSANT_DEFAUT = 3.0


def poids_par_rendement(net_par_coin: dict[str, float | None], *,
                        exposant: float = EXPOSANT_DEFAUT,
                        part_max_par_coin: float = PART_MAX_PAR_COIN) -> dict[str, float]:
    """{coin: poids} sommant à 1, ∝ net**exposant, plafonné par coin (excédent redistribué).

    Rendement absent, non numérique ou ≤ 0 -> poids ZÉRO (deny-by-default : on ne finance pas
    ce qu'on ne sait pas mesurer, et on ne finance pas une ligne qui perd). Si AUCUN coin n'a
    de rendement positif, retourne {} — l'appelant retombe alors sur la marge par défaut.
    """
    bruts: dict[str, float] = {}
    for coin, net in (net_par_coin or {}).items():
        if not coin or isinstance(net, bool) or not isinstance(net, (int, float)):
            continue
        v = float(net)
        if v != v or v <= 0.0:                      # NaN ou ≤ 0
            continue
        bruts[str(coin)] = v ** max(0.0, float(exposant))
    total = sum(bruts.values())
    if total <= 0.0:
        return {}
    cap = max(0.05, min(1.0, float(part_max_par_coin)))
    poids = {c: v / total for c, v in bruts.items()}
    # water-filling : on écrête au plafond et on redistribue au prorata sur les non-écrêtés.
    for _ in range(64):
        depasse = {c for c, v in poids.items() if v > cap + 1e-12}
        if not depasse:
            break
        surplus = sum(poids[c] - cap for c in depasse)
        libre = sum(v for c, v in poids.items() if c not in depasse)
        if libre <= 0.0:                            # tout le monde au plafond -> parts égales
            return {c: round(1.0 / len(poids), 8) for c in poids}
        poids = {c: (cap if c in depasse else v + surplus * v / libre)
                 for c, v in poids.items()}
    total = sum(poids.values()) or 1.0
    return {c: round(v / total, 8) for c, v in poids.items()}


def allouer_marges(net_par_coin: dict[str, float | None], *, capital_usd: float | None,
                   n_positions_visees: int | None = None,
                   marge_defaut_usd: float = 50.0,
                   exposant: float = EXPOSANT_DEFAUT,
                   reserve_frac: float = RESERVE_FRAC_DEFAUT,
                   part_max_par_coin: float = PART_MAX_PAR_COIN,
                   marge_min_usd: float = MARGE_MIN_USD,
                   marge_max_usd: float = MARGE_MAX_USD) -> dict[str, float]:
    """{coin: marge_usd}. La marge PAR COIN, pondérée par le rendement net.

    Garde-fous identiques à `marge_par_position` (c'est le même capital, les mêmes règles) :
      * réserve intouchable ; plafond de concentration ; plafond dur ;
      * une part sous le plancher est mise à ZÉRO plutôt qu'à une taille insignifiante — et
        son capital est redistribué aux autres (MOINS de positions correctement dimensionnées
        vaut mieux que N positions qui ne paient même pas leurs frais fixes) ;
      * capital inconnu / aucun rendement positif -> marge par défaut pour tout le monde
        (on ne devine JAMAIS un capital, et on ne dégrade pas le comportement existant).
    """
    coins = [str(c) for c in (net_par_coin or {}) if c]
    if not coins:
        return {}
    defaut = marge_par_position(capital_usd=capital_usd,
                                n_positions_visees=int(n_positions_visees or len(coins)),
                                marge_defaut_usd=marge_defaut_usd, reserve_frac=reserve_frac,
                                part_max_par_coin=part_max_par_coin, marge_min_usd=marge_min_usd,
                                marge_max_usd=marge_max_usd)
    if not isinstance(capital_usd, (int, float)) or isinstance(capital_usd, bool):
        return {c: defaut for c in coins}
    capital = float(capital_usd)
    if capital != capital or capital <= 0:
        return {c: defaut for c in coins}

    poids = poids_par_rendement(net_par_coin, exposant=exposant,
                                part_max_par_coin=part_max_par_coin)
    if not poids:
        return {c: defaut for c in coins}

    deployable = capital * (1.0 - max(0.0, min(0.9, float(reserve_frac))))
    marges = {c: deployable * w for c, w in poids.items()}
    # plancher : on coupe les miettes et on redistribue leur capital aux lignes qui restent.
    for _ in range(len(marges) + 1):
        petits = [c for c, m in marges.items() if m < float(marge_min_usd)]
        if not petits or len(petits) == len(marges):
            break
        for c in petits:
            marges.pop(c)
        restant = poids_par_rendement({c: net_par_coin[c] for c in marges}, exposant=exposant,
                                      part_max_par_coin=part_max_par_coin)
        marges = {c: deployable * w for c, w in restant.items()}
    # dernier recours : capital trop petit pour QUI QUE CE SOIT -> une seule ligne au plancher.
    if marges and all(m < float(marge_min_usd) for m in marges.values()):
        meilleur = max(marges, key=lambda c: float(net_par_coin[c] or 0.0))
        marges = {meilleur: min(float(marge_min_usd), deployable)}
    sortie = {c: round(min(m, float(marge_max_usd)), 2) for c, m in marges.items() if m > 0}
    # les coins écartés (rendement absent ou ≤ 0) reçoivent 0 : explicite, jamais implicite.
    for c in coins:
        sortie.setdefault(c, 0.0)
    return sortie


def diagnostic(net_par_coin: dict[str, float | None], marges: dict[str, float]) -> dict:
    """Ce que l'allocation a fait, en clair — pour le dashboard, le rapport et l'audit.
    Un nombre qu'on ne peut pas remonter à un rapport finira par mentir."""
    finances = {c: m for c, m in (marges or {}).items() if m > 0}
    total = sum(finances.values())
    nets = {c: float(net_par_coin.get(c) or 0.0) for c in finances}
    pondere = (sum(finances[c] * nets[c] for c in finances) / total) if total > 0 else 0.0
    egal = (sum(nets.values()) / len(nets)) if nets else 0.0
    return {
        "coins_finances": len(finances),
        "coins_ecartes": sorted(c for c, m in (marges or {}).items() if not m),
        "capital_alloue_usd": round(total, 2),
        "rendement_pondere_bps_j": round(pondere, 4),
        "rendement_part_egale_bps_j": round(egal, 4),
        "gain_vs_part_egale_pct": round(100.0 * (pondere / egal - 1.0), 2) if egal > 0 else None,
        "meilleur": max(nets, key=lambda c: nets[c]) if nets else None,
        "regle": "marge ∝ gain_net_24h_bps ** %g, plafond %.0f %% par coin, plancher %.0f $"
                 % (EXPOSANT_DEFAUT, 100 * PART_MAX_PAR_COIN, MARGE_MIN_USD),
    }


__all__ = ["EXPOSANT_DEFAUT", "poids_par_rendement", "allouer_marges", "diagnostic"]
