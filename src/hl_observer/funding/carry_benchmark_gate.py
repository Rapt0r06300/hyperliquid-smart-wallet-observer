"""LA PORTE DU COÛT D'OPPORTUNITÉ — battre l'alternative, pas seulement zéro (21/07).

LE CONSTAT QUI L'A RENDUE NÉCESSAIRE
------------------------------------
Mesure de ce jour, sur les positions RÉELLEMENT ouvertes :

    12 positions · notionnel 2 819 $ · marge immobilisée 1 343,61 $
    funding de CHACUNE : 0,1250 bps/h   ->   **12/12 au plancher protocolaire**
    journal de scans : 580 lectures sur 20 coins, **580 au plancher, 0 au-dessus**

Le plancher n'est pas un taux de marché. C'est ce que Hyperliquid verse *quand personne ne
paie pour être long* : `F = premium + clamp(0,125 − premium, ±5 bps/h)`. À 0,125 bps/h, il n'y
a aucune demande à capter — on ramasse une subvention protocolaire.

L'ARITHMÉTIQUE, DÉRIVÉE ET NON CHOISIE
--------------------------------------
Sur la durée de vie plausible d'une position (`PLAFOND_COHERENT_H` = 248 h, déjà dérivé) :

    revenu = funding × H          coût = entrée (~12,5 bps) + sortie (11,0 bps maker 2 jambes)
    APR net = (revenu − coût) / H × 24 × 365

        funding 0,125 bps/h (plancher) ->  APR brut 10,95 %  ->  **APR net 2,65 %**
        funding 0,266 bps/h            ->  APR brut 23,30 %  ->  APR net 15,00 %

Le benchmark n'est pas une opinion : **le vault HLP paie 15 à 30 % APR** (donnée publique 2026,
loi `hlp_benchmark`, verdict REFUTE — c'est-à-dire que HLP nous bat). Un dépôt passif, sans
jambe spot, sans risque de base, sans frais de sortie, rend plus que notre carry au plancher.

    -> il faut **0,2660 bps/h, soit 2,13 × le plancher**, juste pour ÉGALER le bas de HLP.

Un rendement positif mais dominé n'est pas un gain : c'est du capital mal placé. La loi
`rendement_negatif_domine` disait déjà que le sizing ne change pas le signe ; celle-ci dit que
le signe ne suffit pas — il faut battre l'alternative disponible.

CE QUE CETTE PORTE N'EST PAS
----------------------------
Elle ne promet aucun gain. Elle **empêche d'immobiliser du capital sous l'alternative**, ce qui
est une chose différente et beaucoup plus modeste. Dans le régime mesuré aujourd'hui, elle
refusera très probablement tout : c'est le bon résultat. Ne pas ouvrir n'a jamais coûté un
dollar ; les 29 fermetures subies du 18-19/07 en ont coûté 5,07.

HONNÊTETÉ SUR LE BENCHMARK
--------------------------
HLP n'est **pas** delta-neutre : il porte du risque directionnel et des drawdowns de 5 à 12 %.
Comparer un carry neutre à HLP est donc *sévère*. On assume : on prend la **borne basse** (15 %)
et on autorise un abattement de risque explicite — mais tout abattement est ENREGISTRÉ dans le
verdict (`abattement_risque_pct`), pour qu'on ne puisse jamais gagner une comparaison en
baissant discrètement la barre. C'est la même discipline que `carry_backtest`, qui refuse tout
gain provenant d'une baisse de `securite_liquidation`.

PAPER only : refuser d'ouvrir n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.funding.delta_neutral_carry import COUT_MAKER_2_JAMBES_BPS

#: plancher protocolaire Hyperliquid : le taux versé en l'ABSENCE de demande.
PLANCHER_PROTOCOLAIRE_BPS_H = 0.125
#: borne BASSE du rendement public du vault HLP (loi `hlp_benchmark`, donnée 2026).
BENCHMARK_APR_PCT = 15.0
#: durée de vie plausible d'une position — déjà dérivée ailleurs (`PLAFOND_COHERENT_H`).
HORIZON_DEFAUT_H = 248.0
#: coût d'entrée observé (frais + spread) quand la mesure par position n'est pas fournie.
COUT_ENTREE_OBSERVE_BPS = 12.5

MOTIF_DOMINE = "RENDEMENT_DOMINE_PAR_BENCHMARK_NO_TRADE"
MOTIF_PLANCHER = "FUNDING_AU_PLANCHER_PROTOCOLAIRE_NO_TRADE"
MOTIF_DONNEE = "RENDEMENT_INCALCULABLE_DONNEE_ABSENTE_NO_TRADE"

#: marge au-dessus du plancher à partir de laquelle on considère qu'il y a une VRAIE demande.
#: 0,01 bps/h = 8 % du plancher : au-delà du bruit d'arrondi de l'API, en deçà de tout signal.
MARGE_HORS_PLANCHER_BPS = 0.01


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x or x in (float("inf"), float("-inf")) else x


def apr_net_pct(*, funding_bps_h: float, horizon_h: float = HORIZON_DEFAUT_H,
                cout_entree_bps: float = COUT_ENTREE_OBSERVE_BPS,
                cout_sortie_bps: float = COUT_MAKER_2_JAMBES_BPS) -> float | None:
    """Le rendement net ANNUALISÉ d'une position tenue `horizon_h`, coûts d'aller ET de retour
    déduits. `None` si l'horizon n'a pas de sens — on ne divise pas par un trou."""
    f, h = _f(funding_bps_h), _f(horizon_h)
    if f is None or h is None or h <= 0:
        return None
    ce = _f(cout_entree_bps)
    cs = _f(cout_sortie_bps)
    if ce is None or cs is None:
        return None
    net_bps = f * h - (ce + cs)
    return round(net_bps / h * 24.0 * 365.0 / 100.0, 4)


def funding_requis_bps_h(*, apr_cible_pct: float = BENCHMARK_APR_PCT,
                         horizon_h: float = HORIZON_DEFAUT_H,
                         cout_entree_bps: float = COUT_ENTREE_OBSERVE_BPS,
                         cout_sortie_bps: float = COUT_MAKER_2_JAMBES_BPS) -> float | None:
    """Le funding minimal qui atteint `apr_cible_pct`. **Inversion exacte** de `apr_net_pct`,
    pas une recherche numérique : un seuil qu'on ne sait pas recalculer à la main finit par
    devenir une constante magique que personne n'ose toucher."""
    h = _f(horizon_h)
    ce, cs = _f(cout_entree_bps), _f(cout_sortie_bps)
    a = _f(apr_cible_pct)
    if h is None or h <= 0 or ce is None or cs is None or a is None:
        return None
    # apr = (f·h − C)/h · 8760/100  =>  f = apr·100/8760 + C/h
    return round(a * 100.0 / 8760.0 + (ce + cs) / h, 6)


def evaluer(*, coin: str, funding_bps_h: float | None,
            horizon_h: float = HORIZON_DEFAUT_H,
            cout_entree_bps: float | None = None,
            benchmark_apr_pct: float = BENCHMARK_APR_PCT,
            abattement_risque_pct: float = 0.0) -> dict[str, Any]:
    """Ce carry bat-il l'alternative disponible ? DENY-BY-DEFAULT.

    `abattement_risque_pct` reconnaît que HLP porte un risque directionnel qu'un carry neutre
    n'a pas. Il est **toujours reporté dans le verdict** : on ne doit jamais pouvoir gagner une
    comparaison en baissant la barre sans que ça se voie.
    """
    f = _f(funding_bps_h)
    ce = _f(cout_entree_bps)
    if ce is None:
        ce = COUT_ENTREE_OBSERVE_BPS
    ab = max(0.0, _f(abattement_risque_pct) or 0.0)
    seuil_apr = max(0.0, (_f(benchmark_apr_pct) or 0.0) - ab)
    base = {"coin": str(coin or "").upper(), "benchmark_apr_pct": benchmark_apr_pct,
            "abattement_risque_pct": ab, "seuil_apr_pct": round(seuil_apr, 4),
            "horizon_h": horizon_h, "cout_entree_bps": ce,
            "cout_sortie_bps": COUT_MAKER_2_JAMBES_BPS, "real_execution": False}
    if f is None:
        return {**base, "autorise": False, "motif": MOTIF_DONNEE, "apr_net_pct": None,
                "funding_bps_h": None,
                "explication": "funding absent : on ne compare pas un trou a un benchmark"}
    apr = apr_net_pct(funding_bps_h=f, horizon_h=horizon_h, cout_entree_bps=ce)
    requis = funding_requis_bps_h(apr_cible_pct=seuil_apr, horizon_h=horizon_h,
                                  cout_entree_bps=ce)
    out = {**base, "funding_bps_h": round(f, 6), "apr_net_pct": apr,
           "funding_requis_bps_h": requis,
           "multiple_du_plancher": (round(f / PLANCHER_PROTOCOLAIRE_BPS_H, 3)
                                    if PLANCHER_PROTOCOLAIRE_BPS_H else None),
           "multiple_requis": (round(requis / PLANCHER_PROTOCOLAIRE_BPS_H, 3)
                               if requis and PLANCHER_PROTOCOLAIRE_BPS_H else None)}
    # 1) au plancher = personne ne paie. Refus NOMMÉ à part : ce n'est pas « un peu trop bas »,
    #    c'est l'absence totale de demande, et le motif doit le dire pour être lisible au ledger.
    if f <= PLANCHER_PROTOCOLAIRE_BPS_H + MARGE_HORS_PLANCHER_BPS:
        return {**out, "autorise": False, "motif": MOTIF_PLANCHER,
                "explication": ("funding %.4f bps/h = plancher protocolaire : personne ne paie "
                                "pour etre long. APR net %.2f%% vs benchmark %.1f%%"
                                % (f, apr if apr is not None else float("nan"), seuil_apr))}
    if apr is None:
        return {**out, "autorise": False, "motif": MOTIF_DONNEE,
                "explication": "APR incalculable : horizon ou couts absents"}
    if apr < seuil_apr:
        return {**out, "autorise": False, "motif": MOTIF_DOMINE,
                "explication": ("APR net %.2f%% < benchmark %.2f%% : ce capital rendrait plus "
                                "ailleurs. Il faudrait %.4f bps/h (x%.2f le plancher)"
                                % (apr, seuil_apr, requis or 0.0,
                                   (requis or 0.0) / PLANCHER_PROTOCOLAIRE_BPS_H))}
    return {**out, "autorise": True, "motif": "",
            "explication": "APR net %.2f%% >= benchmark %.2f%%" % (apr, seuil_apr)}


def resume_portefeuille(positions: Any, *, benchmark_apr_pct: float = BENCHMARK_APR_PCT
                        ) -> dict[str, Any]:
    """Combien de nos positions VIVANTES sont dominées par l'alternative, et pour quel capital.

    Une porte ne protège que les ouvertures FUTURES. Ce résumé dit ce que le portefeuille déjà
    ouvert vaut face au benchmark — sans quoi on croirait le problème réglé alors qu'il dort
    encore dans le book.
    """
    lignes = [p for p in (positions or ()) if isinstance(p, dict)]
    if not lignes:
        return {"positions": 0, "dominees": 0, "marge_dominee_usd": 0.0, "vide": True}
    dom, marge, notion, details = 0, 0.0, 0.0, []
    for p in lignes:
        n = _f(p.get("notional_usdt")) or 0.0
        usd_h = _f(p.get("taux_accrual_usd_h"))
        f = _f(p.get("funding_bps_h"))
        if f is None and usd_h is not None and n > 0:
            f = usd_h / n * 1e4          # le panneau publie des $/h : on reconvertit en bps/h
        v = evaluer(coin=str(p.get("coin") or ""), funding_bps_h=f,
                    benchmark_apr_pct=benchmark_apr_pct)
        notion += n
        if not v["autorise"]:
            dom += 1
            marge += _f(p.get("marge_usdt")) or 0.0
            details.append({"coin": v["coin"], "apr_net_pct": v["apr_net_pct"],
                            "motif": v["motif"]})
    return {"positions": len(lignes), "dominees": dom,
            "part_dominee_pct": round(100.0 * dom / len(lignes), 1),
            "marge_dominee_usd": round(marge, 2), "notionnel_usd": round(notion, 2),
            "benchmark_apr_pct": benchmark_apr_pct, "details": details[:20], "vide": False}


__all__ = ["PLANCHER_PROTOCOLAIRE_BPS_H", "BENCHMARK_APR_PCT", "HORIZON_DEFAUT_H",
           "COUT_ENTREE_OBSERVE_BPS", "MARGE_HORS_PLANCHER_BPS", "MOTIF_DOMINE",
           "MOTIF_PLANCHER", "MOTIF_DONNEE", "apr_net_pct", "funding_requis_bps_h",
           "evaluer", "resume_portefeuille"]
