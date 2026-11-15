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
INTERVALLES_MS = {"5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}
SORTIES = {"5m": Path("runtime") / "history" / "candles_5m.jsonl",
           "1h": Path("runtime") / "history" / "candles_1h.jsonl",
           "1d": Path("runtime") / "history" / "candles_1d.jsonl"}
SORTIE = SORTIES["5m"]
SORTIE_FUNDING = Path("runtime") / "history" / "funding_1h.jsonl"
SERIE_FUNDING = "funding"
PAGE_FUNDING = 500                # fundingHistory rend au plus 500 points par réponse
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


def coins_suivis(root: Path) -> list[str]:
    """Coins des fills de backfill, puis ceux des listes de coins des leaders ; sans doublon."""
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
    return list(coins)


def _post_candles(coin: str, intervalle: str, a: int, b: int, *, timeout_s: float = 15.0) -> Any:
    corps = json.dumps({"type": "candleSnapshot",
                        "req": {"coin": coin, "interval": intervalle, "startTime": int(a), "endTime": int(b)}}).encode()
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


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
        return json.loads(rep.read().decode("utf-8"))


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


def passe_funding(root: Path, *, now_ms: int | None = None, poster=_post_funding,
                  dormir: Callable[[float], None] = time.sleep, budget_s: float = 1500.0,
                  max_coins: int | None = None, univers: set[str] | None | str = "auto",
                  horloge: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Un passage borné : rattrape ou prolonge l'historique horaire du funding de chaque coin."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if univers == "auto":
        univers = charger_univers(root)
    coins, _inconnus = filtrer_abonnables(coins_suivis(root), univers)
    etat = charger_etat(root, (SERIE_FUNDING,))
    derniers = etat[SERIE_FUNDING]
    debut = horloge()
    compte: dict[str, Any] = {"demandes": 0, "points": 0, "a_jour": 0, "echecs": [], "arret": None}
    chemin = root / SORTIE_FUNDING
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # 15/11/2026 — LA PASSE ETAIT MUETTE. Verifie : **zero octet de sortie en une heure**, car le
    # seul `print` arrivait APRES l'epuisement du budget (jusqu'a 8 h plus tard). Un rattrapage qui
    # ne dit rien pendant huit heures est indistinguable d'un rattrapage mort — et on ne peut pas
    # decider d'attendre ou de relancer sans le savoir.
    ordre = sorted(coins, key=lambda c: derniers.get(c, 0))[:max_coins]
    total_coins = len(ordre)
    debut_heure = time.time()
    print(f"[funding] rattrapage de {total_coins} coins | cible "
          f"{PROFONDEUR_FUNDING_MS // 86_400_000} jours | budget {budget_s:.0f} s", flush=True)
    for rang, coin in enumerate(ordre, 1):
        points_avant = compte["points"]
        while not compte["arret"]:
            if horloge() - debut > budget_s:
                compte["arret"] = "BUDGET_DE_TEMPS"
                break
            dernier = derniers.get(coin, 0)
            a = max(now_ms - PROFONDEUR_FUNDING_MS, dernier + 1)
            if a + 3_600_000 > now_ms:
                compte["a_jour"] += 1
                break
            CF.ceder_au_direct(dormir)
            lignes, pleine, erreur = tirer_funding(coin, a, now_ms, poster=poster)
            if erreur == "LIMITE_DEBIT":
                dormir(ATTENTE_REFUS_S)
                lignes, pleine, erreur = tirer_funding(coin, a, now_ms, poster=poster)
                if erreur == "LIMITE_DEBIT":
                    compte["arret"] = "LIMITE_DEBIT"
                    break
            compte["demandes"] += 1
            if erreur:
                compte["echecs"].append(coin)
                dormir(20.0 / BUDGET_POIDS_PAR_MINUTE * 60.0)
                break
            nouvelles = [x for x in lignes if dernier < x["ts_ms"] <= now_ms]
            if nouvelles:
                with chemin.open("a", encoding="utf-8") as ruban:
                    for x in nouvelles:
                        ruban.write(json.dumps({**x, "recv_ms": now_ms}, ensure_ascii=False) + "\n")
                derniers[coin] = nouvelles[-1]["ts_ms"]
                compte["points"] += len(nouvelles)
                sauver_etat(root, etat)
            dormir((20.0 + len(lignes) / 20.0) / BUDGET_POIDS_PAR_MINUTE * 60.0)
            if not pleine or not nouvelles:
                break                                   # dernière page de ce coin
        # UNE LIGNE PAR COIN, poussee immediatement : c'est ce qui rend l'avancement visible.
        gagnes = compte["points"] - points_avant
        ecoule = time.time() - debut_heure
        reste = (budget_s - ecoule) if budget_s else 0.0
        plus_ancien = derniers.get(coin, 0)
        jours = ((now_ms - plus_ancien) / 86_400_000) if plus_ancien else 0.0
        print(f"[funding] {rang:>4}/{total_coins} {coin:<12} +{gagnes:>6} points | "
              f"remonte a {jours:>6.0f} j | {compte['points']:>8} au total | "
              f"{ecoule / 60:.0f} min ecoulees, {max(0, reste) / 60:.0f} restantes", flush=True)
        if compte["arret"]:
            print(f"[funding] ARRET : {compte['arret']} apres {rang}/{total_coins} coins "
                  f"-> la passe suivante reprendra ici (l'etat est sauve par coin)", flush=True)
            break
    sauver_etat(root, etat)
    return compte


def _etat_depuis_ruban(chemin: Path, champ: str = "t_ms") -> dict[str, int]:
    """Dernière bougie écrite par coin, relue du ruban (état perdu ou premier passage après migration)."""
    derniers: dict[str, int] = {}
    try:
        with chemin.open(encoding="utf-8", errors="ignore") as lignes:
            for ligne in lignes:
                try:
                    d = json.loads(ligne)
                    coin, t = str(d["coin"]), int(d[champ])
                except (ValueError, KeyError, TypeError):
                    continue
                if t > derniers.get(coin, 0):
                    derniers[coin] = t
    except OSError:
        pass
    return derniers


def charger_etat(root: Path, intervalles: tuple[str, ...]) -> dict[str, dict[str, int]]:
    try:
        brut = json.loads((root / ETAT).read_text(encoding="utf-8"))
        etat = brut.get("intervalles") if brut.get("_schema") == SCHEMA_ETAT else None
    except (OSError, ValueError, AttributeError):
        etat = None
    etat = etat if isinstance(etat, dict) else {}
    for intervalle in intervalles:
        if not isinstance(etat.get(intervalle), dict):
            etat[intervalle] = (_etat_depuis_ruban(root / SORTIE_FUNDING, "ts_ms") if intervalle == SERIE_FUNDING
                                else _etat_depuis_ruban(root / SORTIES[intervalle]))
    return etat


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
        os.replace(tmp, chemin)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)      # un brouillon oublie finirait par polluer le dossier


def passe(root: Path, *, intervalles: tuple[str, ...] = ("1h", "5m"), now_ms: int | None = None,
          poster=_post_candles, dormir: Callable[[float], None] = time.sleep, budget_s: float = 3000.0,
          max_coins: int | None = None, univers: set[str] | None | str = "auto",
          horloge: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Un passage borné : rattrape ou prolonge les bougies de chaque coin, par intervalle."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
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
        for coin in ordre:
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
                dormir(ATTENTE_REFUS_S)
                lignes, tronque, erreur = tirer(coin, intervalle, a, now_ms, poster=poster, now_ms=now_ms)
                if erreur == "LIMITE_DEBIT":
                    bilan["arret"] = "LIMITE_DEBIT"      # on n'insiste pas : reprise au prochain passage
                    break
            compte["demandes"] += 1
            if erreur:
                compte["echecs"].append(coin)
                dormir(poids_requete(0) / BUDGET_POIDS_PAR_MINUTE * 60.0)
                continue
            nouvelles = [x for x in lignes if x["t_ms"] > dernier]
            if nouvelles:
                with chemin.open("a", encoding="utf-8") as ruban:
                    for x in nouvelles:
                        ruban.write(json.dumps({**x, "recv_ms": now_ms}, ensure_ascii=False) + "\n")
                derniers[coin] = max(x["t_ms"] for x in nouvelles)
                compte["bougies"] += len(nouvelles)
                sauver_etat(root, etat)
            if tronque:
                compte["tronques"].append(coin)
            dormir(poids_requete(len(lignes)) / BUDGET_POIDS_PAR_MINUTE * 60.0)
    sauver_etat(root, etat)
    return bilan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill des bougies 5 min et 1 h des coins des leaders (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalles", default="1h,5m", help="intervalles à tenir à jour (parmi 5m, 1h)")
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
        funding = passe_funding(Path(a.root), budget_s=a.budget_funding_s, max_coins=a.max_coins)
        echecs = f" ({','.join(funding['echecs'][:8])})" if funding["echecs"] else ""
        print(f"[candles-vaults] funding 1h SEUL : {funding['points']} points ajoutes, "
              f"{funding['demandes']} demandes, {funding['a_jour']} coins a jour, "
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
        funding = passe_funding(Path(a.root), budget_s=a.budget_funding_s, max_coins=a.max_coins)
        echecs = f" ({','.join(funding['echecs'][:8])})" if funding["echecs"] else ""
        print(f"[candles-vaults] funding 1h : {funding['points']} points ajoutes, {funding['demandes']} demandes, "
              f"{funding['a_jour']} coins a jour, {len(funding['echecs'])} echecs{echecs} -> {SORTIE_FUNDING}"
              + (f" | interrompu ({funding['arret']}) : reprise au prochain passage" if funding["arret"] else ""),
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
