#!/usr/bin/env python3
"""TUNNEL D'EXÉCUTABILITÉ Copy-Vault : chaque passage compté, avec son dénominateur et son motif.

POURQUOI. Le rapport du labo du 12/11 annonçait **0 trade exécutable sur 98 138 signaux** sans que
l'on puisse dire où le tunnel se fermait ni de combien. Les motifs étaient agrégés et pouvaient se
chevaucher. Cet outil mesure le tunnel étape par étape sur les rubans RÉELS, publie à chaque étage
le nombre d'entrants, de sortants et le motif exact de chaque refus, et décompose par jour UTC,
coin et leader.

CE QU'IL NE FAIT PAS : il n'élargit aucune fenêtre de fraîcheur pour « sauver » un signal, il
n'invente aucun carnet, et il ne mesure AUCUN PnL. Un signal exécutable n'est pas un trade
rentable : c'est seulement un signal dont la chaîne d'observation est causalement complète.

Les règles appliquées sont IMPORTÉES des modules de production (classification d'entrée, liaison du
carnet pré-signal), pour qu'une divergence entre la mesure et le moteur soit impossible.

PAPER / LECTURE SEULE : aucune requête réseau, aucune écriture hors du rapport.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_executable import (  # noqa: E402
    classify_live_entry_action,
    expected_open_direction,
)
from hl_observer.collection import copy_vault_reference_binding as LIAISON  # noqa: E402
from hl_observer.backtesting import coffre_tranches as TR  # noqa: E402
from hl_observer.backtesting import copy_vault_detention as DET  # noqa: E402
from hl_observer.ops import fraicheur_preuve as FRAICHEUR  # noqa: E402
from hl_observer.ops import sauts_d_horloge as SAUTS  # noqa: E402

#: Deux sources possibles, et c'est le defaut qui a motive ce changement.
#:
#: 17/11/2026 — LE DENOMINATEUR ETAIT UN ARTEFACT. Le tunnel ne lisait que la QUEUE des rubans
#: vivants, bornee par un budget d'octets. Mesure du jour : 400 Mo de carnets couvrent 652 min,
#: 120 Mo de fills couvrent 3 jours — resultat, `HORS_FENETRE_DE_MESURE` emportait **35 239 refus
#: sur 43 793 signaux (80 %)**, c'est-a-dire que la quasi-totalite du verdict decrivait la taille
#: de mon tampon de lecture, pas la donnee. Pire : le labo mesure sur le COFFRE (6 988 954 lignes
#: de carnets sur 21 jours) et le tunnel sur le ruban, donc les deux dénominateurs ne pouvaient
#: pas etre reconcilies — exactement ce que l'objectif exige de fermer.
#:
#: Le mode `coffre` lit la MEME chaine depuis les shards certifies, par shards selectionnes sur
#: les bornes de l'index : la fenetre devient une propriete des donnees, et `HORS_FENETRE` devient
#: une mesure. Le mode `ruban` reste disponible pour juger la collecte EN COURS, non encore scellee.
SOURCE_RUBAN = "ruban"
SOURCE_COFFRE = "coffre"

FILLS = Path("runtime") / "data" / "vault_fills_live.jsonl"
LANE = Path("runtime") / "data" / "copy_vault_l2_lane.jsonl"
#: Délai de copie déclaré par le compagnon : l'entrée s'observe à `signal + ce délai`.
COPY_DELAY_MS = 60_000
#: Horizon de sortie mesuré. Une sortie non observée reste CENSURÉE, jamais un PnL nul.
EXIT_HORIZON_MS = 300_000


def _lire_queue(chemin: Path, octets: int) -> list[bytes]:
    """Les lignes COMPLÈTES de la fin du fichier. La première, tronquée, est jetée."""
    taille = chemin.stat().st_size
    with chemin.open("rb") as fh:
        fh.seek(max(0, taille - octets))
        brut = fh.read()
    lignes = brut.split(b"\n")
    if taille > octets:
        lignes = lignes[1:]                     # ligne coupee par le seek
    return [l for l in lignes if l.strip()]


def _jour(ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))


def charger_carnets(root: Path, octets: int) -> tuple[dict[str, list[int]], int, int]:
    """``{coin: [instants de reception triés]}`` + bornes de la fenêtre observée."""
    par_coin: dict[str, list[int]] = defaultdict(list)
    mini = maxi = None
    for ligne in _lire_queue(root / LANE, octets):
        try:
            o = json.loads(ligne)
        except ValueError:
            continue
        recu = o.get("received_at_ms")
        coin = o.get("coin")
        if type(recu) is not int or not isinstance(coin, str):
            continue
        par_coin[coin].append(recu)
        mini = recu if mini is None else min(mini, recu)
        maxi = recu if maxi is None else max(maxi, recu)
    for v in par_coin.values():
        v.sort()
    return par_coin, int(mini or 0), int(maxi or 0)


def _index_du_coffre(root: Path) -> list[dict[str, Any]]:
    chemin = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    if not chemin.is_file():
        raise SystemExit(f"index du coffre introuvable : {chemin}")
    index = json.loads(chemin.read_text(encoding="utf-8"))
    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list) or not shards:
        raise SystemExit("index du coffre vide")
    return [x for x in shards if isinstance(x, dict)]


def charger_carnets_du_coffre(root: Path, *, debut_ms: int | None = None,
                              fin_ms: int | None = None) -> tuple[dict[str, Any], int, int, dict]:
    """Les instants de RECEPTION des carnets, lus depuis les shards certifies, en flux.

    DEUX HORLOGES, ET C'EST VOULU. Les shards sont SELECTIONNES sur l'horloge de l'index
    (``exchange_ts_ms`` pour ``book_l2``, la meme que le scelleur), mais la chaine causale se
    mesure sur l'horloge de RECEPTION : c'est l'instant ou l'observateur a su, et lui seul peut
    fonder un « strictement avant ». L'ecart entre les deux est le retard d'observation (dizaines
    de ms), ce qui insere legerement la fenetre mesuree dans la fenetre selectionnee — declare
    dans le rapport plutot que masque.

    Les instants sont gardes dans un ``array('q')`` : 8 octets par entree au lieu d'environ 36
    pour une liste d'entiers Python. Sur 7 millions de carnets, 56 Mo au lieu de 250.
    """
    from array import array

    par_coin: dict[str, Any] = {}
    mini = maxi = None
    sel = TR.selectionner(_index_du_coffre(root), famille="book_l2",
                          debut_ms=debut_ms, fin_ms=fin_ms)
    compteurs: dict[str, Any] = {}
    lignes = 0
    sans_reception = 0
    for row in TR.flux(root, sel["retenus"], famille="book_l2",
                       debut_ms=debut_ms, fin_ms=fin_ms, compteurs=compteurs):
        recu = row.get("received_at_ms")
        coin = row.get("coin")
        if type(recu) is not int or not isinstance(coin, str) or not coin:
            sans_reception += 1
            continue
        par_coin.setdefault(coin, array("q")).append(recu)
        lignes += 1
        mini = recu if mini is None else min(mini, recu)
        maxi = recu if maxi is None else max(maxi, recu)
    for v in par_coin.values():
        # `flux` rend les lignes shard par shard : l'ordre global n'est pas garanti.
        v2 = sorted(v)
        del v[:]
        v.extend(v2)
    meta = {
        "source": SOURCE_COFFRE,
        "shards_retenus": len(sel["retenus"]),
        "shards_sans_bornes": len(sel["sans_bornes"]),
        "shards_lus": compteurs.get("shards_lus", 0),
        "shards_refuses": compteurs.get("shards_refuses", []),
        "lignes_sans_horloge_index": compteurs.get("lignes_sans_horloge", 0),
        "lignes_sans_horloge_de_reception": sans_reception,
        "lignes_retenues": lignes,
    }
    return par_coin, int(mini or 0), int(maxi or 0), meta


def fills_du_coffre(root: Path, *, debut_ms: int | None = None, fin_ms: int | None = None,
                    compteurs: dict[str, Any] | None = None):
    """Les fills certifies, en flux. Seule ``fills_forward`` porte des fills LIVE_WS causaux."""
    sel = TR.selectionner(_index_du_coffre(root), famille="fills_forward",
                          debut_ms=debut_ms, fin_ms=fin_ms)
    c = compteurs if compteurs is not None else {}
    c["shards_retenus_fills"] = len(sel["retenus"])
    yield from TR.flux(root, sel["retenus"], famille="fills_forward",
                       debut_ms=debut_ms, fin_ms=fin_ms, compteurs=c)


def fills_du_ruban(root: Path, octets: int, compteurs: dict[str, Any]):
    """Les fills de la QUEUE du ruban vivant, parses. Les lignes illisibles sont COMPTEES."""
    compteurs.setdefault("lignes_illisibles", 0)
    compteurs.setdefault("lignes_non_objet", 0)
    for brut in _lire_queue(root / FILLS, octets):
        try:
            fill = json.loads(brut)
        except ValueError:
            compteurs["lignes_illisibles"] += 1
            continue
        if not isinstance(fill, dict):
            compteurs["lignes_non_objet"] += 1
            continue
        yield fill


def _carnet_avant(instants: list[int], borne_ms: int) -> int | None:
    """Le plus RÉCENT instant strictement antérieur à ``borne_ms``, ou ``None``."""
    i = bisect.bisect_left(instants, borne_ms) - 1
    return instants[i] if i >= 0 else None


def _carnet_apres(instants: list[int], cible_ms: int, tolerance_ms: int) -> int | None:
    """Le premier instant >= cible, dans la tolérance. Sert pour ENTRY et EXIT."""
    i = bisect.bisect_left(instants, cible_ms)
    if i >= len(instants):
        return None
    return instants[i] if instants[i] - cible_ms <= tolerance_ms else None


def _instant_chaine_de_preuve(root: Path) -> dict[str, Any]:
    """Les horloges de la chaine de preuve — lues dans les FAITS (voir `fraicheur_preuve`).

    Chantier 13 : une mesure doit DIRE si la preuve couvre la collecte qu'elle qualifie. Depuis le
    17/11, l'horloge du labo est la fin des donnees reellement rejouees, et non la date d'ecriture
    de son dernier fichier ; et l'age du tier SAFE entre dans le verdict.
    """
    return dict(FRAICHEUR.horloges_de_la_chaine(root))


def mesurer(root: Path, *, octets_fills: int, octets_carnets: int,
            source: str = SOURCE_RUBAN, debut_ms: int | None = None,
            fin_ms: int | None = None, mesurer_detention: bool = True) -> dict[str, Any]:
    """Le tunnel, etage par etage, sur la source demandee.

    La logique de jugement est IDENTIQUE pour les deux sources : seule l'origine des lignes
    change. C'est la condition pour que le chiffre du coffre et celui du ruban soient comparables
    — et donc pour que le labo (coffre) et le tunnel cessent d'avoir deux denominateurs.
    """
    etapes = Counter()
    motifs = Counter()
    lecture: dict[str, Any] = {}
    if str(source) == SOURCE_COFFRE:
        carnets, lane_min, lane_max, meta_carnets = charger_carnets_du_coffre(
            root, debut_ms=debut_ms, fin_ms=fin_ms)
        fills = fills_du_coffre(root, debut_ms=debut_ms, fin_ms=fin_ms, compteurs=lecture)
        lecture.update(meta_carnets)
    else:
        carnets, lane_min, lane_max = charger_carnets(root, octets_carnets)
        meta_carnets = {"source": SOURCE_RUBAN,
                        "lignes_retenues": sum(len(v) for v in carnets.values())}
        fills = fills_du_ruban(root, octets_fills, lecture)
        lecture.update(meta_carnets)
    par_jour: dict[str, Counter] = defaultdict(Counter)
    par_coin: dict[str, Counter] = defaultdict(Counter)
    par_leader: dict[str, Counter] = defaultdict(Counter)
    ages_reference: list[int] = []
    vus: set[str] = set()
    # Un recul de l'heure murale rend l'ordre « carnet recu AVANT le signal » incertain : on le
    # detecte contre l'horloge monotone des fills, et on refuse les signaux de la fenetre.
    horloge = SAUTS.Detecteur()

    for fill in fills:
        etapes["A_lignes_lues"] += 1
        recu = fill.get("received_at_ms")
        ts = fill.get("ts_ms")
        coin = fill.get("coin")
        vault = str(fill.get("vault") or "").lower()
        if type(recu) is not int or type(ts) is not int or not isinstance(coin, str) or not vault:
            motifs["IDENTITE_OU_HORLOGE_ABSENTE"] += 1
            continue
        etapes["B_horloges_et_identite"] += 1
        horloge.observer(recu, fill.get("recv_mono_ns"))

        if fill.get("source") != "LIVE_WS":
            motifs["PAS_LIVE_WS"] += 1
            continue
        marqueur = fill.get("isSnapshot", fill.get("is_snapshot"))
        if marqueur is not False:
            motifs["SNAPSHOT_OU_MARQUEUR_ABSENT"] += 1
            continue
        etapes["C_fill_live_non_snapshot"] += 1

        # Dédoublonnage par identité stable : un même fill relu ne crée pas deux signaux.
        identite = str(fill.get("stable_event_id") or fill.get("hash") or "")
        if identite and identite in vus:
            motifs["DOUBLON"] += 1
            continue
        if identite:
            vus.add(identite)

        if expected_open_direction(fill) is None or classify_live_entry_action(fill) is None:
            motifs["PAS_UNE_OUVERTURE"] += 1
            continue
        etapes["D_signal_d_ouverture"] += 1
        jour = _jour(recu)
        par_jour[jour]["signaux"] += 1
        par_coin[coin]["signaux"] += 1
        par_leader[vault]["signaux"] += 1
        if horloge.ambigu(recu):
            motifs["SAUT_D_HORLOGE_EN_ARRIERE"] += 1
            horloge.noter_signal(recu, refuse=True)
            continue
        horloge.noter_signal(recu)

        # L'instant du signal doit être couvert par la fenêtre de carnets observée, sinon on ne
        # juge PAS : une absence de carnet hors fenêtre est une absence de MESURE, pas un refus.
        if not (lane_min + LIAISON.AGE_MAX_MS <= recu <= lane_max):
            motifs["HORS_FENETRE_DE_MESURE"] += 1
            continue
        etapes["E_jugeable_dans_la_fenetre"] += 1

        instants = carnets.get(coin)
        if not instants:
            motifs["AUCUN_CARNET_POUR_CE_COIN"] += 1
            par_coin[coin]["sans_carnet"] += 1
            continue
        avant = _carnet_avant(instants, recu)
        if avant is None:
            motifs["NO_PRESIGNAL_BOOK"] += 1
            continue
        age = recu - avant
        if age > LIAISON.AGE_MAX_MS:
            motifs["PRESIGNAL_BOOK_TOO_OLD"] += 1
            continue
        etapes["F_reference_pre_signal"] += 1
        ages_reference.append(age)
        par_jour[jour]["reference"] += 1

        entree = _carnet_apres(instants, recu + COPY_DELAY_MS, LIAISON.AGE_MAX_MS)
        if entree is None:
            motifs["ENTRY_BOOK_ABSENT"] += 1
            continue
        etapes["G_carnet_d_entree"] += 1
        par_jour[jour]["entree"] += 1

        sortie = _carnet_apres(instants, entree + EXIT_HORIZON_MS, LIAISON.AGE_MAX_MS)
        if sortie is None:
            motifs["EXIT_CENSURE"] += 1          # censuré : ni PnL nul, ni clôture implicite
            continue
        etapes["H_sortie_observee"] += 1
        par_jour[jour]["sortie"] += 1
        par_coin[coin]["complet"] += 1
        par_leader[vault]["complet"] += 1

    ages_reference.sort()
    # 17/11 — L'HORIZON DE SORTIE EST UN CHOIX : on le confronte a la DUREE REELLE.
    #
    # Le tunnel mesure l'observabilite d'une sortie a `entree + EXIT_HORIZON_MS` (300 s). Mesure du
    # 16/11 sur 1 660 493 fills du coffre : la detention mediane des leaders est de **44,8 min**
    # (p25 10,7 min, p75 2,27 h), et **160 comptes sur 163** ont une mediane superieure a 300 s.
    # L'horizon tombe donc entre le p10 et le p25 : il modelise une strategie que les leaders
    # observes n'emploient pas. Publier les deux chiffres cote a cote evite qu'un « 99,7 % de
    # chaines completes » soit lu comme « 99,7 % de strategies realistes ».
    detention: dict[str, Any] | None = None
    if mesurer_detention and str(source) == SOURCE_COFFRE:
        compteurs_det: dict[str, Any] = {}
        detention = DET.apparier(
            fills_du_coffre(root, debut_ms=debut_ms, fin_ms=fin_ms, compteurs=compteurs_det))
        mediane = detention["detention_ms"].get("p50")
        detention["horizon_du_tunnel_ms"] = EXIT_HORIZON_MS
        detention["horizon_vs_mediane"] = (
            None if mediane is None else round(EXIT_HORIZON_MS / float(mediane), 4))
        detention["comptes_tenant_plus_que_l_horizon"] = sum(
            1 for b in detention["comptes"].values()
            if b.get("mediane_ms") is not None and b["mediane_ms"] > EXIT_HORIZON_MS)
        detention["comptes_avec_mediane"] = sum(
            1 for b in detention["comptes"].values() if b.get("mediane_ms") is not None)
        # le detail par compte est volumineux : il reste dans le rapport JSON, pas a l'ecran
    fraicheur = FRAICHEUR.evaluer(collecte_ms=lane_max or None,
                                  elements=_instant_chaine_de_preuve(root))
    return {
        "fraicheur_de_la_preuve": fraicheur,
        "schema": "hypersmart.tunnel_executabilite.v1",
        "genere_ms": int(time.time() * 1000),
        "paper_read_only": True,
        "real_execution": False,
        "fenetre_carnets": {
            "debut_ms": lane_min, "fin_ms": lane_max,
            "duree_min": round((lane_max - lane_min) / 60000.0, 1),
            "coins": len(carnets),
            "lignes": sum(len(v) for v in carnets.values()),
        },
        "source": str(source),
        "bornes_de_lecture": (
            {"octets_fills": octets_fills, "octets_carnets": octets_carnets}
            if str(source) == SOURCE_RUBAN
            else {"fenetre_demandee_ms": [debut_ms, fin_ms]}),
        # Ce qu'a coute la lecture, et ce qu'elle n'a PAS pu lire. Un refus de shard doit etre
        # visible : sinon un tunnel « complet » pourrait l'etre sur un corpus amoindri.
        "lecture": lecture,
        "horloges": {
            "selection_des_shards": "horloge d'index (meme table que le scelleur)",
            "mesure_causale": "received_at_ms — l'instant ou l'observateur a su",
            "consequence": ("la fenetre mesuree est legerement INSEREE dans la fenetre "
                            "selectionnee, du retard d'observation"),
        },
        "regles": {
            "copy_delay_ms": COPY_DELAY_MS,
            "exit_horizon_ms": EXIT_HORIZON_MS,
            "age_max_carnet_ms": LIAISON.AGE_MAX_MS,
            "egalite_ms": "REFUSEE (strictement anterieur)",
        },
        "detention_des_leaders": detention,
        "sauts_d_horloge": horloge.bilan(),
        "etapes": dict(etapes),
        "motifs_de_refus": dict(sorted(
            ({**{k: v for k, v in motifs.items()},
              **({"LIGNE_ILLISIBLE": lecture["lignes_illisibles"]}
                 if lecture.get("lignes_illisibles") else {}),
              **({"LIGNE_NON_OBJET": lecture["lignes_non_objet"]}
                 if lecture.get("lignes_non_objet") else {})}).items(),
            key=lambda kv: -kv[1])),
        "age_reference_ms": {
            "n": len(ages_reference),
            "median": ages_reference[len(ages_reference) // 2] if ages_reference else None,
            "p90": ages_reference[int(0.9 * len(ages_reference))] if ages_reference else None,
            "max": ages_reference[-1] if ages_reference else None,
        },
        "par_jour_utc": {j: dict(c) for j, c in sorted(par_jour.items())},
        "top_coins_sans_carnet": sorted(
            ((c, v["sans_carnet"]) for c, v in par_coin.items() if v.get("sans_carnet")),
            key=lambda kv: -kv[1])[:15],
        "coins_complets": sorted(
            ((c, v["complet"]) for c, v in par_coin.items() if v.get("complet")),
            key=lambda kv: -kv[1])[:15],
        "leaders": {
            "distincts": len(par_leader),
            "avec_signal": sum(1 for v in par_leader.values() if v.get("signaux")),
            "avec_chaine_complete": sum(1 for v in par_leader.values() if v.get("complet")),
        },
    }


def afficher(rapport: dict[str, Any]) -> None:
    f = rapport["fenetre_carnets"]
    print("=" * 84)
    print("  TUNNEL D'EXECUTABILITE COPY-VAULT — PAPER / LECTURE SEULE")
    lec = rapport.get("lecture") or {}
    print(f"  source : {rapport.get('source', '?')}"
          + (f" | shards lus {lec.get('shards_lus', 0):,}"
             f" | refuses {len(lec.get('shards_refuses') or ())}"
             if rapport.get("source") == SOURCE_COFFRE else ""))
    print(f"  fenetre de carnets : {f['duree_min']} min ({f['duree_min'] / 1440:.1f} j) | "
          f"{f['lignes']:,} lignes | {f['coins']} coins")
    h = rapport.get("sauts_d_horloge") or {}
    print(f"  sauts d'horloge : {h.get('verdict', '?')} | en avant {h.get('sauts_en_avant', 0)}"
          f" | en arriere {h.get('sauts_en_arriere', 0)}"
          f" | lignes sans horloge monotone {h.get('lignes_sans_horloge_monotone', 0):,}")
    print("=" * 84)
    etapes = rapport["etapes"]
    base = etapes.get("D_signal_d_ouverture") or 0
    for nom in ("A_lignes_lues", "B_horloges_et_identite", "C_fill_live_non_snapshot",
                "D_signal_d_ouverture", "E_jugeable_dans_la_fenetre", "F_reference_pre_signal",
                "G_carnet_d_entree", "H_sortie_observee"):
        n = etapes.get(nom, 0)
        part = f"{100.0 * n / base:6.1f} % des signaux" if base and nom >= "D" else ""
        print(f"  {nom:<30} {n:>10,}  {part}")
    print()
    print("  MOTIFS DE REFUS (chaque ligne est comptee UNE fois, au premier refus) :")
    for motif, n in rapport["motifs_de_refus"].items():
        print(f"    {motif:<34} {n:>10,}")
    age = rapport["age_reference_ms"]
    if age["n"]:
        print()
        print(f"  age du carnet de reference : median {age['median']:,} ms | "
              f"p90 {age['p90']:,} ms | max {age['max']:,} ms")
    det = rapport.get("detention_des_leaders")
    if det:
        def _duree(ms):
            if ms is None:
                return "n/d"
            ms = float(ms)
            if ms < 90_000:
                return f"{ms / 1000:.1f} s"
            return f"{ms / 60_000:.1f} min" if ms < 5_400_000 else f"{ms / 3_600_000:.2f} h"
        d = det["detention_ms"]
        print()
        print(f"  DETENTION REELLE DES LEADERS ({det['appariees']:,} paires appariees, "
              f"part censuree {det['part_censuree']}) :")
        print(f"     p10 {_duree(d['p10']):>9} | p25 {_duree(d['p25']):>9} | "
              f"p50 {_duree(d['p50']):>9} | p75 {_duree(d['p75']):>9} | p90 {_duree(d['p90']):>9}")
        print(f"     mediane ponderee par la taille : {_duree(det['detention_mediane_ponderee_par_taille_ms'])}")
        print(f"     horizon du tunnel : {_duree(det['horizon_du_tunnel_ms'])} = "
              f"{det['horizon_vs_mediane']} fois la mediane reelle | "
              f"{det['comptes_tenant_plus_que_l_horizon']}/{det['comptes_avec_mediane']} comptes "
              f"tiennent PLUS longtemps que l'horizon")
    print()
    print("  PAR JOUR UTC :", json.dumps(rapport["par_jour_utc"], ensure_ascii=False))
    print("  LEADERS :", json.dumps(rapport["leaders"]))
    fraicheur = rapport.get("fraicheur_de_la_preuve") or {}
    if fraicheur:
        print(" ", FRAICHEUR.message(fraicheur))
    if rapport["top_coins_sans_carnet"]:
        print("  coins sans carnet :", rapport["top_coins_sans_carnet"][:8])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--octets-fills", type=int, default=30_000_000)
    p.add_argument("--octets-carnets", type=int, default=250_000_000)
    p.add_argument("--source", choices=(SOURCE_RUBAN, SOURCE_COFFRE), default=SOURCE_RUBAN,
                   help="ruban vivant (collecte en cours) ou coffre certifie (fenetre reelle)")
    p.add_argument("--depuis", default="", help="borne basse AAAA-MM-JJ UTC (mode coffre)")
    p.add_argument("--jusqu", default="", help="borne haute AAAA-MM-JJ UTC incluse (mode coffre)")
    p.add_argument("--sans-detention", action="store_true",
                   help="saute la mesure de detention reelle des leaders (mode coffre)")
    p.add_argument("--sortie", default="")
    a = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = Path(a.root)
    import datetime as _dt

    def _borne(texte: str, fin_de_journee: bool) -> int | None:
        if not texte.strip():
            return None
        jour = _dt.datetime.strptime(texte.strip(), "%Y-%m-%d").replace(tzinfo=_dt.UTC)
        if fin_de_journee:
            jour = jour + _dt.timedelta(days=1) - _dt.timedelta(milliseconds=1)
        return int(jour.timestamp() * 1000)

    rapport = mesurer(root, octets_fills=a.octets_fills, octets_carnets=a.octets_carnets,
                      source=a.source, debut_ms=_borne(a.depuis, False),
                      fin_ms=_borne(a.jusqu, True), mesurer_detention=not a.sans_detention)
    afficher(rapport)
    cible = Path(a.sortie) if a.sortie else (
        root / "runtime" / "reports" / "tunnel_executabilite"
        / f"tunnel_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  rapport : {cible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
