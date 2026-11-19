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

def carnets_du_coffre(
    racine: str | Path,
    *,
    coins: Sequence[str],
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DE_CARNETS,
    fenetre_ms: int = MAX_BOOK_AGE_MS,
    instants_par_coin: Mapping[str, Sequence[int]] | None = None,
    par_signal: int = 240,
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

    # Les instants de signal, par coin, pour filtrer au vol.
    cibles: dict[str, list[int]] = {}
    if instants_par_coin:
        cibles = {str(k): sorted(int(x) for x in v) for k, v in instants_par_coin.items()}

    apres_ms = _fenetre_apres_signal()
    densite: dict[tuple[str, int], int] = {}
    trop_denses = 0
    incomplets = 0
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
        for ligne in coffre_tranches.flux(
            racine, shards, famille=famille, coins=list(coins),
            debut_ms=debut_ms - fenetre_ms, fin_ms=fin_ms + apres_ms, verifier_sha=False,
        ):
            lus += 1
            coin = str(ligne.get("coin") or ligne.get("symbole") or "")
            ts = ligne.get(horloge, ligne.get("ts_ms"))
            if not coin or ts is None:
                continue
            ts = int(ts)
            instants = cibles.get(coin)
            if instants is not None:
                # DES DEUX COTES du signal : avant pour la reference, apres pour l'entree et la
                # sortie. Ne regarder qu'en arriere jetait les carnets d'entree et de sortie, et
                # le replay rendait zero trade sur 4 000 signaux.
                i = bisect.bisect_left(instants, ts - apres_ms)
                if not (i < len(instants) and instants[i] - ts <= fenetre_ms):
                    continue
                # ET PAS PLUS DE `par_signal` CARNETS PAR SIGNAL. Le replay n'a besoin que de
                # TROIS carnets -- reference, entree, sortie -- mais la fenetre d'une heure en
                # contient des milliers, et les fenetres de signaux voisins se recouvrent : mesure
                # du 19/11/2026, 459 signaux retenaient 1 950 464 carnets. On garde les premiers
                # de chaque fenetre, qui sont les plus proches des instants cibles ; au-dela, un
                # carnet de plus n'ajoute aucune information que le replay saurait lire.
                vus_du_signal = densite.get((coin, i), 0)
                if vus_du_signal >= par_signal:
                    trop_denses += 1
                    continue
                densite[(coin, i)] = vus_du_signal + 1
            # LE REPLAY EXIGE CES CHAMPS : `bid`, `ask` et `capacity_usd`. Les cinq familles de
            # carnets du coffre n'ont pas le meme schema -- `bbo` et `book_l2` portent les deux
            # cotes, d'autres non -- et le replay levait `KeyError: 'ask'` apres 60 candidats.
            # Une donnee incomplete se REFUSE et se COMPTE, elle ne fait pas tomber la mesure :
            # c'est la regle du contrat, et c'est aussi la seule façon de savoir ce qui manque.
            if any(ligne.get(champ) is None for champ in ("bid", "ask", "capacity_usd")):
                incomplets += 1
                continue
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
            gardes.setdefault(coin, []).append(carnet)
            retenus += 1
        par_famille[famille] = {"shards": len(shards), "lus": lus, "gardes": retenus}

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
        "par_signal": int(par_signal),
    }
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

def fills_du_coffre(
    racine: str | Path,
    *,
    debut_ms: int,
    fin_ms: int,
    familles: Sequence[str] = FAMILLES_DE_FILLS,
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
        "actions": {},
    }
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
                # aussi bien pour une ouverture que pour un renforcement. Elle se CALCULE sur
                # `start_position`, la position du leader AVANT ce fill : non nulle, le fill
                # renforce une position existante, donc c'est un ADD.
                #
                # Sans cette distinction, tous les metaordres sortaient en OPEN -- 514 544 sur
                # six tranches, zero ADD -- et l'alignement, qui compte les ADD evaluables,
                # rendait `NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS` alors que 99,4 %
                # des signaux avaient bien un carnet a portee. Le refus accusait les carnets ; la
                # cause etait une action manquante.
                try:
                    position_avant = float(ligne.get("start_position") or 0.0)
                except (TypeError, ValueError):
                    position_avant = 0.0
                if position_avant != 0.0:
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
            entrees.append(entree)
            audit["actions"][action] = audit["actions"].get(action, 0) + 1
            rendus += 1
        audit["familles"][famille] = {"shards": len(shards), "lus": lus, "rendus": rendus}
        audit["lignes_lues"] += lus
        audit["entrees_rendues"] += rendus
    entrees.sort(key=lambda e: int(e["ts_ms"]))
    return entrees, audit
