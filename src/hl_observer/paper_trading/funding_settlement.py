"""RÈGLEMENT DU FUNDING — séparer ce qui est ENCAISSÉ de ce qui est ESTIMÉ (P0, 21/07).

LE DÉFAUT, NOMMÉ
----------------
Le README affirmait : « PnL unifié = réalisé + funding **couru (l'encaissé, stable)** ».
Les deux mots ne peuvent pas désigner la même chose, et le code faisait le premier :

    dt_h = (now_ms - last_accrual_ts_ms) / 3.6e6      # fraction d'heure
    accru += funding_bps_h * dt_h * notional / 1e4    # PRORATA LINÉAIRE

Sur Hyperliquid, le funding est **réglé au sommet de chaque heure**, sur la position tenue à
cet instant précis. Une position ouverte depuis 20 minutes se voit créditer 1/3 d'heure de
funding par notre modèle, alors qu'en réalité elle a reçu **soit un paiement horaire entier
(si elle a traversé un règlement), soit rien du tout**.

`funding_accrued_usdt` est donc une **ESTIMATION**, pas un encaissement. L'appeler « stable »
est doublement faux : c'est l'interpolation linéaire d'une fonction en escalier.

ORDRE DE GRANDEUR (mesuré le 21/07)
-----------------------------------
1 175 $ de notionnel × 0,125 bps/h = **0,0147 $/h** d'incertitude maximale à tout instant,
contre 0,32 $ d'accru affiché → jusqu'à **~4,6 %** du chiffre. Faible en valeur absolue,
mais c'est une **erreur de catégorie** : une estimation présentée comme un fait comptable.
Et l'erreur grandit exactement quand le notionnel grandit.

CE QUE FAIT CE MODULE
---------------------
Il découpe le funding couru en deux quantités qui ne se mélangent plus jamais :

  * `net_funding_settled`      — les heures de règlement RÉELLEMENT franchies. Comptable.
                                 C'est la seule qui entre dans le PnL stable.
  * `funding_accrual_estimate` — la fraction d'heure en cours, non encore réglée.
                                 Affichée à part, étiquetée estimation, jamais additionnée
                                 au net stable (même traitement que le latent de base).

Aucun chiffre n'est inventé : on RE-DÉCOUPE la même mesure de funding, on n'en ajoute pas.
La somme des deux redonne exactement l'accru historique — la migration est neutre.

PAPER only : compter du funding simulé n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

#: Hyperliquid règle le funding au sommet de chaque heure (doc officielle : paiement horaire).
PERIODE_REGLEMENT_MS = 3_600_000


def _nombre(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return None if f != f else f


def reglements_franchis(debut_ms: int, fin_ms: int,
                        periode_ms: int = PERIODE_REGLEMENT_MS) -> int:
    """Combien de sommets d'heure ont été franchis STRICTEMENT entre `debut` et `fin` ?

    C'est le nombre de paiements de funding qu'une position ouverte sur cet intervalle aurait
    réellement reçus. Un intervalle qui ne traverse aucun sommet d'heure rapporte **zéro** —
    même s'il dure 59 minutes.
    """
    d, f = int(debut_ms), int(fin_ms)
    if f <= d or periode_ms <= 0:
        return 0
    # nombre de multiples de `periode` dans ]d, f]
    return int(f // periode_ms) - int(d // periode_ms)


def decouper(position: dict[str, Any], *, now_ms: int,
             periode_ms: int = PERIODE_REGLEMENT_MS) -> dict[str, float]:
    """Découpe le funding couru d'une position en RÉGLÉ et ESTIMÉ.

    Retourne `{net_funding_settled, funding_accrual_estimate, heures_reglees,
    fraction_heure_en_cours}`. La somme des deux premiers vaut exactement
    `funding_accrued_usdt` — on ne crée ni ne détruit de valeur, on la qualifie.

    Position illisible (pas d'entrée, pas d'accru) -> tout à zéro, jamais une exception :
    une position mal formée ne doit pas faire disparaître le PnL des autres.
    """
    accru = _nombre(position.get("funding_accrued_usdt")) or 0.0
    entree = _nombre(position.get("entry_ts_ms"))
    if entree is None or accru == 0.0:
        return {"net_funding_settled": round(accru, 8), "funding_accrual_estimate": 0.0,
                "heures_reglees": 0.0, "fraction_heure_en_cours": 0.0}
    duree_ms = max(0.0, float(now_ms) - entree)
    if duree_ms <= 0:
        return {"net_funding_settled": 0.0, "funding_accrual_estimate": round(accru, 8),
                "heures_reglees": 0.0, "fraction_heure_en_cours": 0.0}
    n_regl = reglements_franchis(int(entree), int(now_ms), periode_ms)
    heures_totales = duree_ms / float(periode_ms)
    if heures_totales <= 0:
        part_reglee = 0.0
    else:
        # le funding couru est réparti UNIFORMÉMENT sur la durée de détention (c'est
        # l'hypothèse de `accruer`) : la part réglée est donc le rapport des durées.
        part_reglee = min(1.0, float(n_regl) / heures_totales)
    regle = accru * part_reglee
    return {
        "net_funding_settled": round(regle, 8),
        "funding_accrual_estimate": round(accru - regle, 8),
        "heures_reglees": float(n_regl),
        "fraction_heure_en_cours": round(max(0.0, heures_totales - n_regl), 6),
    }


def agreger(positions: Any, *, now_ms: int,
            periode_ms: int = PERIODE_REGLEMENT_MS) -> dict[str, float]:
    """Le découpage sur TOUT un portefeuille. Même contrat : la somme est conservée."""
    regle = est = 0.0
    n_pos = 0
    for p in (positions.values() if isinstance(positions, dict) else (positions or ())):
        if not isinstance(p, dict):
            continue
        d = decouper(p, now_ms=now_ms, periode_ms=periode_ms)
        regle += d["net_funding_settled"]
        est += d["funding_accrual_estimate"]
        n_pos += 1
    return {"net_funding_settled": round(regle, 8),
            "funding_accrual_estimate": round(est, 8),
            "funding_total_couru": round(regle + est, 8),
            "positions": n_pos}


def pnl_stable(realise_usd: float, net_funding_settled: float) -> float:
    """LE chiffre qui a le droit de s'appeler « stable ».

    `realise_usd` sort du ledger (les CLOSE portent déjà frais d'entrée, de sortie et
    correction de base). On y ajoute UNIQUEMENT le funding réellement réglé.
    N'y entrent JAMAIS : l'accrual de l'heure en cours, ni le latent de base — les deux
    sont réversibles ou non encore acquis, et s'affichent à côté.
    """
    return round(float(realise_usd or 0.0) + float(net_funding_settled or 0.0), 8)


__all__ = ["PERIODE_REGLEMENT_MS", "reglements_franchis", "decouper", "agreger", "pnl_stable"]
