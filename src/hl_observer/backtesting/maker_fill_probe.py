"""MESURER le taux de remplissage MAKER, au lieu de le supposer.

POURQUOI CE MODULE EXISTE
-------------------------
Tout edge mesuré ici est mort dans les coûts : `fast_follow` REJETÉ à tous les horizons ≤ 300 s
**même à spread nul**, DeepLOB à **−4 242 bps net**, 67 % des fills de leaders passifs et valant
≈ 0 avant frais. Le seul levier qui n'a jamais été ouvert est l'entrée **MAKER** : payer le rebate
au lieu de traverser le spread.

Le moteur sait déjà en tenir compte — `robustness.maker_adjust_net` modélise proprement l'économie
d'un trade rempli ET la sélection adverse (`adverse=True` garde les PIRES trades : les gagnants
filent avant que l'ordre passif soit touché). Et `microstructure_extras.maker_queue_fill_prob`
donne une probabilité de file.

**Mais les deux PRENNENT `fill_rate` EN PARAMÈTRE.** Personne ne l'a jamais mesuré. C'est pour cela
que `native_cross_venue_replay` publie `maker_fill_proven: False` en dur et nomme ses clés
`..._unproven_fill` : le moteur refuse de conclure, et il a raison de refuser.

Ce module comble exactement ce trou : il regarde, dans les **vrais carnets** et les **vrais
trades**, si un ordre passif posé au touch aurait été consommé.

LES TROIS CHOIX QUI RENDENT LA MESURE HONNÊTE
---------------------------------------------
1. **On se met DERNIER dans la file.** La taille affichée à notre prix au moment du signal est
   considérée comme intégralement devant nous. C'est pessimiste et c'est voulu : surestimer sa
   place dans la file est la façon classique de fabriquer un faux edge maker.
2. **Seul le volume au PRIX OU MIEUX compte.** Un trade à un prix qui ne touche pas notre niveau
   ne consomme pas notre file. Pour un achat passif à `B`, seuls les trades à `prix <= B`.
3. **« Je ne sais pas » n'est jamais « rempli ».** Carnet absent, niveau absent, aucun trade
   observé sur la fenêtre : le cas sort en `NON_MESURABLE` et n'entre dans AUCUN numérateur.
   Le taux renvoyé porte donc toujours son dénominateur réel et son compte d'écartés.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne dit pas qu'une stratégie maker est rentable. Il fournit **un chiffre mesuré** là où il y
avait une hypothèse, pour que `maker_adjust_net` cesse d'être alimenté au doigt mouillé. La
rentabilité reste soumise au moteur et à ses portes.

PAPER / lecture seule : aucun ordre, aucune signature, aucune écriture.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

#: Verdicts d'un cas. `NON_MESURABLE` n'est JAMAIS compté comme un remplissage.
REMPLI = "REMPLI"
NON_REMPLI = "NON_REMPLI"
NON_MESURABLE = "NON_MESURABLE"

#: Motifs d'impossibilité — on dit toujours POURQUOI on ne sait pas.
SANS_CARNET = "SANS_CARNET"
SANS_NIVEAU = "NIVEAU_ABSENT_DU_CARNET"
SANS_TRADES = "AUCUN_TRADE_OBSERVE_SUR_LA_FENETRE"
COTE_INCONNU = "COTE_INCONNU"

ACHAT, VENTE = 1, -1


def _nombre(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def file_devant(carnet: Mapping[str, Any], prix: float, cote: int) -> float | None:
    """Taille affichée A NOTRE PRIX au moment du signal — elle est TOUTE devant nous.

    On ne cherche pas à estimer une position de file plus favorable : se croire devant est la
    façon la plus simple de fabriquer un faux edge maker. Renvoie None si le niveau est absent,
    ce qui rendra le cas NON_MESURABLE plutôt que gratuitement optimiste.
    """
    niveaux = carnet.get("bids5" if cote == ACHAT else "asks5")
    if not isinstance(niveaux, Sequence):
        return None
    for niveau in niveaux:
        if not isinstance(niveau, Sequence) or len(niveau) < 2:
            continue
        prix_niveau, taille = _nombre(niveau[0]), _nombre(niveau[1])
        if prix_niveau is None or taille is None:
            continue
        if math.isclose(prix_niveau, prix, rel_tol=0.0, abs_tol=1e-12):
            return max(0.0, taille)
    return None


def volume_consommateur(trades: Iterable[Mapping[str, Any]], *, prix: float, cote: int,
                        debut_ms: int, fin_ms: int) -> tuple[float, int]:
    """Volume qui a REELLEMENT traversé notre niveau sur la fenêtre, et le nombre de trades vus.

    Pour un achat passif à `B`, seuls les trades à `prix <= B` consomment la file : un trade plus
    haut n'y touche pas. Le compte de trades est renvoyé pour distinguer « fenêtre vide »
    (non mesurable) de « fenêtre pleine mais niveau jamais atteint » (non rempli, information
    réelle).
    """
    volume = 0.0
    vus = 0
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        # RECEPTION d'abord : c'est l'instant ou nous AURIONS PU agir, choix canonique du
        # projet (cf. `copy_vault_book_loader`, ts_ms = received). Les rubans de trades
        # portent `received_at_ms` / `exchange_ts_ms` et PAS `ts_ms` : ne chercher que
        # `ts_ms` revenait a ignorer SILENCIEUSEMENT 100 % des trades, donc a declarer
        # « aucun trade observe » sur un ruban de 3,7 Go. Bug mesure le 14/11.
        ts = _nombre(
            trade.get("received_at_ms")
            if trade.get("received_at_ms") is not None
            else trade.get("ts_ms")
            if trade.get("ts_ms") is not None
            else trade.get("exchange_ts_ms")
            if trade.get("exchange_ts_ms") is not None
            else trade.get("time") if trade.get("time") is not None else trade.get("ts_ex")
        )
        if ts is None or not (debut_ms <= ts <= fin_ms):
            continue
        vus += 1
        prix_trade = _nombre(trade.get("px") or trade.get("price"))
        taille = _nombre(
            trade.get("sz") if trade.get("sz") is not None else trade.get("size")
        )
        if prix_trade is None or taille is None or taille <= 0:
            continue
        touche = prix_trade <= prix if cote == ACHAT else prix_trade >= prix
        if touche:
            volume += taille
    return volume, vus


def instant_de_remplissage(trades: Iterable[Mapping[str, Any]], *, prix: float, cote: int,
                           debut_ms: int, fin_ms: int, besoin: float) -> int | None:
    """Instant ou le volume cumule franchit `besoin` — l'instant du FILL, pas celui de l'ordre.

    Le markout se mesure A PARTIR DU FILL. Le mesurer depuis le depot de l'ordre melangerait
    l'attente (pendant laquelle on ne porte aucun risque) avec la derive post-remplissage, et
    ferait paraitre toxique un ordre simplement reste longtemps dans le carnet.
    """
    cumul = 0.0
    horodates: list[tuple[int, float]] = []
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        ts = _nombre(
            trade.get("received_at_ms")
            if trade.get("received_at_ms") is not None
            else trade.get("ts_ms")
            if trade.get("ts_ms") is not None
            else trade.get("exchange_ts_ms")
        )
        if ts is None or not (debut_ms <= ts <= fin_ms):
            continue
        prix_trade = _nombre(trade.get("px") if trade.get("px") is not None else trade.get("price"))
        taille = _nombre(trade.get("sz") if trade.get("sz") is not None else trade.get("size"))
        if prix_trade is None or taille is None or taille <= 0:
            continue
        touche = prix_trade <= prix if cote == ACHAT else prix_trade >= prix
        if touche:
            horodates.append((int(ts), taille))
    horodates.sort()
    for ts, taille in horodates:
        cumul += taille
        if cumul >= besoin:
            return ts
    return None


#: Places simulees dans la file. DERNIER = pire cas (toute la taille affichee devant nous).
#: PREMIER = meilleur cas (on est en tete, seule notre taille doit etre consommee).
DERNIER, PREMIER = "DERNIER", "PREMIER"


def sonder_un_cas(*, carnet: Mapping[str, Any] | None, trades: Iterable[Mapping[str, Any]],
                  prix_passif: float | None, cote: int, debut_ms: int, horizon_ms: int,
                  taille_voulue: float, place: str = DERNIER) -> dict[str, Any]:
    """Un ordre passif posé à `prix_passif` aurait-il été rempli dans l'horizon ?

    Règle : rempli SI le volume ayant traversé notre niveau dépasse la file devant nous PLUS notre
    propre taille. Exiger de couvrir aussi notre taille évite de compter « rempli » un ordre qui
    n'aurait été servi qu'en partie.
    """
    if carnet is None:
        return {"verdict": NON_MESURABLE, "motif": SANS_CARNET}
    if cote not in (ACHAT, VENTE):
        return {"verdict": NON_MESURABLE, "motif": COTE_INCONNU}
    prix = _nombre(prix_passif)
    if prix is None:
        return {"verdict": NON_MESURABLE, "motif": SANS_NIVEAU}
    devant = file_devant(carnet, prix, cote)
    if devant is None:
        return {"verdict": NON_MESURABLE, "motif": SANS_NIVEAU}

    fin_ms = int(debut_ms) + int(horizon_ms)
    volume, trades_vus = volume_consommateur(trades, prix=prix, cote=cote,
                                             debut_ms=int(debut_ms), fin_ms=fin_ms)
    if trades_vus == 0:
        # Fenêtre sans aucun trade observé : on n'a pas regardé le marché, on ne peut pas
        # conclure « non rempli ». C'est un trou de données, pas une information.
        return {"verdict": NON_MESURABLE, "motif": SANS_TRADES, "file_devant": devant}

    # LA PLACE DANS LA FILE EST LE LEVIER QUI RETOURNE LE SIGNE. Mesure publiee sur le perp BTC
    # d'Hyperliquid a 5 s : remplissage maker moyen -0,48 bp, mais PREMIERE PLACE +0,32 bp, soit
    # un ecart de ~0,8 bp. Supposer la derniere place donne donc le PIRE cas, et comparer les deux
    # bras est l'experience qui dit si le signe negatif appartient au fait de coter au touch ou
    # seulement au fait d'y coter EN DERNIER.
    devant_effectif = 0.0 if place == PREMIER else devant
    besoin = devant_effectif + max(0.0, float(taille_voulue))
    rempli = volume >= besoin
    instant = (instant_de_remplissage(trades, prix=prix, cote=cote, debut_ms=int(debut_ms),
                                      fin_ms=fin_ms, besoin=besoin) if rempli else None)
    return {
        "verdict": REMPLI if rempli else NON_REMPLI,
        "place": place,
        "instant_remplissage_ms": instant,
        "prix_passif": prix,
        "cote": cote,
        "file_devant": devant,
        "volume_traverse": volume,
        "volume_necessaire": besoin,
        "trades_observes": trades_vus,
        "marge": volume - besoin,
    }


def economie_de_spread(carnet: Mapping[str, Any], *, notionnel: float) -> float | None:
    """Ce qu'une entree MAKER economise REELLEMENT sur ce carnet, en dollars.

    Entrer en passif au touch au lieu de traverser, c'est economiser le DEMI-SPREAD par rapport au
    mid. On le mesure sur le carnet observe au lieu de le supposer : l'appel historique de
    `maker_adjust_net` utilisait `spread_saving_usd=0.20` en dur, une constante qui ne correspond
    a aucun marche en particulier — et qui, sur un coin a spread serre, SURESTIME massivement le
    gain. Renvoie None si le carnet ne permet pas de conclure, jamais une valeur par defaut.
    """
    bids = carnet.get("bids5")
    asks = carnet.get("asks5")
    if not isinstance(bids, Sequence) or not isinstance(asks, Sequence) or not bids or not asks:
        return None
    try:
        meilleur_bid = _nombre(bids[0][0])
        meilleur_ask = _nombre(asks[0][0])
    except (IndexError, TypeError):
        return None
    if meilleur_bid is None or meilleur_ask is None or meilleur_ask <= meilleur_bid:
        return None
    mid = (meilleur_bid + meilleur_ask) / 2.0
    if mid <= 0:
        return None
    demi_spread_relatif = (meilleur_ask - meilleur_bid) / 2.0 / mid
    montant = _nombre(notionnel)
    if montant is None or montant <= 0:
        return None
    return demi_spread_relatif * montant


def encadrement_maker(net_trades: Sequence[float], *, taux: float | None,
                      economie_usd: float | None) -> dict[str, Any]:
    """Encadre l'effet MAKER entre sa borne BASSE et sa borne HAUTE — jamais un point seul.

    `robustness.maker_adjust_net` sait faire les deux : `adverse=True` garde en priorite les PIRES
    trades (les gagnants filent avant que l'ordre passif soit touche) = borne BASSE honnete ;
    `adverse=False` jette au hasard = borne HAUTE. L'appel historique n'utilisait QUE `adverse=False`,
    c'est-a-dire la version flatteuse. Publier un encadrement interdit de ne retenir que la bonne.

    Refuse de calculer si le taux ou l'economie n'ont pas ete MESURES : c'est tout l'objet de ce
    module de supprimer ces deux hypotheses.
    """
    if taux is None or economie_usd is None:
        return {"mesurable": False,
                "raison": "TAUX_OU_ECONOMIE_NON_MESURES",
                "basse": None, "haute": None}
    from hl_observer.backtesting.robustness import maker_adjust_net

    trades = [float(x) for x in net_trades]
    basse = maker_adjust_net(trades, spread_saving_usd=economie_usd, fill_rate=taux,
                             seed=7, adverse=True)
    haute = maker_adjust_net(trades, spread_saving_usd=economie_usd, fill_rate=taux,
                             seed=7, adverse=False)
    return {
        "mesurable": True,
        "taux_utilise": float(taux),
        "economie_usd_utilisee": float(economie_usd),
        "basse": {"somme": sum(basse), "trades": len(basse)},
        "haute": {"somme": sum(haute), "trades": len(haute)},
        "verdict": ("POSITIF_MEME_AU_PIRE" if sum(basse) > 0
                    else "POSITIF_SEULEMENT_AU_MIEUX" if sum(haute) > 0
                    else "NEGATIF_DANS_LES_DEUX_CAS"),
    }


def taux_de_remplissage(cas: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Agrège des cas en un taux MESURE, avec son dénominateur et ses écartés.

    Un taux sans son dénominateur ne veut rien dire : 100 % sur 2 cas n'est pas 100 % sur 2 000.
    Les NON_MESURABLE sont comptés à part et n'entrent dans aucun numérateur — ils ne doivent ni
    gonfler ni déprimer le taux.
    """
    remplis = non_remplis = 0
    ecartes: dict[str, int] = {}
    for item in cas:
        if not isinstance(item, Mapping):
            continue
        verdict = item.get("verdict")
        if verdict == REMPLI:
            remplis += 1
        elif verdict == NON_REMPLI:
            non_remplis += 1
        else:
            motif = str(item.get("motif") or NON_MESURABLE)
            ecartes[motif] = ecartes.get(motif, 0) + 1
    jugeables = remplis + non_remplis
    return {
        "remplis": remplis,
        "non_remplis": non_remplis,
        "jugeables": jugeables,
        "non_mesurables": sum(ecartes.values()),
        "par_motif": dict(sorted(ecartes.items())),
        "taux": (remplis / jugeables) if jugeables else None,
        "mesurable": jugeables > 0,
    }


def lecture(resume: Mapping[str, Any], *, minimum_jugeables: int = 30) -> str:
    """Phrase honnête — et qui refuse de conclure sur trop peu de cas."""
    jugeables = int(resume.get("jugeables") or 0)
    ecartes = int(resume.get("non_mesurables") or 0)
    if not jugeables:
        return (f"taux de remplissage maker NON MESURABLE : aucun cas jugeable "
                f"({ecartes} ecarte(s)). Ne pas alimenter maker_adjust_net avec une hypothese.")
    taux = float(resume.get("taux") or 0.0)
    phrase = (f"taux de remplissage maker MESURE : {taux * 100:.1f} % "
              f"sur {jugeables} cas jugeables ({ecartes} non mesurables)")
    if jugeables < minimum_jugeables:
        phrase += (f" — ATTENTION : moins de {minimum_jugeables} cas, chiffre indicatif, "
                   "insuffisant pour prouver un remplissage")
    return phrase


__all__ = [
    "ACHAT", "VENTE", "DERNIER", "PREMIER", "REMPLI", "NON_REMPLI", "NON_MESURABLE",
    "SANS_CARNET", "SANS_NIVEAU", "SANS_TRADES", "COTE_INCONNU",
    "file_devant", "volume_consommateur", "instant_de_remplissage", "sonder_un_cas", "taux_de_remplissage", "lecture",
    "economie_de_spread", "encadrement_maker",
]
