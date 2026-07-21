"""LE COÛT ALL-IN DE L'ARBITRAGE — le forfait qui décidait de tout (P4-2, 21/07).

CE QUE LE FORFAIT CACHAIT
-------------------------
`arb_dislocation_paper` calculait son PnL avec `COUT_AR_BPS = 8.0`, une constante commentée
« 2 exécutions HL maker (1,5×2) + spread/slippage ~5 ». Deux erreurs dans ce commentaire :

  1. un aller-retour d'arbitrage, ce n'est pas 2 exécutions, c'est **4** — ouverture ET
     fermeture, sur **chacune** des deux venues ;
  2. il ne compte les frais que d'un côté. La jambe Binance en a aussi.

Re-pricing des 4 trades d'arbitrage réellement enregistrés :

    coût  7,0 bps  (les 4 fills passifs, frais seuls)   -> +0,1129 $   survit
    coût  8,0 bps  (le forfait en place)                -> +0,0929 $   survit
    coût 10,0 bps  (HL maker, Binance taker)            -> +0,0529 $   survit
    coût 13,0 bps  (idem + 2 bps de spread traversé)    -> **−0,0071 $   MEURT**
    coût 19,0 bps  (tout taker + spread)                -> −0,1271 $   meurt

**Tout le PnL positif de l'arbitrage tenait dans l'incertitude d'une constante que personne
n'avait mesurée.** Ce module la remplace par une décomposition qui se défend poste par poste.

L'HYPOTHÈSE D'EXÉCUTION EST LE VRAI PARAMÈTRE
---------------------------------------------
8 bps ne tient que si les **quatre** fills sont passifs. Or un trade de dislocation est une
**course** : l'écart se referme, c'est tout l'intérêt. Poster passivement sur les deux venues,
c'est accepter de ne pas être servi — et une jambe servie sans l'autre n'est pas une couverture,
c'est une position directionnelle nue.

Le défaut de ce module est donc `MODE_REALISTE` : passif là où l'on peut attendre (HL, on
choisit notre moment), agressif là où la couverture doit se compléter sous peine d'être à nu
(la seconde venue). Deny-by-default s'applique aux **hypothèses** comme aux données : quand on
ne sait pas si l'on sera servi passivement, on price comme si l'on ne l'était pas.

Passer à `MODE_TOUT_MAKER` est légitime — mais seulement contre une **mesure de taux de fill
passif**, pas contre un espoir. Le mode retenu est toujours reporté dans le verdict.

CE QUI N'EST PAS MESURÉ RESTE `None`
------------------------------------
Le spread réellement traversé et le slippage à la taille demandent le carnet des deux venues,
que ce module n'a pas. Ils sont donc soit fournis par l'appelant (mesurés), soit portés par une
**provision explicite** — jamais zéro. Un zéro fabriqué sur un poste de coût ment toujours dans
le sens qui arrange.

PAPER only : chiffrer un coût n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

#: frais documentés, tier 0, en bps par exécution.
FRAIS = {
    "HL": {"maker": 1.5, "taker": 4.5},
    "BINANCE": {"maker": 2.0, "taker": 5.0},
}

MODE_TOUT_MAKER = "TOUT_MAKER"
MODE_REALISTE = "REALISTE"          # passif où l'on peut attendre, agressif où il faut compléter
MODE_TOUT_TAKER = "TOUT_TAKER"

#: provision de spread traversé, par exécution AGRESSIVE, quand le carnet n'est pas fourni.
#: 1,0 bps est déjà optimiste : sur le carry, le spread pesait **3,3 × les frais**.
PROVISION_SPREAD_TAKER_BPS = 1.0
#: provision par exécution PASSIVE : on ne traverse pas, mais on subit l'adverse selection.
PROVISION_ADVERSE_PASSIF_BPS = 0.5

#: marge exigée AU-DESSUS du coût pour qu'un écart mérite qu'on le prenne. Ce n'est pas de la
#: prudence : c'est le prix de l'incertitude de mesure (fraîcheur, latence, jambe non servie).
MARGE_EXIGEE_BPS = 3.0


def _f(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x or x in (float("inf"), float("-inf")) else x


def modes_par_jambe(mode: str = MODE_REALISTE) -> dict[str, str]:
    """Qui est passif, qui est agressif, sur chacune des 4 exécutions."""
    if mode == MODE_TOUT_MAKER:
        return {"hl_entree": "maker", "hl_sortie": "maker",
                "bin_entree": "maker", "bin_sortie": "maker"}
    if mode == MODE_TOUT_TAKER:
        return {"hl_entree": "taker", "hl_sortie": "taker",
                "bin_entree": "taker", "bin_sortie": "taker"}
    # RÉALISTE : on peut attendre pour poser la jambe HL (on choisit le moment) ; la seconde
    # jambe doit se compléter sous peine d'être à nu -> on la price agressive.
    return {"hl_entree": "maker", "hl_sortie": "maker",
            "bin_entree": "taker", "bin_sortie": "taker"}


def decomposer(*, mode: str = MODE_REALISTE,
               spread_hl_bps: float | None = None,
               spread_bin_bps: float | None = None,
               slippage_bps: float | None = None) -> dict[str, Any]:
    """Le coût d'un aller-retour complet, poste par poste, sur les **4** exécutions.

    `spread_*` et `slippage_bps` sont les valeurs MESURÉES si l'appelant les a. Sinon une
    provision explicite s'applique — jamais zéro.
    """
    jambes = modes_par_jambe(mode)
    frais = {}
    total_frais = 0.0
    for jambe, m in jambes.items():
        venue = "HL" if jambe.startswith("hl") else "BINANCE"
        c = FRAIS[venue][m]
        frais[jambe] = {"venue": venue, "mode": m, "bps": c}
        total_frais += c

    n_taker = sum(1 for m in jambes.values() if m == "taker")
    n_maker = 4 - n_taker
    sh, sb = _f(spread_hl_bps), _f(spread_bin_bps)
    mesure = sh is not None or sb is not None
    if mesure:
        # spread mesuré : il ne se paie qu'aux exécutions AGRESSIVES de la venue concernée.
        spread = 0.0
        for jambe, m in jambes.items():
            if m != "taker":
                continue
            v = sh if jambe.startswith("hl") else sb
            spread += (v if v is not None else PROVISION_SPREAD_TAKER_BPS)
    else:
        spread = n_taker * PROVISION_SPREAD_TAKER_BPS
    adverse = n_maker * PROVISION_ADVERSE_PASSIF_BPS
    slip = _f(slippage_bps)
    total = total_frais + spread + adverse + (slip or 0.0)
    return {
        "mode": mode, "jambes": jambes, "frais_par_jambe": frais,
        "frais_bps": round(total_frais, 4),
        "spread_bps": round(spread, 4),
        "spread_mesure": bool(mesure),
        "adverse_selection_bps": round(adverse, 4),
        # non mesurable ici : il faut le carnet aux DEUX venues, à la taille demandée.
        "slippage_bps": slip,
        "slippage_mesure": slip is not None,
        "executions": 4, "taker": n_taker, "maker": n_maker,
        "cout_aller_retour_bps": round(total, 4),
        "postes_non_mesures": [p for p, ok in (("spread", mesure), ("slippage", slip is not None))
                               if not ok],
        "real_execution": False,
    }


def seuil_dynamique_bps(*, mode: str = MODE_REALISTE, marge_bps: float = MARGE_EXIGEE_BPS,
                        **mesures: Any) -> float:
    """Le seuil d'ouverture DÉRIVÉ du coût, au lieu d'une constante (P4-3).

    `SEUIL_OUVERTURE_BPS = 15` était un nombre choisi ; il ne bougeait pas quand le coût
    bougeait. Ici le seuil suit son coût : c'est la définition d'un seuil qui se défend.
    """
    c = decomposer(mode=mode, **mesures)["cout_aller_retour_bps"]
    return round(c + max(0.0, _f(marge_bps) or 0.0), 4)


def verdict(*, ecart_bps: float | None, mode: str = MODE_REALISTE,
            marge_bps: float = MARGE_EXIGEE_BPS, **mesures: Any) -> dict[str, Any]:
    """Cet écart couvre-t-il son coût all-in, marge comprise ? DENY-BY-DEFAULT."""
    e = _f(ecart_bps)
    d = decomposer(mode=mode, **mesures)
    seuil = round(d["cout_aller_retour_bps"] + max(0.0, _f(marge_bps) or 0.0), 4)
    base = {"cout": d, "seuil_bps": seuil, "marge_bps": marge_bps, "real_execution": False}
    if e is None:
        return {**base, "autorise": False, "motif": "ARB_ECART_ABSENT_NO_TRADE",
                "ecart_bps": None, "manque_bps": None}
    a = abs(e)
    return {**base, "ecart_bps": round(e, 4), "ecart_abs_bps": round(a, 4),
            "autorise": a >= seuil,
            "motif": "" if a >= seuil else "ARB_ECART_SOUS_LE_COUT_ALL_IN_NO_TRADE",
            "manque_bps": round(max(0.0, seuil - a), 4),
            "marge_nette_bps": round(a - d["cout_aller_retour_bps"], 4)}


#: en dessous de cet écart-type (bps) sur l'historique récent, l'écart est FIGÉ.
#: Mesuré le 21/07 : MKR affichait 71,44 bps sur **208 observations avec un écart-type de
#: 0,0000** — min = max, jamais un mouvement. Le seau 40+ bps convergeait à **0 %** (176 obs).
ECART_TYPE_MIN_BPS = 0.05
#: nombre d'observations en dessous duquel on ne juge pas : un écart-type sur 3 points ne dit rien.
OBSERVATIONS_MIN_VIVACITE = 20

MOTIF_FIGE = "ARB_ECART_FIGE_PRIX_SUSPECT_NO_TRADE"


def ecart_vivant(historique: Any, *, ecart_type_min_bps: float = ECART_TYPE_MIN_BPS,
                 observations_min: int = OBSERVATIONS_MIN_VIVACITE) -> dict[str, Any]:
    """Cet écart BOUGE-T-IL ? Sinon ce n'est pas une dislocation, c'est un prix mort.

    Un vrai écart de dislocation **fluctue** — c'est exactement ce qui le rend capturable. Un
    écart parfaitement immobile est un prix périmé, un contrat différent, ou un mauvais
    appariement (le carry connaît déjà ce défaut : `base aberrante ×3511` sur TRUMP).

    Mesure du 21/07, 38 coins : **37 vivants, 1 figé (MKR)**. Le figé était le plus gros écart
    de tout l'univers — donc le seul à passer le seuil — et il a perdu de l'argent.

    Données insuffisantes -> `vivant=None` : on s'abstient de juger, on ne condamne pas.
    """
    vals = [_f(x) for x in (historique or ())]
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if n < max(2, int(observations_min)):
        return {"vivant": None, "observations": n, "ecart_type_bps": None,
                "motif": "", "note": "trop peu d'observations pour juger la vivacite"}
    moy = sum(vals) / n
    sd = (sum((v - moy) ** 2 for v in vals) / n) ** 0.5
    fige = sd < float(ecart_type_min_bps)
    return {"vivant": not fige, "observations": n, "ecart_type_bps": round(sd, 6),
            "amplitude_bps": round(max(vals) - min(vals), 6),
            "motif": MOTIF_FIGE if fige else "",
            "note": ("ecart immobile sur %d observations (sigma %.4f bps) : prix perime, "
                     "contrat different ou mauvais appariement — rien a capturer" % (n, sd)
                     if fige else "")}


def repricer(trades: Any, *, notional_usd: float = 50.0,
             mode: str = MODE_REALISTE, **mesures: Any) -> dict[str, Any]:
    """Re-price des trades DÉJÀ enregistrés avec le coût honnête.

    Sert à répondre à la seule question qui compte : « ce résultat positif survit-il quand on
    arrête de sous-estimer le coût ? ». Chaque trade porte `ecart_entree_bps`/`ecart_sortie_bps`.
    """
    c = decomposer(mode=mode, **mesures)["cout_aller_retour_bps"]
    lignes, total = [], 0.0
    for t in (trades or ()):
        if not isinstance(t, dict):
            continue
        ei, eo = _f(t.get("ecart_entree_bps")), _f(t.get("ecart_sortie_bps"))
        if ei is None or eo is None:
            continue
        capture = abs(ei) - (abs(eo) if ei * eo > 0 else -abs(eo))
        pnl = round((capture - c) / 1e4 * float(notional_usd), 6)
        total += pnl
        lignes.append({"coin": t.get("coin"), "capture_bps": round(capture, 4),
                       "pnl_usd": pnl, "gagnant": pnl > 0})
    return {"mode": mode, "cout_aller_retour_bps": c, "notional_usd": notional_usd,
            "trades": len(lignes), "gagnants": sum(1 for x in lignes if x["gagnant"]),
            "total_usd": round(total, 6), "survit": total > 0, "lignes": lignes,
            "real_execution": False}


__all__ = ["FRAIS", "MODE_TOUT_MAKER", "MODE_REALISTE", "MODE_TOUT_TAKER",
           "PROVISION_SPREAD_TAKER_BPS", "PROVISION_ADVERSE_PASSIF_BPS", "MARGE_EXIGEE_BPS",
           "modes_par_jambe", "decomposer", "seuil_dynamique_bps", "verdict", "repricer"]
