"""BACKFILL DES BOUGIES SUR LES COINS DES LEADERS — 5 min (17 jours) ET 1 h (208 jours).

POURQUOI
--------
Toute étude lente du labo (réplication d'inventaire, étude d'événements, persistance) a besoin d'un
prix historique pour chaque coin tradé par les leaders. ``candleSnapshot`` ne garde que les 5 000
dernières bougies d'un intervalle : en 5 min cela fait 17 jours, en 1 h **208 jours**. Ne tirer que
du 5 min limitait donc le labo à 17 jours d'histoire alors que douze fois plus était à un appel.

CE QUE FAIT CE COLLECTEUR
-------------------------
* Coins : ceux des fills de backfill, plus les listes de coins des leaders (dex HIP-3 compris).
  L'identité NATIVE est conservée (``kPEPE``, ``xyz:XYZ100``) et vérifiée auprès de l'univers
  officiel : l'ancienne mise en majuscules demandait ``KPEPE`` ou ``XYZ:XYZ100``, que l'API refuse.
* Incrémental : un état par (intervalle, coin) ; seules les bougies nouvelles sont demandées puis
  AJOUTÉES au ruban. Le premier passage rattrape toute la profondeur disponible.
* Bougies CLOSES seulement : une bougie en cours n'a pas encore de clôture, l'écrire serait publier
  un prix qui changera.
* Cadence : chaque réponse coûte ``20 + bougies/60`` unités du budget de l'API ; le collecteur dort
  en proportion et s'arrête sur un refus de débit plutôt que d'insister. Passage borné en durée :
  le suivant reprend où celui-ci s'est arrêté.

FUNDING. Le même passage tient à jour l'historique HORAIRE du funding de chaque coin
(``fundingHistory``, même profondeur de 208 jours) : sans lui, le coût de portage d'une position
tenue plusieurs heures reste inconnu — la simulation de réplication ne le connaissait que 10 % du
temps. Un taux publié à l'heure H sert à compter ce qu'une position a payé ; il n'est jamais lu
comme une information disponible avant H.

Ces séries sont récupérées APRÈS COUP : elles servent à mesurer et à rejouer, jamais à prétendre
qu'un prix était observé en direct. Lecture seule (``candleSnapshot``, ``fundingHistory``). 0 ordre, 0 clé.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import candle_backfill as CB  # noqa: E402
from hl_observer.ops import budget_rest as _BUDGET  # noqa: E402  (n° 22 : poids REST réel, sans bloquer)
from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.collection.univers_perps import charger_univers, filtrer_abonnables  # noqa: E402
from hl_observer.instrument_identity import preserve_native_instrument_symbol  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
LISTES_DE_COINS = (Path("runtime") / "data" / "copy_vault_coins_local.json", Path("config") / "copy_vault_coins.json")
# 15/11/2026 — AJOUT DU JOURNALIER, et c'est le plus profond des trois.
# J'avais conclu que les prix s'arretaient a 211 jours apres n'avoir sonde que le pas HORAIRE. Le
# plafond de `candleSnapshot` est de **5 000 BOUGIES**, pas de 211 jours : il depend donc du PAS.
# Sonde du 15/11 sur BTC, une requete par pas :
#     1h -> 5 001 bougies =   208 jours (avril 2026)
#     4h -> 5 001 bougies =   833 jours (aout 2024)
#     1d -> 1 101 bougies = **1 101 jours** (novembre 2023)
# Le journalier remonte donc EXACTEMENT aussi loin que le funding, et la strategie tient 24 h :
# **une bougie journaliere correspond a une detention entiere.** Sans ce pas, les 890 jours de
# funding rattrapes n'auraient jamais eu de prix en face et le rattrapage aurait ete inutile.
# 15/11/2026 — AJOUT DU PAS 4 h : 833 jours, et il comble le trou entre 208 et 1 101.
# Entre l'horaire (208 j) et le journalier (1 101 j) il manquait un pas INTERMEDIAIRE. Or la
# strategie entre et sort a une HEURE precise : avec le seul pas journalier, un horizon de 96 h se
# mesure sur 4 points, et l'heure d'entree disparait. Le pas 4 h donne 833 jours a 6 points par
# jour — assez fin pour placer une entree, assez profond pour quadrupler l'echantillon.
INTERVALLES_MS = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
SORTIES = {"5m": Path("runtime") / "history" / "candles_5m.jsonl",
           "1h": Path("runtime") / "history" / "candles_1h.jsonl",
           "4h": Path("runtime") / "history" / "candles_4h.jsonl",
           "1d": Path("runtime") / "history" / "candles_1d.jsonl"}
SORTIE = SORTIES["5m"]
SORTIE_FUNDING = Path("runtime") / "history" / "funding_1h.jsonl"
SERIE_FUNDING = "funding"
#: Front ARRIERE du funding : l'horodatage le plus ANCIEN detenu par coin.
#:
#: 15/11/2026 — SANS CE SECOND FRONT, LA PROFONDEUR ETAIT DEFINITIVEMENT GELEE A 211 JOURS.
#: La passe ne connaissait QUE `SERIE_FUNDING`, c'est-a-dire l'horodatage le plus RECENT, et ne
#: savait qu'avancer : `a = max(now - PROFONDEUR, dernier + 1)`. Pour un coin deja tenu a jour sous
#: l'ancien plafond de 208 jours, `dernier` vaut donc ~maintenant, `a` vaut ~maintenant, et le coin
#: est declare « a jour »... a 211 jours de profondeur. **Il ne pouvait PLUS JAMAIS etre
#: approfondi.** Mesure du 15/11 qui l'a revele : 118 coins avec du funding, profondeur mediane
#: **211 jours**, et seulement **3 coins a 1 100 jours** — exactement les trois partis de zero.
#: Monter `PROFONDEUR_FUNDING_JOURS` de 208 a 1 100 n'avait donc servi qu'aux coins neufs.
#: Un historique se rattrape par DEUX bouts : on prolonge vers maintenant, et on CREUSE vers le
#: passe. Le second front est celui qui manquait.
SERIE_FUNDING_ANCIEN = "funding_ancien"
PAGE_FUNDING = 500                # fundingHistory rend au plus 500 points par réponse
#: Largeur temporelle d'une page de funding : 500 points horaires = 20,8 jours par requete.
PAGE_FUNDING_MS = PAGE_FUNDING * 3_600_000
ETAT = Path("runtime") / "data" / "backfill_candles_etat.json"
SCHEMA_ETAT = "hypersmart.backfill_candles_etat.v1"
CAP_CANDLES = 5000                # candleSnapshot ne rend que les 5 000 dernières bougies
# 15/11/2026 — LA PROFONDEUR DU FUNDING N'A RIEN A VOIR AVEC CELLE DES BOUGIES.
# Elle etait calee sur `CAP_CANDLES` (5 000 bougies 1 h = 208 jours) « par symetrie ». C'etait une
# BORNE INVENTEE : `candleSnapshot` plafonne a 5 000 points, mais `fundingHistory` est pagine par
# 500 et ne plafonne pas du tout a la meme profondeur.
# SONDE DU 15/11 sur BTC (une requete par palier) : l'endpoint rend 500 points a 211, 365, 550,
# 730 ET **1 095 jours** en arriere, et plus rien a 1 460. La profondeur reelle est donc d'environ
# **TROIS ANS**, et nous n'en collections que 211 jours.
# POURQUOI CELA CHANGE TOUT : le nombre d'observations INDEPENDANTES vaut
# `historique / duree_de_detention`. A 211 jours et 96 h de detention, cela faisait **26** — trop
# peu pour distinguer une strategie d'une serie chanceuse, et c'est la vraie raison pour laquelle
# le labo ne trouvait rien de solide. Le `t` croit en racine de `n` : x5,7 d'historique -> x2,4 de
# `t`, **si** l'effet tient sur les regimes plus anciens, ce que seule la mesure dira.
# On prend 1 100 jours : juste sous la limite sondee, pour ne pas depenser des requetes dans le
# vide a chaque passage.
PROFONDEUR_FUNDING_JOURS = 1100
PROFONDEUR_FUNDING_MS = PROFONDEUR_FUNDING_JOURS * 86_400_000
BUDGET_POIDS_PAR_MINUTE = CF.BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE   # part d'un rattrapage : les collecteurs en direct d'abord
ATTENTE_REFUS_S = 30.0
#: Refus 429 CONSECUTIFS tolerés avant d'abandonner la passe. A chaque refus l'AIMD divise le
#: debit par deux : 5 refus ramenent 600 u/min au plancher de 100 u/min, c'est-a-dire au debit
#: prudent d'origine. Abandonner avant, c'est perdre le budget restant pour rien.
REFUS_AVANT_ABANDON = 5


def coins_et_fenetre(root: Path) -> tuple[list[str], int, int]:
    """(coins tradés par les vaults, t0_ms, t1_ms) depuis les fills backfillés — identité native."""
    coins: dict[str, None] = {}
    tmin, tmax = 9 << 60, 0
    try:
        with (root / FILLS).open(encoding="utf-8", errors="ignore") as lignes:
            for ligne in lignes:
                try:
                    d = json.loads(ligne)
                except ValueError:
                    continue
                c = preserve_native_instrument_symbol(d.get("coin"))
                t = int(d.get("ts_ms") or 0)
                if c:
                    coins.setdefault(c, None)
                if t:
                    tmin, tmax = min(tmin, t), max(tmax, t)
    except OSError:
        return [], 0, 0
    return list(coins), (tmin if tmax else 0), tmax


MANIFESTES_COFFRE = Path("runtime") / "coffre_certifie" / "local" / "manifests"
#: Nom du ruban d origine -> serie de cette passe. Le manifeste du coffre ne porte
#: PAS l intervalle des bougies, mais le chemin SOURCE le porte (candles_5m.jsonl...).
#: Identite stable du flux telle que le certificateur l inscrit dans chaque entree.
_TAG_VERS_SERIE = {
    "REST_BACKFILL_5M": "5m",
    "REST_BACKFILL_1H": "1h",
    "REST_BACKFILL_4H": "4h",
    "REST_BACKFILL_1D": "1d",
    "REST_FUNDING_HISTORY": SERIE_FUNDING,
}
_SOURCE_VERS_SERIE = {
    "candles_5m.jsonl": "5m",
    "candles_1h.jsonl": "1h",
    "candles_4h.jsonl": "4h",
    "candles_1d.jsonl": "1d",
    "funding_1h.jsonl": SERIE_FUNDING,
}


def coins_du_coffre(root: Path) -> dict[str, set[str]]:
    """Coins dont le COFFRE atteste deja un historique, par serie.

    POURQUOI LIRE LES MANIFESTES ET PAS LES SHARDS. Chaque entree de manifeste porte
    sa famille, son ruban source, ses bornes ts_min_ms/ts_max_ms et le DICTIONNAIRE
    DES COINS presents. Lire ~350 petits JSON coute quelques dizaines de ms, la ou
    rouvrir les shards demanderait de relire des centaines de millions de lignes.

    CE QUE CETTE FONCTION NE FAIT PAS. Elle ne rend AUCUNE borne de temps. Les bornes
    du manifeste valent pour le shard ENTIER, donc pour tous ses coins a la fois :
    s en servir pour declarer un coin "a jour" pourrait sauter un vrai trou. Or
    retelecharger est idempotent (le scellage deduplique) alors qu un trou saute ne
    se voit jamais. Le coffre peut donc ELARGIR l univers suivi, jamais l abreger.
    """
    par_serie: dict[str, set[str]] = {}
    try:
        manifestes = sorted((root / MANIFESTES_COFFRE).iterdir())
    except OSError:
        return par_serie
    for manifeste in manifestes:
        if not manifeste.name.endswith(".json"):
            continue
        try:
            lot = json.loads(manifeste.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue   # un manifeste illisible ne doit pas casser la passe
        for entree in (lot.get("fichiers") or ()) if isinstance(lot, dict) else ():
            if not isinstance(entree, dict):
                continue
            # Le TAG est l identite STABLE du flux (REST_BACKFILL_1H...) ; le chemin
            # source ne sert que de repli si un ruban change un jour de dossier.
            serie = _TAG_VERS_SERIE.get(str(entree.get("source_tag") or ""))
            if serie is None:
                source = str(entree.get("source") or "").replace("\\", "/")
                serie = _SOURCE_VERS_SERIE.get(source.rsplit("/", 1)[-1])
            coins = entree.get("coins")
            if serie is None or not isinstance(coins, dict):
                continue
            cible = par_serie.setdefault(serie, set())
            for coin in coins:
                nom = preserve_native_instrument_symbol(coin)
                if nom:
                    cible.add(nom)
    return par_serie


def coins_deja_commences(root: Path) -> list[str]:
    """Coins dont on tient DEJA un historique, lus de l'etat du backfill.

    15/11/2026 — L'UNIVERS RETRECISSAIT A CHAQUE SESSION, ET PERSONNE NE LE VOYAIT.
    `coins_et_fenetre` lit `runtime/data/vault_fills.jsonl`, un ruban que le lanceur ARCHIVE a
    chaque demarrage de session (« runtime/data repart a zero »). Apres l'archivage du 15/11 a
    21 h 37, l'univers suivi est tombe de **261 a 216 coins** : 45 coins dont on detenait des
    centaines de jours d'histoire cessaient d'etre tenus a jour, en silence.

    Or une serie qu'on arrete de prolonger ne vaut plus rien pour une strategie transversale : son
    histoire devient un bloc qui s'arrete, et le livre perd sa largeur. Un coin DONT ON A DEJA
    COMMENCE l'historique reste donc suivi — `filtrer_abonnables` ecartera de toute facon celui
    que l'univers officiel ne connait plus (retrait de cotation).
    """
    series = (SERIE_FUNDING, SERIE_FUNDING_ANCIEN, *SORTIES)
    try:
        brut = json.loads((root / ETAT).read_text(encoding="utf-8"))
        etat = brut.get("intervalles") if brut.get("_schema") == SCHEMA_ETAT else None
    except (OSError, ValueError, AttributeError):
        etat = None
    if not isinstance(etat, dict):
        etat = {}   # pas d etat lisible : le coffre reste consulte ci-dessous
    vus: dict[str, None] = {}
    for serie in series:
        for coin in (etat.get(serie) or {}):
            nom = preserve_native_instrument_symbol(coin)
            if nom:
                vus.setdefault(nom, None)
    # RECOUPEMENT AVEC LE COFFRE (19/11/2026). L etat ci-dessus vit dans
    # runtime/data, que le lanceur ARCHIVE a chaque demarrage de session : il etait
    # donc un point unique de defaillance. S il disparait, cette passe croyait ne
    # rien detenir et retelechargeait tout. Le coffre certifie, lui, est le magasin
    # DURABLE -- et le seul que lise le labo. On en tire les coins deja attestes.
    for _coins in coins_du_coffre(root).values():
        for _nom in _coins:
            vus.setdefault(_nom, None)
    return list(vus)


def coins_suivis(root: Path) -> list[str]:
    """Coins des fills, des listes de leaders, ET ceux dont un historique est deja commence."""
    coins: dict[str, None] = dict.fromkeys(coins_et_fenetre(root)[0])
    for liste in LISTES_DE_COINS:
        try:
            contenu = json.loads((root / liste).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for coin in (contenu.get("coins") if isinstance(contenu, dict) else contenu) or ():
            nom = preserve_native_instrument_symbol(coin)
            if nom:
                coins.setdefault(nom, None)
    for nom in coins_deja_commences(root):
        coins.setdefault(nom, None)
    return list(coins)


def _post_candles(coin: str, intervalle: str, a: int, b: int, *, timeout_s: float = 15.0) -> Any:
    corps = json.dumps({"type": "candleSnapshot",
                        "req": {"coin": coin, "interval": intervalle, "startTime": int(a), "endTime": int(b)}}).encode()
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        rendu = json.loads(rep.read().decode("utf-8"))
    _BUDGET.compter("candleSnapshot", len(rendu) if isinstance(rendu, list) else 0)
    return rendu


def poids_requete(n_bougies: int) -> float:
    """Coût d'une réponse dans le budget de débit de l'API (base 20, plus 1 par 60 bougies)."""
    return 20.0 + max(0, int(n_bougies)) / 60.0


def tirer(coin: str, intervalle: str, a: int, b: int, *, poster=_post_candles, now_ms: int | None = None,
          ) -> tuple[list[dict[str, Any]], bool, str | None]:
    """``(bougies closes, tronqué ?, erreur)``. ``erreur`` : ``None``, ``"LIMITE_DEBIT"`` ou ``"ECHEC"``."""
    try:
        payload = poster(coin, intervalle, a, b)
    except urllib.error.HTTPError as exc:
        return [], False, "LIMITE_DEBIT" if exc.code == 429 else "ECHEC"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return [], False, "ECHEC"
    bougies = CB.dedupliquer(CB.parser_bougies(coin, payload))
    tronque = len(bougies) >= CAP_CANDLES
    pas = INTERVALLES_MS.get(intervalle)
    lignes = []
    for bougie in bougies:
        if now_ms is not None and pas is not None and bougie.t_ms + pas > now_ms:
            continue                                   # bougie encore en cours : pas de clôture à publier
        # le coin écrit est celui DEMANDÉ (identité native), jamais une variante de casse
        lignes.append({**bougie.as_dict(), "coin": coin, "interval": intervalle,
                       "source": f"REST_BACKFILL_{intervalle.upper()}"})
    return lignes, tronque, None


def backfill_un_coin(coin: str, a: int, b: int, *, intervalle: str = "5m", limiteur: CF.Limiteur,
                     poster=_post_candles, now_ms: int | None = None, dormir: Callable[[float], None] = time.sleep,
                     ) -> tuple[list[dict], bool]:
    """(bougies propres du coin, tronque?). Tronque si une réponse atteint le cap 5000."""
    CF.ceder_au_direct(dormir)                         # un collecteur en direct vient d'être refusé : on attend
    CF.prendre_la_pause(limiteur, dormir)              # la cadence est RESPECTÉE, pas seulement calculée
    lignes, tronque, _erreur = tirer(coin, intervalle, a, b, poster=poster, now_ms=now_ms)
    return lignes, tronque


def _post_funding(coin: str, a: int, b: int, *, timeout_s: float = 15.0) -> Any:
    corps = json.dumps({"type": "fundingHistory", "coin": coin, "startTime": int(a), "endTime": int(b)}).encode()
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        rendu = json.loads(rep.read().decode("utf-8"))
    _BUDGET.compter("fundingHistory", len(rendu) if isinstance(rendu, list) else 0)
    return rendu


def tirer_funding(coin: str, a: int, b: int, *, poster=_post_funding) -> tuple[list[dict[str, Any]], bool, str | None]:
    """``(points de funding, page pleine ?, erreur)``. Un point illisible est écarté, jamais deviné."""
    try:
        payload = poster(coin, a, b)
    except urllib.error.HTTPError as exc:
        return [], False, "LIMITE_DEBIT" if exc.code == 429 else "ECHEC"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return [], False, "ECHEC"
    if not isinstance(payload, list):
        return [], False, "ECHEC"
    points: dict[int, dict[str, Any]] = {}
    for brut in payload:
        try:
            instant, taux = int(brut["time"]), float(brut["fundingRate"])
        except (KeyError, TypeError, ValueError):
            continue
        if instant <= 0 or not (taux == taux and abs(taux) < 1.0):     # NaN ou taux horaire absurde : écarté
            continue
        try:
            prime = float(brut.get("premium"))
        except (TypeError, ValueError):
            prime = None
        # ``funding`` = taux HORAIRE, même nom que dans le contexte d'actif observé : un seul lecteur côté labo
        points[instant] = {"coin": coin, "ts_ms": instant, "funding": taux, "premium": prime, "interval": "1h",
                           "source": "REST_FUNDING_HISTORY", "real_execution": False}
    return [points[t] for t in sorted(points)], len(payload) >= PAGE_FUNDING, None


def _ecrire_funding(chemin: Path, lignes: list[dict[str, Any]], now_ms: int) -> None:
    with chemin.open("a", encoding="utf-8") as ruban:
        for x in lignes:
            ruban.write(json.dumps({**x, "recv_ms": now_ms}, ensure_ascii=False) + "\n")


def page_arriere_funding(coin: str, *, ancien: int, plancher: int, poster=_post_funding,
                         ) -> tuple[list[dict[str, Any]], str | None, bool, int]:
    """Une page VERS LE PASSE : ``(lignes, erreur, origine_atteinte, requetes)``.

    `fundingHistory` rend les points A PARTIR de `startTime`, au plus 500. Pour creuser, on demande
    donc exactement la fenetre `[ancien - une page, ancien)` : une requete = une page de 20,8 jours
    gagnee, jamais plus, jamais moins.

    **Une fenetre vide ne veut pas dire « plus rien »** : elle peut precéder la cotation du coin,
    ou cacher un trou. On ne devine pas — on REDEMANDE depuis le plancher. Toujours vide : le coin
    n'existait pas avant, `origine_atteinte` est vrai et on ne le redemandera plus. Non vide : le
    trou etait reel, on ecrit ce qui existe et on le signale plutot que de le combler en silence.

    `requetes` est rendu parce que cette fonction peut en faire DEUX : les compter pour une seule
    ferait mentir le budget de debit, qui est precisement ce qui protege l'IP.
    """
    debut = max(int(plancher), int(ancien) - PAGE_FUNDING_MS)
    if debut >= int(ancien):
        return [], None, True, 0                   # deja au plancher : rien a creuser, rien a payer
    lignes, _pleine, erreur = tirer_funding(coin, debut, int(ancien) - 1, poster=poster)
    if erreur:
        return [], erreur, False, 1
    if lignes:
        return lignes, None, False, 1
    lignes, _pleine, erreur = tirer_funding(coin, int(plancher), int(ancien) - 1, poster=poster)
    if erreur:
        return [], erreur, False, 2
    return lignes, None, not lignes, 2


def avec_recul(resultat: Any, appel: Callable[[], Any], *, erreur_de: Callable[[Any], Any],
               cadence: Any, dormir: Callable[[float], None],
               apres_chaque_essai: Callable[[Any], None] | None = None) -> tuple[Any, int]:
    """Sur un refus de debit, RECULE puis reessaie ``appel()`` avant de renoncer.

    ``resultat`` est le resultat DEJA obtenu par le premier essai : le helper ne rejoue jamais une
    requete sans avoir d'abord attendu. Rejouer immediatement apres un 429 serait exactement le
    comportement qui fait bannir.

    17/11/2026 — LE CORRECTIF DU 16/11 N'AVAIT ETE POSE QUE SUR UN SITE SUR TROIS. Le recul
    geometrique (« deux refus ne doivent pas tuer la passe ») protegeait le front AVANT du funding.
    Le front de CREUSAGE s'arretait encore au PREMIER refus, et la passe des bougies au deuxieme.

    Mesure du passage de la nuit du 16 au 17/11 : `funding-profond` s'est arrete sur
    ``LIMITE_DEBIT`` apres **37 minutes**, a la ronde 5, alors qu'il restait **334 minutes** de
    budget et **9 872 jours-coins** a creuser. Un seul refus, a 600 u/min, a suffi — sans que le
    debit ait eu l'occasion de reculer une seule fois.

    Une regle ecrite a trois endroits finit toujours par diverger : elle vit donc ICI, et les trois
    sites l'appellent. Chaque refus divise le debit (``cadence.refus()``) et allonge l'attente ;
    on ne renonce qu'apres ``REFUS_AVANT_ABANDON`` refus CONSECUTIFS.

    Rend ``(dernier_resultat, refus_consecutifs)``. ``apres_chaque_essai`` recoit chaque resultat
    de NOUVEL essai, pour les compteurs qui doivent suivre toutes les requetes reellement faites.
    """
    refus = 0
    while erreur_de(resultat) == "LIMITE_DEBIT" and refus < REFUS_AVANT_ABANDON:
        refus += 1
        cadence.refus()
        dormir(ATTENTE_REFUS_S * refus)
        resultat = appel()
        if apres_chaque_essai is not None:
            apres_chaque_essai(resultat)
    return resultat, refus


def passe_funding(root: Path, *, now_ms: int | None = None, poster=_post_funding,
                  dormir: Callable[[float], None] = time.sleep, budget_s: float = 1500.0,
                  max_coins: int | None = None, univers: set[str] | None | str = "auto",
                  horloge: Callable[[], float] = time.monotonic, cadence=None,
                  profondeur_ms: int | None = None) -> dict[str, Any]:
    """Un passage borné : prolonge l'historique horaire du funding **et le creuse**, en RONDES.

    DEUX FRONTS. On prolonge de `plus_recent` vers maintenant (bon marche : une page suffit presque
    toujours) PUIS on creuse de `plus_ancien` vers le plancher. Sans ce second front, un coin deja
    tenu a jour restait prisonnier de l'ancien plafond de 208 jours pour toujours.

    EN RONDES, ET C'EST LA QUE SE JOUE L'UTILITE DE LA PASSE. L'ancienne boucle vidait un coin
    entierement avant de passer au suivant : mesure du 15/11, **41 minutes pour 2 coins sur 261**.
    Or ce que la strategie peut mesurer est l'INTERSECTION des historiques de tout le livre — trois
    coins parfaits et 258 coins pauvres donnent donc une fenetre mesurable INCHANGEE : 41 minutes
    pour rien. Une page par coin et par ronde fait au contraire monter le plancher commun des la
    premiere ronde, et un arret a n'importe quel moment laisse une profondeur UNIFORME.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    profondeur = int(profondeur_ms if profondeur_ms is not None else PROFONDEUR_FUNDING_MS)
    if univers == "auto":
        univers = charger_univers(root)
    coins, _inconnus = filtrer_abonnables(coins_suivis(root), univers)
    etat = charger_etat(root, (SERIE_FUNDING, SERIE_FUNDING_ANCIEN))
    derniers, anciens = etat[SERIE_FUNDING], etat[SERIE_FUNDING_ANCIEN]
    if cadence is None:
        from hl_observer.collection.debit_adaptatif import CadenceAimd
        cadence = CadenceAimd()
    debut = horloge()
    compte: dict[str, Any] = {"demandes": 0, "points": 0, "a_jour": 0, "echecs": [], "arret": None,
                              "creuses": 0, "origines": 0, "trous": [], "rondes": 0}
    chemin = root / SORTIE_FUNDING
    chemin.parent.mkdir(parents=True, exist_ok=True)
    plancher = now_ms - profondeur
    # 15/11/2026 — LA PASSE ETAIT MUETTE. Verifie : **zero octet de sortie en une heure**, car le
    # seul `print` arrivait APRES l'epuisement du budget (jusqu'a 8 h plus tard). Un rattrapage qui
    # ne dit rien pendant huit heures est indistinguable d'un rattrapage mort — et on ne peut pas
    # decider d'attendre ou de relancer sans le savoir.
    ordre = sorted(coins, key=lambda c: derniers.get(c, 0))[:max_coins]
    total_coins = len(ordre)
    debut_heure = time.time()

    def _hors_budget() -> bool:
        if budget_s and horloge() - debut > budget_s:
            compte["arret"] = "BUDGET_DE_TEMPS"
            return True
        return False

    def _profondeurs() -> list[float]:
        return sorted(((now_ms - int(anciens[c])) / 86_400_000) for c in ordre if anciens.get(c))

    print(f"[funding] rattrapage de {total_coins} coins | cible {profondeur // 86_400_000} jours "
          f"| budget {budget_s:.0f} s | 2 fronts (prolonger + creuser), en rondes", flush=True)

    # ─────────────── FRONT AVANT : prolonger jusqu'a maintenant ───────────────
    for rang, coin in enumerate(ordre, 1):
        if compte["arret"]:
            break
        points_avant = compte["points"]
        while not compte["arret"]:
            if _hors_budget():
                break
            dernier = derniers.get(coin, 0)
            a = max(plancher, dernier + 1)
            if a + 3_600_000 > now_ms:
                compte["a_jour"] += 1
                break
            CF.ceder_au_direct(dormir)
            lignes, pleine, erreur = tirer_funding(coin, a, now_ms, poster=poster)
            # 16/11/2026 — DEUX REFUS NE DOIVENT PAS TUER LA PASSE.
            #
            # Mesure : le passage de 18:14 s'est arrete sur LIMITE_DEBIT apres 40 min, laissant
            # 24 494 s de budget inutilisees. L'AIMD existe pour RECULER : chaque refus divise le
            # debit par deux (600 -> 300 -> 150 -> 100, le plancher). S'arreter au deuxieme refus,
            # c'est abandonner avant meme d'avoir atteint le debit prudent d'origine.
            #
            # On recule donc geometriquement, en attendant de plus en plus longtemps, et on ne
            # renonce qu'apres REFUS_AVANT_ABANDON refus CONSECUTIFS. Un refus suivi d'un succes
            # remet le compteur a zero : seule une venue durablement fermee arrete la passe.
            refus_consecutifs = 0
            if erreur == "LIMITE_DEBIT":
                (lignes, pleine, erreur), refus_consecutifs = avec_recul(
                    (lignes, pleine, erreur),
                    lambda: tirer_funding(coin, a, now_ms, poster=poster),  # noqa: B023
                    erreur_de=lambda r: r[2], cadence=cadence, dormir=dormir)
            if erreur == "LIMITE_DEBIT":
                compte["arret"] = "LIMITE_DEBIT"
                compte["refus_consecutifs"] = refus_consecutifs
                break
            compte["demandes"] += 1
            if erreur:
                compte["echecs"].append(coin)
                dormir(cadence.pause(20.0))
                break
            cadence.succes()
            dormir(cadence.pause(20.0 + len(lignes) / 20.0))
            nouvelles = [x for x in lignes if dernier < x["ts_ms"] <= now_ms]
            if nouvelles:
                _ecrire_funding(chemin, nouvelles, now_ms)
                derniers[coin] = nouvelles[-1]["ts_ms"]
                # Un coin jamais vu n'a pas de front arriere : le plus ancien point qu'on vient
                # d'ecrire le fonde. Sans cela, le creusage n'aurait aucun point de depart.
                if not anciens.get(coin):
                    anciens[coin] = nouvelles[0]["ts_ms"]
                compte["points"] += len(nouvelles)
                sauver_etat(root, etat)
            if not pleine or not nouvelles:
                break                                   # dernière page de ce coin
        gagnes = compte["points"] - points_avant
        if gagnes:
            ecoule = time.time() - debut_heure
            print(f"[funding] prolonge {rang:>4}/{total_coins} {coin:<12} +{gagnes:>6} points | "
                  f"{compte['points']:>8} ajoutes ce passage | {ecoule / 60:.0f} min", flush=True)

    # ─────────────── FRONT ARRIERE : creuser, une page par coin et par ronde ───────────────
    # Un coin est a creuser si son point le plus ANCIEN est encore au-dessus du plancher.
    restants = [c for c in ordre if int(anciens.get(c) or 0) > plancher]
    while restants and not compte["arret"]:
        compte["rondes"] += 1
        profs = _profondeurs()
        mediane = profs[len(profs) // 2] if profs else 0.0
        print(f"[funding] --- ronde {compte['rondes']} | {len(restants)} coins a creuser | "
              f"profondeur mediane {mediane:.0f} j | {cadence.resume()}", flush=True)
        encore: list[str] = []
        for rang, coin in enumerate(restants, 1):
            if compte["arret"]:
                encore.append(coin)                     # pas servi : il reste a creuser
                continue
            if _hors_budget():
                encore.append(coin)
                continue
            ancien = int(anciens.get(coin) or 0)
            if not ancien or ancien <= plancher:
                continue
            CF.ceder_au_direct(dormir)
            lignes, erreur, origine, faites = page_arriere_funding(
                coin, ancien=ancien, plancher=plancher, poster=poster)
            compte["demandes"] += faites
            if erreur == "LIMITE_DEBIT":
                # Meme recul que le front avant : UN refus ne tue plus la passe (voir avec_recul).
                def _compter_les_demandes(resultat: Any) -> None:
                    compte["demandes"] += resultat[3]

                (lignes, erreur, origine, faites), refus_creusage = avec_recul(
                    (lignes, erreur, origine, faites),
                    lambda: page_arriere_funding(                           # noqa: B023
                        coin, ancien=ancien, plancher=plancher, poster=poster),
                    erreur_de=lambda r: r[1], cadence=cadence, dormir=dormir,
                    apres_chaque_essai=_compter_les_demandes)
                if erreur == "LIMITE_DEBIT":
                    compte["arret"] = "LIMITE_DEBIT"
                    compte["refus_consecutifs"] = refus_creusage
                    encore.append(coin)
                    continue
            if erreur:
                compte["echecs"].append(coin)
                encore.append(coin)
                dormir(cadence.pause(20.0))
                continue
            cadence.succes()
            dormir(cadence.pause(20.0 + len(lignes) / 20.0))
            if origine:
                # Le coin n'a rien de plus ancien : on marque le plancher pour ne plus le demander.
                anciens[coin] = plancher
                compte["origines"] += 1
                sauver_etat(root, etat)
                continue
            nouvelles = [x for x in lignes if plancher <= x["ts_ms"] < ancien]
            if not nouvelles:
                anciens[coin] = plancher               # rien d'exploitable : on arrete ce coin
                sauver_etat(root, etat)
                continue
            _ecrire_funding(chemin, nouvelles, now_ms)
            plus_vieux = min(x["ts_ms"] for x in nouvelles)
            plus_jeune = max(x["ts_ms"] for x in nouvelles)
            if plus_jeune < ancien - PAGE_FUNDING_MS:
                # On a saute par-dessus un intervalle vide. On l'ECRIT au bilan : un trou comble en
                # silence serait une continuite inventee.
                compte["trous"].append({"coin": coin, "de_ms": plus_jeune, "a_ms": ancien})
            anciens[coin] = plus_vieux
            compte["points"] += len(nouvelles)
            compte["creuses"] += 1
            sauver_etat(root, etat)
            if plus_vieux > plancher:
                encore.append(coin)                     # il reste de la profondeur a prendre
            jours = (now_ms - plus_vieux) / 86_400_000
            ecoule = time.time() - debut_heure
            reste = (budget_s - ecoule) if budget_s else 0.0
            print(f"[funding] R{compte['rondes']} {rang:>4}/{len(restants)} {coin:<12} "
                  f"+{len(nouvelles):>5} points | remonte a {jours:>6.0f} j | "
                  f"{compte['points']:>8} ajoutes ce passage | {ecoule / 60:.0f} min ecoulees, "
                  f"{max(0, reste) / 60:.0f} restantes", flush=True)
        restants = encore

    sauver_etat(root, etat)
    profs = _profondeurs()
    if profs:
        print(f"[funding] profondeur apres cette passe : min {profs[0]:.0f} j | "
              f"mediane {profs[len(profs) // 2]:.0f} j | max {profs[-1]:.0f} j "
              f"({len(profs)}/{total_coins} coins servis)", flush=True)
    if compte["arret"]:
        print(f"[funding] ARRET : {compte['arret']} -> la passe suivante reprend ici "
              "(l'etat est sauve apres chaque page)", flush=True)
    return compte


def _etat_depuis_ruban(chemin: Path, champ: str = "t_ms", *, sens: str = "max") -> dict[str, int]:
    """Bougie/point EXTREME par coin, relu du ruban (état perdu ou premier passage après migration).

    `sens="max"` rend le plus RECENT (front avant), `sens="min"` le plus ANCIEN (front arriere).
    Le front arriere n'a aucune autre source : l'etat historique ne stockait que le plus recent, et
    c'est precisement pourquoi la profondeur ne pouvait pas etre rattrapee.
    """
    extremes: dict[str, int] = {}
    vers_le_bas = str(sens) == "min"
    try:
        with chemin.open(encoding="utf-8", errors="ignore") as lignes:
            for ligne in lignes:
                try:
                    d = json.loads(ligne)
                    coin, t = str(d["coin"]), int(d[champ])
                except (ValueError, KeyError, TypeError):
                    continue
                vu = extremes.get(coin)
                if vu is None or (t < vu if vers_le_bas else t > vu):
                    extremes[coin] = t
    except OSError:
        pass
    return extremes


def charger_etat(root: Path, intervalles: tuple[str, ...]) -> dict[str, dict[str, int]]:
    try:
        brut = json.loads((root / ETAT).read_text(encoding="utf-8"))
        etat = brut.get("intervalles") if brut.get("_schema") == SCHEMA_ETAT else None
    except (OSError, ValueError, AttributeError):
        etat = None
    etat = etat if isinstance(etat, dict) else {}
    for intervalle in intervalles:
        if isinstance(etat.get(intervalle), dict):
            continue
        if intervalle == SERIE_FUNDING:
            etat[intervalle] = _etat_depuis_ruban(root / SORTIE_FUNDING, "ts_ms")
        elif intervalle == SERIE_FUNDING_ANCIEN:
            # Premiere fois que le front arriere existe : il se reconstruit du ruban, qui porte
            # deja 118 coins. Sans cette relecture, creuser repartirait de zero et redemanderait
            # a la venue des centaines de milliers de points deja detenus.
            etat[intervalle] = _etat_depuis_ruban(root / SORTIE_FUNDING, "ts_ms", sens="min")
        else:
            etat[intervalle] = _etat_depuis_ruban(root / SORTIES[intervalle])
    return etat


#: 16/11/2026 — WINDOWS REFUSE `os.replace` SI LA CIBLE EST OUVERTE, MEME EN LECTURE SEULE (il
#: n'y a pas de FILE_SHARE_DELETE sur un `open()` Python). Mesure remontee par le rapport
#: collecteurs : `PermissionError: [WinError 5] Acces refuse: backfill_candles_etat.json.85588.tmp
#: -> backfill_candles_etat.json`, dans le journal de la passe de campagne — pendant qu'un
#: rattrapage lisait le meme etat au debut de SON `sauver_etat`. L'exception TUAIT la passe.
#: L'autre lecteur ne tient le fichier que quelques millisecondes : on attend, on ne meurt pas.
ESSAIS_REMPLACEMENT = 6
ATTENTE_REMPLACEMENT_S = 0.25


def remplacer_avec_patience(tmp: Path, cible: Path, *, dormir: Callable[[float], None] = time.sleep,
                            ) -> bool:
    """`os.replace` avec quelques tentatives. Rend ``False`` plutot que de tuer la passe.

    Perdre un ETAT n'est pas perdre des DONNEES : les lignes sont deja sur le ruban, completes, et
    la page suivante resauvera l'etat. Mourir ici fait perdre tout le reste du budget de la passe —
    c'est-a-dire des heures de requetes.
    """
    for essai in range(1, ESSAIS_REMPLACEMENT + 1):
        try:
            os.replace(tmp, cible)
            return True
        except PermissionError:
            if essai >= ESSAIS_REMPLACEMENT:
                print(f"[candles-vaults] etat NON sauve : {cible.name} tenu par un autre processus "
                      f"apres {essai} essais. Les donnees sont sur le ruban ; la page suivante "
                      "resauvera l'etat.", flush=True)
                return False
            dormir(ATTENTE_REMPLACEMENT_S * essai)
        except OSError as erreur:
            print(f"[candles-vaults] etat NON sauve ({type(erreur).__name__}) : les donnees sont "
                  "sur le ruban ; la page suivante resauvera l'etat.", flush=True)
            return False
    return False


def sauver_etat(root: Path, etat: dict[str, dict[str, int]]) -> None:
    chemin = root / ETAT
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # un passage ne charge que ses séries : celles des autres passages sont conservées telles quelles
    try:
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
        complet = dict(ancien["intervalles"]) if ancien.get("_schema") == SCHEMA_ETAT else {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        complet = {}
    complet.update(etat)
    # 15/11/2026 — LE TEMPORAIRE PORTE LE PID. Avec un nom FIXE, deux passes concurrentes (celle
    # de la campagne toutes les 4 h et une passe de rattrapage lancee a la main) ouvrent le MEME
    # fichier : P1 ecrit, P2 le tronque, P1 remplace — et un etat PARTIEL devient l'etat officiel.
    # Le `os.replace` est atomique, mais il ne protege pas de deux ecrivains sur le meme brouillon.
    # C'est precisement ce qui m'a fait renoncer au rattrapage le 14/11 ; avec le PID, les deux
    # passes peuvent tourner ensemble. La derniere a ecrire gagne pour les coins qu'elle a traites,
    # et comme la boucle sert d'abord les coins les plus en retard, aucun coin n'est affame.
    tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({"_schema": SCHEMA_ETAT, "intervalles": complet},
                                  ensure_ascii=False), encoding="utf-8")
        remplacer_avec_patience(tmp, chemin)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)      # un brouillon oublie finirait par polluer le dossier


def passe(root: Path, *, intervalles: tuple[str, ...] = ("1h", "5m"), now_ms: int | None = None,
          poster=_post_candles, dormir: Callable[[float], None] = time.sleep, budget_s: float = 3000.0,
          max_coins: int | None = None, univers: set[str] | None | str = "auto",
          horloge: Callable[[], float] = time.monotonic, cadence=None) -> dict[str, Any]:
    """Un passage borné : rattrape ou prolonge les bougies de chaque coin, par intervalle."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if cadence is None:
        from hl_observer.collection.debit_adaptatif import CadenceAimd
        cadence = CadenceAimd()
    if univers == "auto":
        univers = charger_univers(root)
    coins, inconnus = filtrer_abonnables(coins_suivis(root), univers)
    etat = charger_etat(root, intervalles)
    debut = horloge()
    bilan: dict[str, Any] = {"coins": len(coins), "coins_inconnus_non_demandes": inconnus, "intervalles": {},
                             "arret": None}
    for intervalle in intervalles:
        pas = INTERVALLES_MS[intervalle]
        plancher = now_ms - CAP_CANDLES * pas          # plus ancien que cela : l'API ne le rend plus
        derniers = etat[intervalle]
        # les coins les moins à jour d'abord : un passage interrompu n'affame jamais les mêmes ; à égalité,
        # l'ordre de la liste est gardé (elle est classée par notionnel des leaders : l'important d'abord)
        ordre = sorted(coins, key=lambda c: derniers.get(c, 0))[:max_coins]
        compte = {"demandes": 0, "bougies": 0, "a_jour": 0, "echecs": [], "tronques": []}
        bilan["intervalles"][intervalle] = compte
        chemin = root / SORTIES[intervalle]
        chemin.parent.mkdir(parents=True, exist_ok=True)
        total = len(ordre)
        debut_heure = time.time()
        # 15/11/2026 — CETTE PASSE AUSSI ETAIT MUETTE. Seule celle du funding avait recu son
        # affichage par coin ; celle des bougies ne parlait qu'au bilan final, apres ses 3 000 s.
        # « Pas de cmd muet, je veux voir l'avancement » valait pour les deux.
        print(f"[candles] {intervalle} : {total} coins | profondeur accessible "
              f"{CAP_CANDLES * pas // 86_400_000} jours | budget {budget_s:.0f} s", flush=True)
        for rang, coin in enumerate(ordre, 1):
            if bilan["arret"]:
                break
            if horloge() - debut > budget_s:
                bilan["arret"] = "BUDGET_DE_TEMPS"
                break
            dernier = derniers.get(coin, 0)
            a = max(plancher, dernier + pas) if dernier else plancher
            if a + pas > now_ms:
                compte["a_jour"] += 1
                continue
            CF.ceder_au_direct(dormir)
            lignes, tronque, erreur = tirer(coin, intervalle, a, now_ms, poster=poster, now_ms=now_ms)
            if erreur == "LIMITE_DEBIT":
                # Meme recul que le funding (voir avec_recul) : la passe renoncait au DEUXIEME refus.
                (lignes, tronque, erreur), refus_bougies = avec_recul(
                    (lignes, tronque, erreur),
                    lambda: tirer(coin, intervalle, a, now_ms, poster=poster,   # noqa: B023
                                  now_ms=now_ms),
                    erreur_de=lambda r: r[2], cadence=cadence, dormir=dormir)
                if erreur == "LIMITE_DEBIT":
                    bilan["arret"] = "LIMITE_DEBIT"      # la venue reste fermee : reprise au prochain passage
                    bilan["refus_consecutifs"] = refus_bougies
                    break
            compte["demandes"] += 1
            if erreur:
                compte["echecs"].append(coin)
                # La pause reste PROPORTIONNELLE a ce que la requete a reellement coute : un echec
                # ne rend rien, il ne doit donc pas etre paye au prix d'une reponse pleine.
                dormir(cadence.pause(poids_requete(0)))
                continue
            cadence.succes()
            nouvelles = [x for x in lignes if x["t_ms"] > dernier]
            if nouvelles:
                with chemin.open("a", encoding="utf-8") as ruban:
                    for x in nouvelles:
                        ruban.write(json.dumps({**x, "recv_ms": now_ms}, ensure_ascii=False) + "\n")
                derniers[coin] = max(x["t_ms"] for x in nouvelles)
                compte["bougies"] += len(nouvelles)
                sauver_etat(root, etat)
                # 19/11/2026 -- "0 j" POUR UN LOT DE 7 HEURES : la colonne affichait des JOURS
                # arrondis a l entier, donc tout lot de moins de 12 h se lisait "0 j". L operateur
                # a cru deux fois que le creusement ne partait pas, alors que le rattrapage
                # comblait 6 a 7 heures. On montre desormais l unite qui a du SENS a cette
                # echelle : heures sous la journee, jours au-dela.
                age_ms = now_ms - min(x["t_ms"] for x in nouvelles)
                jours = age_ms / 86_400_000
                portee = ("%6.1f h" % (age_ms / 3_600_000)) if jours < 1 else ("%6.0f j" % jours)
                ecoule = time.time() - debut_heure
                print(f"[candles] {intervalle} {rang:>4}/{total} {coin:<12} "
                      # 17/11/2026 : « remonte a 0 j | 1 au total » se lisait comme le STOCK, alors
                      # que ces chiffres ne comptent que ce que CE passage vient d'ajouter.
                      f"+{len(nouvelles):>5} bougies | ce lot remonte a {portee} | "
                      f"{compte['bougies']:>8} ajoutees ce passage | {ecoule / 60:.0f} min", flush=True)
            if tronque:
                compte["tronques"].append(coin)
            # Le coût d'une réponse dépend du NOMBRE de bougies rendues : une page pleine se paie
            # 103 unités, une réponse d'une bougie 20. Payer tout le monde au tarif maximum
            # ralentirait 5x les coins déjà à jour, qui sont l'immense majorité des passages.
            dormir(cadence.pause(poids_requete(len(lignes))))
        print(f"[candles] {intervalle} termine : {compte['bougies']} bougies, "
              f"{compte['a_jour']}/{total} deja a jour | {cadence.resume()}", flush=True)
    sauver_etat(root, etat)
    return bilan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill des bougies 5 min et 1 h des coins des leaders (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalles", default="1h,5m",
                   help="intervalles à tenir à jour (parmi 5m, 1h, 4h, 1d)")
    p.add_argument("--intervalle", default=None, help="(ancien nom) un seul intervalle")
    p.add_argument("--budget-s", type=float, default=3000.0, help="durée maximale de ce passage")
    p.add_argument("--max-coins", type=int, default=None)
    p.add_argument("--sans-funding", action="store_true", help="ne pas tenir à jour l'historique du funding")
    # 14/11/2026 — POURQUOI CETTE OPTION. La passe bougies consomme ses 3 000 s AVANT que le
    # funding n'obtienne ses 1 500 s, et le tout ne tourne que toutes les 4 h. Resultat mesure :
    # 90 coins ont du funding sur 261 suivis, **171 n'en ont JAMAIS eu**. Or la largeur de la
    # section transversale joue sur les DEUX termes du rapport `brut/repli` qui fixe le resultat :
    # des queues plus extremes (signal plus fort) ET plus de diversification (repli plus bas).
    # Cette option permet de rattraper les 171 manquants sans refaire les bougies, qui sont deja
    # a jour sur 263 coins.
    p.add_argument("--seulement-funding", action="store_true",
                   help="ne faire QUE l'historique du funding (les bougies sont deja a jour)")
    p.add_argument("--budget-funding-s", type=float, default=1500.0)
    p.add_argument("--profondeur-jours", type=float, default=None,
                   help=f"profondeur de funding visee (defaut {PROFONDEUR_FUNDING_JOURS} j, "
                        "limite sondee de l'endpoint ~1 095 j)")
    p.add_argument("--une-fois", action="store_true", default=True)
    a = p.parse_args(argv)
    demandes = tuple(x.strip() for x in (a.intervalle or a.intervalles).split(",") if x.strip())
    inconnus = [x for x in demandes if x not in INTERVALLES_MS]
    if inconnus:
        print(f"[candles-vaults] intervalle(s) non géré(s) : {', '.join(inconnus)}", flush=True)
        return 2
    if a.seulement_funding:
        if a.sans_funding:
            print("[candles-vaults] --seulement-funding et --sans-funding sont contradictoires",
                  flush=True)
            return 2
        funding = passe_funding(Path(a.root), budget_s=a.budget_funding_s, max_coins=a.max_coins,
                                profondeur_ms=(int(a.profondeur_jours * 86_400_000)
                                               if a.profondeur_jours else None))
        echecs = f" ({','.join(funding['echecs'][:8])})" if funding["echecs"] else ""
        print(f"[candles-vaults] funding 1h SEUL : {funding['points']} points ajoutes, "
              f"{funding['demandes']} demandes, {funding['a_jour']} coins a jour, "
              f"{funding.get('creuses', 0)} pages creusees en {funding.get('rondes', 0)} ronde(s), "
              f"{funding.get('origines', 0)} coins au bout de leur histoire, "
              f"{len(funding.get('trous', ()))} trou(s) signale(s), "
              f"{len(funding['echecs'])} echecs{echecs} -> {SORTIE_FUNDING}"
              + (f" | interrompu ({funding['arret']}) : reprise au prochain passage"
                 if funding["arret"] else ""), flush=True)
        return 0
    bilan = passe(Path(a.root), intervalles=demandes, budget_s=a.budget_s, max_coins=a.max_coins)
    if not bilan["coins"]:
        print("[candles-vaults] aucun coin (ni fills, ni liste de coins) - rien a faire", flush=True)
        return 0
    for intervalle, compte in bilan["intervalles"].items():
        echecs = f" ({','.join(compte['echecs'][:8])})" if compte["echecs"] else ""
        print(f"[candles-vaults] {intervalle} : {compte['bougies']} bougies ajoutees, {compte['demandes']} coins "
              f"demandes, {compte['a_jour']} deja a jour, {len(compte['echecs'])} echecs{echecs} "
              f"-> {SORTIES[intervalle]}", flush=True)
    if bilan["coins_inconnus_non_demandes"]:
        print("[candles-vaults] marches inconnus de l'univers officiel, non demandes : "
              + ",".join(bilan["coins_inconnus_non_demandes"][:12]), flush=True)
    if bilan["arret"]:
        print(f"[candles-vaults] passage interrompu ({bilan['arret']}) : reprise au prochain passage", flush=True)
    if not a.sans_funding and bilan["arret"] != "LIMITE_DEBIT":
        funding = passe_funding(Path(a.root), budget_s=a.budget_funding_s, max_coins=a.max_coins,
                                profondeur_ms=(int(a.profondeur_jours * 86_400_000)
                                               if a.profondeur_jours else None))
        echecs = f" ({','.join(funding['echecs'][:8])})" if funding["echecs"] else ""
        print(f"[candles-vaults] funding 1h : {funding['points']} points ajoutes, {funding['demandes']} demandes, "
              f"{funding['a_jour']} coins a jour, {funding.get('creuses', 0)} pages creusees en "
              f"{funding.get('rondes', 0)} ronde(s), {funding.get('origines', 0)} coins au bout de leur histoire, "
              f"{len(funding['echecs'])} echecs{echecs} -> {SORTIE_FUNDING}"
              + (f" | interrompu ({funding['arret']}) : reprise au prochain passage" if funding["arret"] else ""),
              flush=True)
    return 0


def _point_d_entree() -> int:
    """Ctrl+C : on sort PROPREMENT. L'etat est deja sauve apres chaque page (atomiquement), et
    chaque ligne du ruban est ecrite entiere, donc il n'y a rien a reparer — seulement a le dire.
    """
    try:
        return main()
    except KeyboardInterrupt:
        print()
        print("[candles-vaults] Ctrl+C — arret propre. Etat sauve apres la derniere page complete : "
              "le prochain passage reprend ici, aucune donnee perdue.", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(_point_d_entree())
