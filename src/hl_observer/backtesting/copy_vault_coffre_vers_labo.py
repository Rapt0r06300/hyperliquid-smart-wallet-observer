"""Lire le COFFRE CERTIFIE pour le labo : fills du leader et carnets, en flux.

Separe de `copy_vault_labo_deux_phases` parce que c'est une responsabilite distincte -- la lecture
d'une source -- et parce que le test d'architecture refuse un fichier de plus de 800 lignes, a
juste titre : un module qui melange la lecture d'une source et l'orchestration d'un pipeline se
relit mal et se corrige mal.

POURQUOI LE COFFRE ET PAS LES RUBANS LOCAUX. Mesure du 18-19/11/2026 :
`runtime/data/vault_fills_live.jsonl` couvre 17/11 19:10 -> 18/11 22:06, parce qu'il ne retient
que la source `LIVE_WS`. Le coffre porte `fills_forward` (21,6 M lignes sur 23 journees) avec en
plus `LIVE_POLL`, une collecte par interrogation active depuis le 13/11 et tout aussi causale.
Branche sur les rubans locaux, le labo voyait 8 176 signaux ; branche sur le coffre, 4 618 095.
Il ne manquait pas de donnees, mais un chemin vers elles.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_signal_alignment import MAX_BOOK_AGE_MS


def _fenetre_apres_signal() -> int:
    """Combien de temps APRES un signal un carnet peut encore servir.

    DEFAUT QUE CECI CORRIGE (18/11/2026). Le replay cherche TROIS carnets par signal :

      * `reference` : le dernier carnet au plus tard AU signal ;
      * `entry`     : le premier carnet a partir de `signal + COPY_DELAY_MS` ;
      * `exit_book` : le premier carnet a partir de `entree + horizon_ms`.

    Ne garder que les carnets des `MAX_BOOK_AGE_MS` PRECEDANT le signal -- ce que faisait la
    premiere version de ce filtre -- jette donc les carnets d'entree et de sortie. Resultat mesure
    sur 4 000 signaux : **zero trade**, avec 3 188 `STALE_OR_MISSING_ENTRY_BOOK` et 724
    `STALE_OR_MISSING_REFERENCE_BOOK`. Les carnets etaient la (703 664 sur 200 coins) ; c'est la
    fenetre qui etait du mauvais cote.

    J'avais ecrit moi-meme, dans le commentaire de `carnets_utiles`, qu'une fenetre trop ETROITE
    ferait disparaitre des signaux sans que personne le voie. Je l'avais calibree sur l'alignement,
    qui ne regarde que le passe, et pas sur le replay, qui regarde aussi l'avenir.
    """
    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS

    horizon = max(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    return int(cv.COPY_DELAY_MS) + int(horizon) + int(cv.MAX_TARGET_LAG_MS)

#: Les familles du coffre qui portent des carnets, de la plus riche a la plus pauvre.
#: `bbo` et `book_l2` couvrent depuis le 26/10 ; les rubans locaux `runtime/data/*.jsonl` ne
#: commencent qu'au 17/11 18:35 -- mesure du 18/11/2026. Lire le coffre, c'est la difference entre
#: une journee de carnets et trois semaines.
FAMILLES_DE_CARNETS = ("book_l2", "micro_l2", "venue_book", "bbo", "micro_bbo")
#: Lignes sondees avant d abandonner une famille qui ne peut rien produire.
#:
#: MESURE DU 20/11/2026, sur le coffre reel : `book_l2` rend 100 % de carnets exploitables,
#: les QUATRE autres 0 % -- `capacity_usd` est absent de 6 000 lignes sur 6 000 pour `bbo`,
#: `micro_bbo` et `micro_l2`, et `venue_book` n a meme pas `bid`/`ask`. Le labo lisait donc
#: 195,6 millions de lignes par tranche (bbo 130,8 M + micro_bbo 62,2 M + ...) pour un
#: resultat strictement nul. On ne RETIRE pas ces familles -- leur schema peut gagner le
#: champ un jour -- on les SONDE et on les abandonne quand elles ne peuvent rien donner.
SONDAGE_FAMILLE = 200

#: LES SEULES ACTIONS QUE LA POLITIQUE GELEE SAIT COPIER.
#:
#: `copy_vault_v21_frozen._segment_candidates` ecarte tout metaordre dont la premiere action n'est
#: pas `ADD` (compteur `NON_ADD_REJECTED`) : elle ne copie donc que les RENFORCEMENTS de position
#: d'un leader, jamais ses ouvertures ni ses sorties. Mesure du 19/11/2026 sur une tranche de
#: quatre heures : 386 328 fills, dont **180 666 OPEN, 204 630 CLOSE et 1 032 ADD** -- soit 0,3 %
#: de copiable. Preparer les 99,7 % restants coute des carnets pour rien et noie les signaux
#: utiles : un corpus filtre au notionnel du leader rendait 765 signaux, dont 765 refuses pour
#: cette seule raison, donc zero candidat.
#:
#: Cette constante DUPLIQUE une regle du moteur gele, qu'on ne reecrit pas. Ce qui empeche la
#: copie de deriver, c'est `test_le_filtre_d_action_suit_la_politique_gelee` : il fait juger un
#: OPEN, un CLOSE et un ADD par le moteur lui-meme et verifie que seul l'ADD survit. Si la
#: politique change, ce test rougit -- il ne faut pas que le filtre, lui, reste muet.
ACTIONS_COPIEES_PAR_LA_POLITIQUE = ("ADD",)


def premiere_action(metaordre: Mapping[str, Any]) -> str:
    """L'action du PREMIER fill du metaordre, comme le moteur gele la lit.

    Le groupement rassemble plusieurs fills ; c'est le premier qui decide si l'episode est une
    ouverture ou un renforcement, parce que c'est lui qui declenche la copie.
    """
    membres = list(metaordre.get("member_events") or ())
    if membres and isinstance(membres[0], Mapping):
        return str(membres[0].get("action") or "").strip().upper()
    return str(metaordre.get("action") or "").strip().upper()


def copiable_par_la_politique(metaordre: Mapping[str, Any]) -> bool:
    """Vrai si la politique gelee tentera quelque chose avec ce metaordre."""
    return premiere_action(metaordre) in ACTIONS_COPIEES_PAR_LA_POLITIQUE


def ancres_utiles(
    instants: Sequence[int], *, delai_ms: int, horizons_ms: Sequence[int], pas_ms: int
) -> list[int]:
    """Les instants OU un carnet sert vraiment au replay, pour une suite de signaux d'un coin.

    DEFAUT QUE CECI CORRIGE (19/11/2026). La version precedente gardait « les premiers carnets de
    chaque fenetre », avec un plafond de 240 par signal, en expliquant qu'ils etaient « les plus
    proches des instants cibles ». C'etait faux : les premiers d'une fenetre sont les plus proches
    de son DEBUT, donc du carnet de reference -- et le carnet de SORTIE, a une heure de la, etait
    systematiquement jete. Mesure sur la tranche t001 : SOL, TIA, XMR, ZEC et XRP portaient
    exactement 240 carnets couvrant 40,9 minutes d'une fenetre de 240, sur une connexion unique et
    sans la moindre coupure reelle. Le plafond, pose pour la memoire, detruisait la mesure.

    Le replay cherche trois instants par signal : `t` (reference), `t + delai` (entree) et
    `t + delai + horizon` (sortie) -- pour CHACUN des horizons que le labo explore, puisqu'il les
    cherche. On garde donc des carnets autour de ces instants-la, et de nulle part ailleurs.

    `pas_ms` quantifie les ancres : deux instants separes de moins d'un pas n'ont pas besoin de
    deux carnets, puisque le meme carnet repond pour les deux. C'est ce qui empeche le budget de
    croitre avec le nombre de signaux voisins.
    """
    exactes: set[int] = set()
    crans: set[int] = set()
    pas = max(1, int(pas_ms))
    for brut in instants:
        t = int(brut)
        # LA REFERENCE ET L'ENTREE NE SE QUANTIFIENT PAS.
        #
        # Premiere version : tout etait arrondi au cran inferieur. L'ancre de reference tombait
        # donc jusqu'a un pas AVANT le signal, et le carnet garde de son cote passe pouvait se
        # trouver a `pas + fenetre` du signal -- 45 s pour un pas de 15 s. Le replay, qui exige une
        # reference a `max_reference_lag_ms` pres, refusait alors : mesure du 19/11/2026,
        # `STALE_OR_MISSING_REFERENCE_BOOK` sur 418 candidats de VALIDATION sur 418 et 623 sur 636
        # en OOS. Ces deux instants sont connus exactement, et ils decident de l'episode : on les
        # garde tels quels.
        exactes.add(t)
        exactes.add(t + int(delai_ms))
        # Les sorties, elles, se quantifient sans dommage : leur cible depend de l'horizon cherche
        # ET de l'instant d'entree reel, donc elle est deja approximative a quelques secondes.
        # C'est ce qui empeche le budget de croitre avec le nombre de signaux voisins.
        for horizon in horizons_ms:
            crans.add((t + int(delai_ms) + int(horizon)) // pas)
    return sorted(exactes | {cran * pas for cran in crans})

def une_seule_connexion_par_coin(
    carnets: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Ne laisser au replay, pour chaque coin, que l'observateur le plus continu.

    POURQUOI (mesure du 19/11/2026). Le replay refuse un episode dont la reference, l'entree et
    la sortie ne portent pas la MEME `connection_id` : c'est `L2_CONNECTION_GAP_CROSSED`, et c'est
    une regle juste -- trois carnets venus de trois flux differents ne prouvent pas qu'on aurait
    observe le marche sans interruption. Mais plusieurs lanes observent le meme coin en meme
    temps : sur la tranche t001, BTC portait une connexion longue (151 minutes d'affilee) PLUS
    neuf reconnexions qui se relaient toutes les dix a vingt-cinq minutes. Le replay, qui prend le
    carnet le plus proche sans regarder l'identite, melangeait les deux et refusait : 250 des 262
    candidats de TRAIN, soit 95 % des refus, pour un trou qui n'existait pas.

    On choisit donc la connexion qui couvre le plus d'instants distincts, coin par coin, et on
    COMPTE ce qu'on ecarte. Ce filtre s'applique APRES la lecture, ce qui serait un defaut s'il
    portait sur un volume non borne -- ce n'est pas le cas : `carnets_du_coffre` a deja limite a un
    carnet par ancre, par cote et par connexion.
    """
    gardes: dict[str, list[dict[str, Any]]] = {}
    ecartes = 0
    coins_mono = 0
    for coin, liste in carnets.items():
        groupes: dict[Any, list[dict[str, Any]]] = {}
        for brut in liste:
            groupes.setdefault(brut.get("connection_id"), []).append(dict(brut))
        if len(groupes) <= 1:
            coins_mono += 1
            gardes[str(coin)] = [dict(x) for x in liste]
            continue
        # PLUSIEURS CONNEXIONS, MAIS JAMAIS DEUX EN MEME TEMPS.
        #
        # Premiere version : garder LA connexion la plus etendue, pour tout le corpus. Mesure du
        # 19/11/2026, qui l'a refutee : une lane L2 vit quelques heures, pas six journees. Choisir
        # globalement laissait donc **un seul coin couvert le 13/11 et treize le 14**, alors que
        # TRAIN est precisement le 13-15 ; 365 819 carnets tombaient a 64 024, et 418 candidats de
        # VALIDATION sur 418 etaient refuses faute du moindre carnet.
        #
        # Ce que le replay exige n'est pas une connexion unique, c'est qu'un EPISODE n'en traverse
        # pas deux. On garde donc plusieurs connexions par coin, a condition qu'elles ne se
        # recouvrent pas : les periodes se succedent, chacune servie par un seul observateur. Un
        # episode a cheval sur une frontiere sera refuse -- et il le merite, l'observateur a
        # vraiment change.
        intervalles: list[tuple[int, int, Any, list[dict[str, Any]]]] = []
        for identite, groupe in groupes.items():
            horodatages = [int(x["ts_ms"]) for x in groupe]
            intervalles.append((min(horodatages), max(horodatages), identite, groupe))
        # Du plus long au plus court : une connexion longue vaut mieux que deux courtes, puisque
        # c'est la duree qui decide si un episode tient dedans.
        intervalles.sort(key=lambda bloc: (bloc[0] - bloc[1], bloc[0]))
        pris: list[tuple[int, int]] = []
        retenus_du_coin: list[dict[str, Any]] = []
        for debut, fin, _identite, groupe in intervalles:
            if any(debut <= f and d <= fin for d, f in pris):
                continue        # recouvrement : cette connexion ferait un melange
            pris.append((debut, fin))
            retenus_du_coin.extend(dict(x) for x in groupe)
        retenus_du_coin.sort(key=lambda x: int(x["ts_ms"]))
        ecartes += len(liste) - len(retenus_du_coin)
        gardes[str(coin)] = retenus_du_coin
    audit = {
        "coins": len(gardes),
        "coins_a_connexion_unique": coins_mono,
        "carnets_gardes": sum(len(v) for v in gardes.values()),
        "ecartes_connexion_minoritaire": ecartes,
    }
    return gardes, audit


def carnets_du_coffre(
    racine: str | Path,
    *,
    coins: Sequence[str],
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DE_CARNETS,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
    instants_par_coin: Mapping[str, Sequence[int]] | None = None,
    par_ancre: int = 1,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Lit les carnets du COFFRE en flux, et ne garde que ceux a portee d'un signal.

    POURQUOI LE COFFRE ET PAS LES RUBANS LOCAUX. `load_observed_books` lit
    `runtime/data/*.jsonl`. Mesure du 18/11/2026 : ces rubans commencent au **17/11 18:35**, alors
    que le coffre porte `bbo` et `book_l2` depuis le **26/10**. Une phase 1 branchee sur les rubans
    locaux prepare donc du vide pour toutes les tranches anterieures au 17/11 -- et rend
    honnetement `0/0`, ce qui ressemble a « pas de carnets » alors que la vraie cause est « pas
    regarde au bon endroit ».

    LE FILTRAGE SE FAIT EN FLUX, jamais apres. On ne materialise que les carnets retenus : c'est ce
    qui permet de traverser 111 millions de lignes de `bbo` sans les accumuler. Si on chargeait
    pour filtrer ensuite, l'economie de la phase 1 serait perdue d'avance.
    """
    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return {}, {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    shards_tous = brut.get("shards") or brut.get("entrees") or []
    if isinstance(shards_tous, dict):
        shards_tous = list(shards_tous.values())

    # Les ANCRES, par coin : la ou le replay cherchera un carnet. Pas les instants de signal --
    # voir `ancres_utiles`, qui dit pourquoi un filtre pose sur les signaux seuls jetait les
    # carnets de sortie.
    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS

    horizons = tuple(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    pas_ms = max(1, int(fenetre_ms) // 2)
    tolerance_ms = int(fenetre_ms) + pas_ms
    cibles: dict[str, list[int]] = {}
    if instants_par_coin:
        cibles = {
            str(coin): ancres_utiles(
                [int(x) for x in instants],
                delai_ms=int(cv.COPY_DELAY_MS),
                horizons_ms=horizons,
                pas_ms=pas_ms,
            )
            for coin, instants in instants_par_coin.items()
        }

    apres_ms = _fenetre_apres_signal()
    densite: dict[tuple[str, int, int, Any], list[tuple[int, int]]] = {}
    trop_denses = 0
    incomplets = 0
    ecartes_sans_signal = 0
    homonymes = 0
    sans_identite = 0
    ecartes_hors_tolerance = 0
    sans_coin_ou_horloge = 0
    gardes: dict[str, list[dict[str, Any]]] = {}
    par_famille: dict[str, dict[str, int]] = {}
    for famille in familles:
        choix = coffre_tranches.selectionner(
            shards_tous, famille=famille, coins=list(coins),
            debut_ms=debut_ms - fenetre_ms, fin_ms=fin_ms + apres_ms)
        shards = choix.get("shards") or choix.get("retenus") or []
        if not shards:
            par_famille[famille] = {"shards": 0, "lus": 0, "gardes": 0}
            continue
        horloge = coffre_tranches.horloge_de(famille)
        lus = retenus = 0
        exploitables_vues = 0
        abandonnee = False
        for ligne in coffre_tranches.flux(
            racine, shards, famille=famille, coins=list(coins),
            debut_ms=debut_ms - fenetre_ms, fin_ms=fin_ms + apres_ms, verifier_sha=False,
        ):
            lus += 1
            coin = str(ligne.get("coin") or ligne.get("symbole") or "")
            ts = ligne.get(horloge, ligne.get("ts_ms"))
            if not coin or ts is None:
                # SECOND REJET MUET (20/11/2026). Une ligne sans coin ou sans l horloge de sa
                # famille sortait par un `continue` nu. Avec les autres motifs non affiches,
                # l audit annoncait « 99,1 % ecartees » en n en expliquant que 2,6 % : on ne
                # pouvait pas distinguer une selection saine d une perte.
                sans_coin_ou_horloge += 1
                continue
            ts = int(ts)
            # LES CHAMPS D'ABORD, LE BUDGET ENSUITE. Le replay exige `bid`, `ask` et
            # `capacity_usd` ; les cinq familles du coffre n'ont pas le meme schema, et il levait
            # `KeyError: 'ask'` apres 60 candidats. Une donnee incomplete se REFUSE et se COMPTE,
            # elle ne fait pas tomber la mesure. Mais l'ordre compte autant que le refus : tant que
            # ce controle venait APRES le budget par ancre, un carnet inutilisable consommait la
            # place du seul carnet gardee pour cette ancre, et un carnet complet arrive juste apres
            # etait refuse comme « trop dense ». Un test du chantier l'a attrape -- il comptait
            # trois refus de champs et en recevait zero, parce que les trois etaient deja tombes
            # dans le plafond.
            if any(ligne.get(champ) is None for champ in ("bid", "ask", "capacity_usd")):
                incomplets += 1
                if lus >= SONDAGE_FAMILLE and exploitables_vues == 0:
                    # Cette famille n a pas le schema d un carnet : la lire jusqu au bout
                    # coute des millions de lignes pour rien. On l abandonne EN LE DISANT.
                    abandonnee = True
                    break
                continue
            exploitables_vues += 1
            # ET UNE IDENTITE DE CONNEXION, sans quoi l'episode sera refuse de toute façon.
            #
            # Le replay exige que les trois carnets d'un episode portent une `connection_id` et un
            # `l2_gap_epoch` (`L2_CONNECTION_IDENTITY_INCOMPLETE` sinon) : c'est ainsi qu'il prouve
            # qu'on observait le marche SANS interruption. Un carnet qui n'en a pas ne peut pas
            # participer a cette preuve.
            #
            # Mesure du 19/11/2026 : 34,8 % des carnets des tranches t021 et suivantes sont des
            # snapshots ponctuels de source `HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT` -- une
            # interrogation REST au moment d'un fill, pas un flux persistant, donc sans identite ni
            # epoque. Ce sont eux qui portaient le `checkpoint_id` homonyme. Les laisser passer
            # faisait refuser 344 candidats de VALIDATION sur 425 et 473 sur 628 en OOS, et pire :
            # ils CONSOMMAIENT le budget d'une ancre au detriment d'un carnet utilisable.
            #
            # CE QU'ON PERD, ET IL FAUDRA Y REVENIR : ces snapshots sont causaux et poses pile au
            # moment d'un fill, donc ce sont d'excellentes references. Le replay a un chemin pour
            # eux (`EXACT_METAORDER_CHECKPOINTS`, qui n'exige aucune identite) mais il demande des
            # `checkpoint_id` de la forme `{metaorder_id}:REFERENCE` -- un apparaige que le coffre
            # ne fournit pas. Les rendre utilisables est un chantier a part, pas un filtre.
            identite = ligne.get("connection_id")
            epoque = ligne.get("l2_gap_epoch")
            if (
                not isinstance(identite, str) or not identite
                or type(epoque) is not int or epoque < 0
            ):
                sans_identite += 1
                continue
            ancres = cibles.get(coin)
            if ancres is None and instants_par_coin is not None:
                # PAS DE SIGNAL SUR CE COIN = PAS DE CARNET. Sans cette ligne, un coin absent du
                # dictionnaire des instants echappait au filtre et faisait garder TOUTE la
                # fenetre : mesure du 19/11/2026, une tranche dont les signaux avaient tous ete
                # ecartes en amont a retenu 268 674 carnets pour **zero** metaordre, et c'est la
                # memoire qui l'a dit, pas l'audit. « Aucun filtre demande » (`instants_par_coin`
                # a None) et « ce coin n'interesse personne » doivent se distinguer.
                ecartes_sans_signal += 1
                continue
            if ancres is not None:
                # L'ANCRE LA PLUS PROCHE, des deux cotes. Un carnet ne sert que s'il repond a une
                # ancre : le replay prend le dernier au plus tard a la reference et le premier a
                # partir de l'entree puis de la sortie, chacun a `fenetre_ms` pres au maximum.
                # La tolerance vaut `fenetre_ms` PLUS le pas de quantification : une ancre est
                # arrondie vers le bas, donc l'instant vraiment cherche peut se trouver jusqu'a un
                # pas plus loin. Serrer la tolerance sur `fenetre_ms` seul rejetterait des carnets
                # que le replay aurait acceptes -- la meme erreur, en plus petit, que la fenetre
                # unilaterale qui rendait zero trade.
                i = bisect.bisect_left(ancres, ts)
                proche: int | None = None
                for j in (i - 1, i):
                    if (
                        0 <= j < len(ancres)
                        and abs(ancres[j] - ts) <= tolerance_ms
                        and (proche is None or abs(ancres[j] - ts) < abs(ancres[proche] - ts))
                    ):
                        proche = j
                if proche is None:
                    # LE REJET LE PLUS MASSIF ETAIT MUET (20/11/2026). L audit annoncait
                    # « 99,1 % ecartees » sans pouvoir dire pourquoi : seuls deux motifs
                    # mineurs etaient comptes, et celui-ci -- aucun signal assez proche --
                    # sortait par un `continue` nu. Un rejet massif sans motif empeche de
                    # distinguer une selection saine d une perte, et c est exactement ce qui
                    # a coute une nuit sur les fills.
                    ecartes_hors_tolerance += 1
                    continue
                # UN CARNET DE CHAQUE COTE DE L'ANCRE, PAR CONNEXION. Le cote compte parce que la
                # reference se cherche en arriere et l'entree en avant : un budget qui les melange
                # peut rendre deux carnets du meme cote et laisser l'autre vide. La CONNEXION
                # compte parce que le replay refuse un episode dont les trois carnets ne partagent
                # pas la meme identite (`L2_CONNECTION_GAP_CROSSED`) : mesure du 19/11/2026, 250
                # des 262 candidats de TRAIN refuses pour cette seule raison, parce que plusieurs
                # lanes observent le MEME coin -- une connexion longue plus des reconnexions qui
                # se relaient toutes les ~20 minutes. Garder un carnet par connexion laisse au
                # replay une suite coherente a choisir, au lieu d'un melange qu'il doit refuser.
                #
                # ET QUAND LE BUDGET EST PLEIN, ON GARDE LE PLUS PROCHE, pas le premier arrive.
                # Les familles sont lues l'une apres l'autre : garder le premier ferait dependre
                # la reference choisie de l'ORDRE DE LECTURE, donc rendrait la mesure sensible a
                # un detail qui n'a aucun sens economique. Un test du chantier attendait deux
                # references pour une meme ancre, a 10 ms et a 30 s du signal : le replay n'en lit
                # qu'une, et c'est la plus proche qui dit la verite du marche a cet instant.
                cote = 0 if ts <= ancres[proche] else 1
                clef = (coin, proche, cote, ligne.get("connection_id"))
                ecart = abs(ancres[proche] - ts)
                places = densite.setdefault(clef, [])
                remplace: int | None = None
                if len(places) >= par_ancre:
                    rang_pire = max(range(len(places)), key=lambda k: places[k][1])
                    if ecart >= places[rang_pire][1]:
                        trop_denses += 1
                        continue
                    remplace = rang_pire
            carnet = dict(ligne)
            carnet["ts_ms"] = ts
            carnet.setdefault("coin", coin)
            carnet["_famille_coffre"] = famille
            # `source_line` est une REFERENCE DE PROVENANCE que le replay inscrit dans chaque
            # trade (`entry_source_line`, `exit_source_line`) pour qu'on puisse remonter au
            # carnet exact qui a servi. Les carnets des rubans locaux la portent ; ceux du coffre
            # non, et le replay levait `KeyError: 'source_line'`. On y met le RANG REEL de la
            # ligne dans la famille lue -- pas un numero invente : une provenance fausse serait
            # pire qu'absente, puisqu'elle designerait le mauvais carnet.
            carnet.setdefault("source_line", f"{famille}:{lus}")
            # `checkpoint_id` EST UN HOMONYME, et il decidait de la mesure.
            #
            # Pour le replay, un `checkpoint_id` designe un point de controle lie
            # CRYPTOGRAPHIQUEMENT a un metaordre : il attend la forme `{metaorder_id}:REFERENCE`,
            # `{metaorder_id}:ENTRY`, `{metaorder_id}:EXIT:{horizon}`. Pour le collecteur de
            # `book_l2`, c'est l'identifiant d'un snapshot -- un hash, sans aucun rapport. Or
            # `index_des_carnets(...).continus()` EXCLUT tout carnet qui en porte un.
            #
            # Mesure du 19/11/2026 : le champ apparait a partir de la tranche t021, soit le 16/11,
            # donc exactement sur VALIDATION et OOS. 46 % des carnets du corpus de phase 2 en
            # portaient un -- et c'etait la connexion la plus etendue, celle que le filtre de
            # connexion privilegie. Resultat : 425 candidats de VALIDATION sur 425 et 613 sur 628
            # en OOS refuses en `STALE_OR_MISSING_REFERENCE_BOOK`, alors que 1 322 signaux sur
            # 1 969 avaient bien un carnet a moins de 30 s. Une evolution de la collecte avait
            # casse le replay sans que rien ne le dise.
            #
            # On RENOMME au lieu de jeter : la provenance reste lisible, mais elle ne se fait plus
            # passer pour ce qu'elle n'est pas.
            if "checkpoint_id" in carnet:
                carnet["checkpoint_id_coffre"] = carnet.pop("checkpoint_id")
                homonymes += 1
            liste_du_coin = gardes.setdefault(coin, [])
            if ancres is None:
                liste_du_coin.append(carnet)
                retenus += 1
            elif remplace is None:
                places.append((len(liste_du_coin), ecart))
                liste_du_coin.append(carnet)
                retenus += 1
            else:
                # Le carnet plus lointain cede sa place : rien n'est ajoute, donc `retenus` ne
                # bouge pas, et `trop_denses` compte celui qui sort -- un seul carnet occupe la
                # place a la fin, quel que soit l'ordre dans lequel les familles ont ete lues.
                rang_liste = places[remplace][0]
                liste_du_coin[rang_liste] = carnet
                places[remplace] = (rang_liste, ecart)
                trop_denses += 1
        par_famille[famille] = {"shards": len(shards), "lus": lus, "gardes": retenus,
                                "abandonnee_sans_champs_de_carnet": abandonnee}

    for liste in gardes.values():
        liste.sort(key=lambda c: int(c["ts_ms"]))
    audit = {
        "status": "LU_DEPUIS_LE_COFFRE",
        "familles": par_famille,
        "lignes_lues": sum(v["lus"] for v in par_famille.values()),
        "carnets_gardes": sum(v["gardes"] for v in par_famille.values()),
        "coins_avec_carnets": len(gardes),
        "fenetre_ms": int(fenetre_ms),
        "ecartes_trop_denses": trop_denses,
        "ecartes_champs_manquants": incomplets,
        "ecartes_coin_sans_signal": ecartes_sans_signal,
        "ecartes_aucun_signal_assez_proche": ecartes_hors_tolerance,
        "checkpoint_id_renommes": homonymes,
        "ecartes_sans_identite_de_connexion": sans_identite,
        "ecartes_sans_coin_ou_horloge": sans_coin_ou_horloge,
        "par_ancre": int(par_ancre),
        "ancres": sum(len(v) for v in cibles.values()),
    }
    # L AUDIT PROUVE SA PROPRE CONSERVATION. Un audit qui annonce un taux de rejet sans
    # pouvoir l expliquer ligne a ligne ne vaut rien : c est ainsi qu une PERTE se deguise en
    # SELECTION. `non_explique` doit rester a zero ; s il bouge, un filtre muet est apparu.
    audit["non_explique"] = audit["lignes_lues"] - audit["carnets_gardes"] - sum(
        int(v) for k, v in audit.items() if k.startswith("ecartes_"))
    return gardes, audit

#: Les familles du coffre qui portent des fills du leader.
#:
#: `fills_forward` compte 21 591 873 lignes sur 23 journees (13 avril -> 18 novembre), dont 1,4 a
#: 2,3 millions par jour depuis le 13/11 -- TOUTES marquees `causal_forward_eligible`. Le ruban
#: local `runtime/data/vault_fills_live.jsonl` ne couvre que 17/11 19:10 -> 18/11 22:06, parce
#: qu'il ne retient que la source `LIVE_WS`. Le coffre porte en plus `LIVE_POLL`, une collecte par
#: interrogation active depuis le 13/11 et tout aussi causale : le labo ignorait une source
#: entiere de signaux valides. Mesure du 18/11/2026 : 2 journees exploitables par le ruban local,
#: 6 par le coffre.
FAMILLES_DE_FILLS = ("fills_forward",)

#: Le libelle Hyperliquid -> l'action du protocole. Seules OPEN et ADD sont copiables.
_ACTION_PAR_LIBELLE = {
    "open long": "OPEN",
    "open short": "OPEN",
    "close long": "CLOSE",
    "close short": "CLOSE",
}

#: Jusqu'a quand une position observee renseigne encore un fill. Les observations tombent toutes
#: les 57 s en mediane et toutes les 299 s au neuvieme decile (mesure du 19/11/2026) : au-dela de
#: cinq minutes, on ne sait plus, et on le DIT.
MAX_AGE_POSITION_MS = 300_000


def positions_du_coffre(
    racine: str | Path, *, debut_ms: int, fin_ms: int
) -> tuple[dict[tuple[str, str], list[tuple[int, float]]], dict[str, Any]]:
    """La position signee (`szi`) de chaque leader par coin, observee et triee.

    POURQUOI IL FAUT LA LIRE. La politique gelee ne copie que les RENFORCEMENTS, et distinguer un
    renforcement d'une ouverture demande de savoir si le leader detenait deja. Cette information
    manque a 99,6 % des fills du coffre : `start_position` n'est renseigne que par `LIVE_WS`
    (434 lignes sur 117 137 pour une heure), jamais par `LIVE_POLL`. La famille `position` la
    porte autrement -- `szi`, source `CLEARINGHOUSE_WS`, `data_origin: REAL_OBSERVED`.

    On lit une heure AVANT la fenetre demandee : une position observee juste avant son debut
    renseigne les premiers fills, et l'oublier les rendrait faussement indeterminés.
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
    debut_lecture = int(debut_ms) - MAX_AGE_POSITION_MS - 3_600_000
    choix = coffre_tranches.selectionner(
        tous, famille="position", coins=None, debut_ms=debut_lecture, fin_ms=int(fin_ms))
    shards = choix.get("shards") or choix.get("retenus") or []
    if not shards:
        return {}, {"status": "AUCUN_SHARD_DE_POSITION", "shards": 0}
    series: dict[tuple[str, str], list[tuple[int, float]]] = {}
    lus = gardes = 0
    for ligne in coffre_tranches.flux(
        racine, shards, famille="position", coins=None,
        debut_ms=debut_lecture, fin_ms=int(fin_ms), verifier_sha=False,
    ):
        lus += 1
        instant = ligne.get("received_at_ms")
        if isinstance(instant, bool) or not isinstance(instant, (int, float)):
            continue
        try:
            szi = float(ligne["szi"])
        except (KeyError, TypeError, ValueError):
            continue
        cle = (str(ligne.get("vault") or ""), str(ligne.get("coin") or ""))
        if not cle[0] or not cle[1]:
            continue
        series.setdefault(cle, []).append((int(instant), szi))
        gardes += 1
    for serie in series.values():
        serie.sort(key=lambda couple: couple[0])
    return series, {
        "status": "LU_DEPUIS_LE_COFFRE", "shards": len(shards), "lignes_lues": lus,
        "observations_gardees": gardes, "couples_vault_coin": len(series),
    }


def position_avant(
    series: Mapping[tuple[str, str], Sequence[tuple[int, float]]],
    *, vault: str, coin: str, instant_ms: int,
    age_max_ms: int = MAX_AGE_POSITION_MS,
) -> float | None:
    """La derniere position observee AU PLUS TARD a `instant_ms`, ou `None` si on ne sait pas.

    Causal par construction : on ne regarde jamais apres le fill, sans quoi on lirait l'avenir
    pour decider s'il faut copier. Et `None` veut dire « inconnu » -- jamais zero, qui
    affirmerait que le leader n'avait pas de position.
    """
    serie = series.get((str(vault), str(coin)))
    if not serie:
        return None
    rang = bisect.bisect_right([instant for instant, _ in serie], int(instant_ms)) - 1
    if rang < 0:
        return None
    instant, szi = serie[rang]
    if int(instant_ms) - instant > int(age_max_ms):
        return None
    return szi


def _nombre_normalise(valeur) -> str | None:
    """Un nombre rendu de facon STABLE, pour qu une meme taille s ecrive pareil partout.

    Les deux sources peuvent ecrire 8.3998 et "8.39980" : sans normalisation numerique, la
    cle stricte verrait deux fills differents et le MEME fill serait compte DEUX FOIS.
    """
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        return repr(float(valeur))
    except (TypeError, ValueError):
        return None


def _empreinte_du_fill(ligne) -> str:
    """L identite STRICTE d un fill, ou "" si elle n est pas prouvable.

    POURQUOI NI `hash` NI `tid` NE SUFFISENT (mesures du 19/11/2026).

    * `hash` est le hash de la TRANSACTION, pas du fill : une transaction en contient
      plusieurs. 3,9 % des identites portaient des directions contradictoires sur le meme
      hash (`Close Long` ET `Open Short`). Deduire l identite du hash DETRUISAIT des fills
      distincts : ~200 000 par journee, 12 % des lignes lues. Un hash entierement nul
      (`0x000...0`) etait meme le plus frequent des deux familles, 4,4 % et 6,3 %.
    * `tid` non plus : il groupe des fills PARTIELS -- le flux WS diffuse les morceaux et le
      REST renvoie l agregat. 1 142 `tid` portaient des tailles differentes (ETC 0.25 et
      ETC 7.98, meme compte, meme prix).

    L IDENTITE RETENUE est donc le tuple complet qui decrit le fill lui-meme. Verifiee sur une
    heure reelle lue dans LES DEUX familles (18/11 12h-13h UTC, 80 225 lignes) : 15 132 noyaux
    revus plusieurs fois, dont 14 942 presents dans les deux familles -- donc les vrais
    doublons inter-sources sont bien attrapes -- et ZERO noyau a direction divergente, donc la
    cle ne SCINDE jamais un doublon reel.

    POURQUOI `ts_ms` EN FAIT PARTIE. Sans lui, deux remplissages PARTIELS de meme taille au
    meme prix sur le meme compte fusionnaient, donc une observation reelle disparaissait --
    defaut attrape par `test_une_position_declaree_decide_l_action`. L ajouter ne risquait de
    scinder un vrai doublon que si les deux sources dataient le meme fill differemment :
    mesure sur l heure commune du 18/11, les comptes sont RIGOUREUSEMENT identiques avec et
    sans `ts_ms` (63 187 noyaux, 15 132 doublons, 14 942 inter-familles). Elles le datent donc
    pareil, et l ajout est sur.

    DENY-BY-DEFAULT : sans de quoi decrire le fill, on ne declare pas de doublon et on garde
    les deux lignes. Declarer un doublon a tort DETRUIT une observation ; en manquer un la
    laisse comptee deux fois, ce qui GONFLE le signal donc le PnL -- c est pourquoi la cle
    doit etre assez riche pour separer, et assez stable pour reunir.
    """
    coin = str(ligne.get("coin") or "").strip()
    compte = str(ligne.get("vault") or ligne.get("user") or "").strip()
    taille = _nombre_normalise(ligne.get("sz"))
    instant = _nombre_normalise(ligne.get("ts_ms"))
    prix = _nombre_normalise(ligne.get("px"))
    if not coin or not compte or taille is None or prix is None or instant is None:
        return ""   # identite non prouvable -> jamais declare doublon
    tid = ligne.get("tid")
    marque = str(tid).strip() if (not isinstance(tid, bool) and tid is not None) else ""
    sens = str(ligne.get("dir") or "").strip().lower()
    return "|".join(("f2", marque, coin, compte, taille, prix, sens, instant))

def fills_du_coffre(
    racine: str | Path,
    *,
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DE_FILLS,
    positions: Mapping[tuple[str, str], Sequence[tuple[int, float]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lit les fills du COFFRE et les met au format que `cluster_metaorders` attend.

    LE MAPPING EST DERIVE, JAMAIS INVENTE. Un fill du coffre porte deja `ts_ms`, `coin`, `vault`,
    `px`, `sz`, `observed_at_ms`, `received_at_ms`, `connection_id` et `causal_forward_eligible`.
    Trois champs manquent, et chacun se CALCULE a partir de ce qui est la :

      * `direction` <- `signe` (±1), l'orientation du fill telle que la plateforme l'a publiee ;
      * `action` <- `dir` (« Open Long », « Close Short »...), traduit par un tableau explicite.
        Un libelle inconnu donne `None`, donc l'evenement est ECARTE au lieu d'etre devine ;
      * `taille_usd` <- `px * sz`, le notionnel du fill.

    Rien n'est suppose : un fill sans prix, sans taille ou sans libelle reconnu est compte dans
    l'audit et laisse de cote. Inventer une direction ou une action reviendrait a fabriquer des
    signaux, c'est-a-dire a fabriquer le PnL qu'on cherche a mesurer.
    """
    from hl_observer.backtesting import coffre_tranches

    racine = Path(racine)
    index = racine / "runtime/coffre_certifie/LOCAL_INDEX.json"
    if not index.exists():
        return [], {"status": "COFFRE_ABSENT", "chemin": str(index)}

    brut = json.loads(index.read_text(encoding="utf-8"))
    tous = brut.get("shards") or []
    if isinstance(tous, dict):
        tous = list(tous.values())

    entrees: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "status": "LU_DEPUIS_LE_COFFRE", "lignes_lues": 0, "entrees_rendues": 0,
        "ecartes_libelle_inconnu": 0, "ecartes_champ_manquant": 0, "familles": {},
        "actions": {}, "ecartes_position_inconnue": 0, "doublons_de_hash": 0,
        "doublons_plus_informatifs": 0,
    }
    # LE MEME FILL ARRIVE DEUX FOIS, et la moins informative des deux copies gagnait.
    #
    # `LIVE_POLL` et `LIVE_WS` rapportent le meme fill -- meme `hash`, meme `ts_ms`, meme `sz` --
    # mais `LIVE_WS` seul porte `start_position`. Mesure du 19/11/2026 : 117 137 lignes brutes
    # pour 54 072 fills distincts, et 434 couples divergeaient sur ce champ. `cluster_metaorders`
    # ecartait ensuite l'une des deux comme doublon (52 142 pour une heure) en gardant LA PREMIERE
    # VENUE : les 915 renforcements reels se faisaient ecraser par leur jumeau sans position, et
    # il sortait **zero ADD**. On deduplique donc ici, sur le `hash` du fill, en gardant toujours
    # la copie qui porte la position -- la plus informative, pas la plus rapide.
    par_hash: dict[str, int] = {}
    for famille in familles:
        choix = coffre_tranches.selectionner(
            tous, famille=famille, debut_ms=debut_ms, fin_ms=fin_ms)
        # `selectionner` rend ses shards sous la cle `retenus`.
        shards = choix.get("retenus") or choix.get("shards") or []
        lus = rendus = 0
        for ligne in coffre_tranches.flux(
            racine, shards, famille=famille,
            debut_ms=debut_ms, fin_ms=fin_ms, verifier_sha=False,
        ):
            lus += 1
            action = _ACTION_PAR_LIBELLE.get(str(ligne.get("dir") or "").strip().lower())
            if action is None:
                audit["ecartes_libelle_inconnu"] += 1
                continue
            if action == "OPEN":
                # OPEN ou ADD : la distinction NE SE LIT PAS dans `dir`, qui dit « Open Long »
                # aussi bien pour une ouverture que pour un renforcement. Elle demande la position
                # du leader AVANT ce fill -- et cette position, il faut la LIRE, jamais la
                # supposer.
                #
                # LE DEFAUT QUE CECI REPARE (19/11/2026), et c'est la cause racine du refus
                # unanime du labo. Cette ligne faisait `float(ligne.get("start_position") or 0.0)`
                # puis `ADD si != 0`. Or `start_position` n'est renseigne que par `LIVE_WS` : 434
                # lignes sur 117 137 pour une heure, soit **0,4 %**. Le `or 0.0` transformait donc
                # « on ne sait pas » en « position nulle », donc en `OPEN`, pour 99,6 % du corpus.
                # La politique ne copiant que les `ADD`, elle refusait tout (`NON_ADD_REJECTED`) :
                # 0 ADD sur 50 581 metaordres, 0 candidat, 0 trade, 11 391 essais rejetes sans
                # qu'aucune porte ne soit en cause. Un zero invente n'etait meme pas favorable au
                # PnL ici -- il faisait disparaitre les candidats, ce qui se voit encore moins.
                #
                # Trois issues, donc, et jamais une valeur par defaut : l'observation directe du
                # fill si elle existe, sinon la position observee par la famille `position` du
                # coffre (causale, au plus `MAX_AGE_POSITION_MS` avant le fill), sinon un REFUS
                # COMPTE.
                declaree = ligne.get("start_position")
                avant: float | None = None
                if not isinstance(declaree, bool) and isinstance(declaree, (int, float)):
                    avant = float(declaree)
                elif positions is not None:
                    avant = position_avant(
                        positions,
                        vault=str(ligne.get("vault") or ligne.get("user") or ""),
                        coin=str(ligne.get("coin") or ""),
                        instant_ms=int(ligne.get("ts_ms") or 0),
                    )
                if avant is None:
                    audit["ecartes_position_inconnue"] += 1
                    continue
                if avant != 0.0:
                    action = "ADD"
            try:
                signe = int(ligne["signe"])
                prix = float(ligne["px"])
                taille = float(ligne["sz"])
            except (KeyError, TypeError, ValueError):
                audit["ecartes_champ_manquant"] += 1
                continue
            if signe not in (-1, 1) or prix <= 0 or taille <= 0:
                audit["ecartes_champ_manquant"] += 1
                continue
            entree = dict(ligne)
            entree["direction"] = signe
            entree["action"] = action
            entree["taille_usd"] = prix * taille
            empreinte = _empreinte_du_fill(ligne)
            deja = par_hash.get(empreinte) if empreinte else None
            if deja is None:
                if empreinte:
                    par_hash[empreinte] = len(entrees)
                entrees.append(entree)
                audit["actions"][action] = audit["actions"].get(action, 0) + 1
                rendus += 1
                continue
            # Deja vu : on ne garde la nouvelle copie que si elle sait quelque chose que l'autre
            # ignorait -- la position du leader. Un doublon n'ajoute jamais un fill, il peut
            # seulement en corriger un.
            audit["doublons_de_hash"] += 1
            ancienne = entrees[deja]
            savait = not isinstance(ancienne.get("start_position"), bool) and isinstance(
                ancienne.get("start_position"), (int, float))
            sait = not isinstance(ligne.get("start_position"), bool) and isinstance(
                ligne.get("start_position"), (int, float))
            if sait and not savait:
                # On RETIRE la cle tombee a zero : un `{"OPEN": 0}` dans l'audit se lit « il y a
                # eu des ouvertures », alors qu'il n'en reste aucune apres correction.
                audit["actions"][ancienne["action"]] -= 1
                if audit["actions"][ancienne["action"]] <= 0:
                    del audit["actions"][ancienne["action"]]
                audit["actions"][action] = audit["actions"].get(action, 0) + 1
                audit["doublons_plus_informatifs"] += 1
                entrees[deja] = entree
        audit["familles"][famille] = {"shards": len(shards), "lus": lus, "rendus": rendus}
        audit["lignes_lues"] += lus
        audit["entrees_rendues"] += rendus
    entrees.sort(key=lambda e: int(e["ts_ms"]))
    return entrees, audit
