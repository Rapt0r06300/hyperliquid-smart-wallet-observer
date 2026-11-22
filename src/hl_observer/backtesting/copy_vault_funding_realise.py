"""Le funding REELLEMENT paye par un episode, lu dans le coffre au lieu d'etre declare inconnu.

DEFAUT QUE CE MODULE REPARE (mesure du 19/11/2026). Le moteur gele refuse tout candidat dont le
funding n'est pas prouve : `FUNDING_PNL_UNMEASURABLE`. Son unique statut acceptant est
`MEASURED_ZERO_NO_SETTLEMENT_CROSSED` -- « aucun reglement traverse ». Or Hyperliquid regle le
funding toutes les heures et les horizons explores vont jusqu'a une heure : presque tout episode
en traverse un. Resultat : la porte refusait **100 % des 11 391 essais**, et aucun candidat, meme
reellement profitable, ne pouvait la franchir.

Le statut `MEASURED` existe pourtant, et `_reference_objective_status` l'accepte -- mais AUCUNE
ligne du depot ne le produisait : `grep "funding_history\\|funding_rate"` sur
`src/hl_observer/backtesting/` ne rendait rien. La grandeur n'etait pas « non mesurable » : elle
n'etait pas mesuree. Et la donnee etait la, dans le coffre : famille `funding_history`, 80 shards,
54 journees, 20 390 reglements horaires sur 263 coins pour la seule fenetre TRAIN.

CE QUE CE MODULE NE FAIT PAS. Il ne desserre aucune porte. Un funding qu'on ne sait pas lire reste
`UNMEASURABLE` avec sa raison -- jamais un zero favorable, qui ferait passer un candidat pour
rentable alors qu'on ignore ce qu'il paie.

PROVENANCE, DITE ET NON SUPPOSEE. Les taux viennent de `REST_FUNDING_HISTORY`, un rattrapage par
interrogation : ils portent `causal_forward_eligible: False`. C'est acceptable ICI, et seulement
ici, parce qu'un taux ne sert jamais a DECIDER -- il chiffre apres coup ce qu'un episode deja
decide a paye. C'est la meme frontiere que pour les carnets : la decision n'utilise que le passe,
seule l'execution lui est posterieure. Chaque recu le dit (`provenance`), pour qu'on ne puisse pas
confondre un cout reconstitue avec une observation directe.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from hl_observer.funding.funding_times import next_funding_time_ms

#: La famille du coffre qui porte les taux de funding regles.
FAMILLE_FUNDING = "funding_history"

#: L'intervalle de reglement d'Hyperliquid. Le coffre le porte ligne par ligne (`interval`), et on
#: REFUSE toute ligne qui annonce autre chose plutot que de supposer : un intervalle different
#: changerait le nombre de reglements traverses, donc le cout.
INTERVALLE_ATTENDU = "1h"

#: Ce que vaut la provenance des taux, dit une fois pour toutes.
PROVENANCE_RECONSTITUEE = "REST_FUNDING_HISTORY_RECONSTITUEE"


def taux_du_coffre(
    racine: str | Path,
    *,
    coins: Sequence[str] | None,
    debut_ms: int,
    fin_ms: int,
) -> tuple[dict[str, list[tuple[int, Decimal]]], dict[str, Any]]:
    """Les reglements de funding du coffre, par coin, tries par instant.

    Rend aussi un audit : sans le couple « lu / garde », un dictionnaire vide ne se distingue pas
    d'une lecture qui n'a rien trouve a lire.
    """
    import json

    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return {}, {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(tous, dict):
        tous = list(tous.values())
    choix = coffre_tranches.selectionner(
        tous, famille=FAMILLE_FUNDING,
        coins=list(coins) if coins else None,
        debut_ms=int(debut_ms), fin_ms=int(fin_ms))
    shards = choix.get("shards") or choix.get("retenus") or []
    if not shards:
        return {}, {"status": "AUCUN_SHARD_DE_FUNDING", "shards": 0}

    par_coin: dict[str, list[tuple[int, Decimal]]] = {}
    lus = gardes = intervalle_inattendu = taux_illisible = 0
    for ligne in coffre_tranches.flux(
        racine, shards, famille=FAMILLE_FUNDING,
        coins=list(coins) if coins else None,
        debut_ms=int(debut_ms), fin_ms=int(fin_ms), verifier_sha=False,
    ):
        lus += 1
        coin = str(ligne.get("coin") or ligne.get("symbole") or "")
        if not coin:
            continue
        if str(ligne.get("interval") or "").strip().lower() != INTERVALLE_ATTENDU:
            # On ne devine pas un intervalle : un reglement toutes les huit heures au lieu d'une
            # heure diviserait le cout par huit, silencieusement.
            intervalle_inattendu += 1
            continue
        valeur = ligne.get("funding")
        try:
            if isinstance(valeur, bool) or valeur is None:
                raise TypeError(valeur)
            taux = Decimal(str(valeur))
        except (TypeError, ValueError, ArithmeticError):
            taux_illisible += 1
            continue
        instant = ligne.get("ts_ms")
        if isinstance(instant, bool) or not isinstance(instant, (int, float)):
            taux_illisible += 1
            continue
        par_coin.setdefault(coin, []).append((int(instant), taux))
        gardes += 1
    for serie in par_coin.values():
        serie.sort(key=lambda couple: couple[0])
    audit = {
        "status": "LU_DEPUIS_LE_COFFRE",
        "shards": len(shards),
        "lignes_lues": lus,
        "reglements_gardes": gardes,
        "coins": len(par_coin),
        "ecartes_intervalle_inattendu": intervalle_inattendu,
        "ecartes_taux_illisible": taux_illisible,
        "provenance": PROVENANCE_RECONSTITUEE,
    }
    return par_coin, audit


def _reglements_traverses(
    serie: Sequence[tuple[int, Decimal]], debut_ms: int, fin_ms: int
) -> list[tuple[int, Decimal]]:
    """Les reglements strictement APRES l'entree et au plus tard a la sortie.

    Un reglement a l'instant exact de l'entree n'est pas paye par une position ouverte juste
    apres ; un reglement a l'instant de la sortie l'est, puisqu'on detient encore. La borne
    choisie est donc `(debut, fin]`, et elle est verrouillee par un test -- une borne qui glisse
    d'un reglement, c'est un cout qui change sans que rien ne le dise.
    """
    instants = [instant for instant, _ in serie]
    premier = bisect.bisect_right(instants, int(debut_ms))
    dernier = bisect.bisect_right(instants, int(fin_ms))
    return list(serie[premier:dernier])


def funding_du_trade(
    trade: Mapping[str, Any],
    taux_par_coin: Mapping[str, Sequence[tuple[int, Decimal]]],
    *,
    couverture_ms: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Le cout de portage d'UN episode, ou la raison pour laquelle il reste inconnu.

    Convention Hyperliquid, et elle compte : a taux positif, les positions LONGUES paient les
    courtes. Un long voit donc son resultat diminue, un short augmente. Se tromper de signe
    transformerait un cout en revenu -- exactement le genre de faux PnL que le contrat interdit.
    """
    coin = str(trade.get("coin") or "")
    entree = trade.get("entry_ts_ms")
    sortie = trade.get("exit_ts_ms")
    notionnel = trade.get("notional_usd", trade.get("entry_notional_usd"))
    direction = trade.get("direction")
    manque = (
        isinstance(entree, bool) or not isinstance(entree, int) or entree <= 0
        or isinstance(sortie, bool) or not isinstance(sortie, int) or sortie <= entree
    )
    if manque:
        return _inconnu("FUNDING_TRADE_TIMESTAMPS_UNMEASURABLE", coin)
    if isinstance(notionnel, bool) or not isinstance(notionnel, (int, float)):
        return _inconnu("FUNDING_NOTIONAL_UNMEASURABLE", coin)
    if direction not in (1, -1):
        return _inconnu("FUNDING_DIRECTION_UNMEASURABLE", coin)
    serie = taux_par_coin.get(coin)
    if not serie:
        return _inconnu("FUNDING_RATES_MISSING_FOR_COIN", coin)
    # LA COUVERTURE SE JUGE SUR LA FENETRE LUE, PAS SUR LA POSITION DES REGLEMENTS.
    #
    # Premiere version de cette garde : « refuser si l'entree precede le premier reglement connu ».
    # Elle melangeait deux choses -- ne pas savoir, et n'avoir rien a payer. Un episode qui tient
    # ENTRE deux reglements n'en traverse aucun : son funding vaut zero, et c'est une mesure, pas
    # une ignorance. Quatre tests l'ont dit avant que la mesure ne serve.
    #
    # Ce qu'il faut verifier, c'est qu'on a LU tous les reglements de l'intervalle de l'episode.
    # Sans `couverture_ms`, on retombe sur les bornes des reglements connus, qui ne prouvent qu'un
    # minimum -- donc on reste prudent et on refuse les episodes qui en sortent.
    debut_couvert, fin_couverte = couverture_ms or (serie[0][0], serie[-1][0])
    if entree < int(debut_couvert) or sortie > int(fin_couverte):
        return _inconnu("FUNDING_RATES_DO_NOT_COVER_EPISODE", coin)
    traverses = _reglements_traverses(serie, entree, sortie)
    porte = Decimal(str(float(notionnel))) * Decimal(int(direction))
    cout = sum((taux * porte for _, taux in traverses), Decimal(0))
    return {
        "status": "MEASURED",
        "coin": coin,
        "carry_pnl_usd": float(-cout),
        "carry_pnl_usd_exact_decimal": format(-cout, "f"),
        "settlement_crossing_count": len(traverses),
        "settlement_interval_hours": 1,
        "provenance": PROVENANCE_RECONSTITUEE,
        "reason": None,
    }


def _inconnu(raison: str, coin: str) -> dict[str, Any]:
    return {
        "status": "UNMEASURABLE",
        "coin": coin,
        "carry_pnl_usd": None,
        "carry_pnl_usd_exact_decimal": None,
        "settlement_crossing_count": None,
        "settlement_interval_hours": 1,
        "provenance": PROVENANCE_RECONSTITUEE,
        "reason": raison,
    }


def funding_des_trades(
    trades: Iterable[Mapping[str, Any]],
    taux_par_coin: Mapping[str, Sequence[tuple[int, Decimal]]],
    *,
    couverture_ms: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Le funding de TOUS les episodes, et un seul verdict : une inconnue suffit a l'emporter.

    Un total calcule sur les seuls episodes lisibles flatterait le resultat d'autant qu'il en
    manque. Si un seul reste inconnu, le total l'est aussi -- on dit combien, et pourquoi.
    """
    recus = [funding_du_trade(trade, taux_par_coin, couverture_ms=couverture_ms)
             for trade in trades]
    inconnus = [r for r in recus if r["status"] != "MEASURED"]
    raisons: dict[str, int] = {}
    for recu in inconnus:
        raison = str(recu.get("reason") or "UNKNOWN")
        raisons[raison] = raisons.get(raison, 0) + 1
    if inconnus:
        return {
            "status": "UNMEASURABLE",
            "trade_count": len(recus),
            "measured_count": len(recus) - len(inconnus),
            "carry_pnl_usd": None,
            "reasons": raisons,
            "provenance": PROVENANCE_RECONSTITUEE,
        }
    total = sum((Decimal(r["carry_pnl_usd_exact_decimal"]) for r in recus), Decimal(0))
    return {
        "status": "MEASURED",
        "trade_count": len(recus),
        "measured_count": len(recus),
        "carry_pnl_usd": float(total),
        "carry_pnl_usd_exact_decimal": format(total, "f"),
        "settlement_crossing_count": sum(r["settlement_crossing_count"] for r in recus),
        "reasons": {},
        "provenance": PROVENANCE_RECONSTITUEE,
    }


def porte_de_funding(
    *, coin: str, entree_ms: int, sortie_ms: int, notionnel_usd: float, direction: int,
    taux_funding: Mapping[str, Sequence[tuple[int, Decimal]]] | None,
    couverture_ms: tuple[int, int] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """(portage, refus) pour UN episode : la porte d'executabilite du moteur.

    POURQUOI CETTE PORTE A CHANGE (22/11/2026, feu vert operateur). Elle refusait TOUT episode
    franchissant une frontiere de funding : 231 candidats TRAIN sur 1 613 mouraient la. Ce refus
    etait JUSTE tant que le moteur ne deduisait le funding nulle part -- desserrer une porte
    derriere laquelle aucun cout n'est retire, c'est sous-estimer les frais, donc fabriquer du
    profit. On a donc d'abord cable le cout, ensuite seulement ouvert la porte.

    Trois cas, la ou le code en confondait deux :

    * frontiere EXACTEMENT a l'entree ou a la sortie -> avec des horodatages seuls, l'ordre
      fill/funding est inconnu, et AUCUN taux ne leve cette ambiguite : refus
      `FUNDING_BOUNDARY_UNPRICED`. C'est le cas que decrivait le commentaire d'origine.
    * frontiere STRICTEMENT INTERIEURE -> la position etait indiscutablement ouverte au
      reglement : son cout est chiffre, a condition d'avoir le taux OBSERVE. Sinon refus
      `FUNDING_BOUNDARY_RATE_UNOBSERVED` -- ne pas savoir n'autorise pas a supposer zero.
    * `taux_funding is None` -> refus identique a l'ancien comportement, bit pour bit.

    Rend `(None, None)` quand aucune frontiere n'est traversee : zero MESURE, pas une ignorance.
    """
    premiere = next_funding_time_ms(entree_ms - 1, interval_hours=1)
    if premiere > sortie_ms:
        return None, None
    ambigue = (premiere == entree_ms
               or next_funding_time_ms(sortie_ms - 1, interval_hours=1) == sortie_ms)
    if ambigue or taux_funding is None:
        return None, "FUNDING_BOUNDARY_UNPRICED"
    portage = funding_du_trade(
        {"coin": coin, "entry_ts_ms": entree_ms, "exit_ts_ms": sortie_ms,
         "notional_usd": notionnel_usd, "direction": direction},
        taux_funding, couverture_ms=couverture_ms,
    )
    if str(portage.get("status")) != "MEASURED":
        return None, "FUNDING_BOUNDARY_RATE_UNOBSERVED"
    return portage, None


def champs_de_portage(net: float, portage: Mapping[str, Any] | None) -> dict[str, Any]:
    """Les champs de portage d'un trade, A COTE de `net_pnl_usd` et jamais dedans.

    `net_pnl_usd` est reconcilie contre `executable_before_fees - fees` et sa provenance est
    causale ; les taux viennent d'un rattrapage REST (`causal_forward_eligible: False`). Les
    melanger casserait l'equation de conservation ET brouillerait la provenance. On publie donc
    la somme EXPLICITE `net_after_carry_usd`, et le lecteur voit les deux termes.
    """
    if portage is None:
        return {
            "carry_pnl_usd": 0.0,
            "carry_status": "MEASURED_ZERO_NO_SETTLEMENT_CROSSED",
            "carry_provenance": None,
            "settlement_crossing_count": 0,
            "net_after_carry_usd": net,
        }
    cout = float(portage["carry_pnl_usd"])
    return {
        "carry_pnl_usd": cout,
        "carry_status": str(portage["status"]),
        "carry_provenance": portage.get("provenance"),
        "settlement_crossing_count": int(portage["settlement_crossing_count"]),
        "net_after_carry_usd": net + cout,
    }
