#!/usr/bin/env python3
"""RÉINDEXAGE TRAÇABLE des shards scellés sans horloge lisible.

POURQUOI. `_ts_primaire` du scelleur ne connaissait pas les horloges de deux familles :
`position` (n'a que `received_at_ms`) et `trades_marche` (a `exchange_ts_ms`). Leurs shards ont
donc été indexés avec `jours = ["0000-00-00"]` et sans `ts_min_ms`/`ts_max_ms`. Conséquence
directe : **aucune étude ne peut les découper par jour ni par fenêtre** — alors que la seule
hypothèse que `docs/LOIS_MESUREES.md` n'a pas réfutée (opérateurs lents, réplication d'inventaire)
exige précisément des transitions de position sur des jours indépendants.

Le correctif du 16/11 répare les lots SUIVANTS. Cet outil répare les PRÉCÉDENTS — 363 shards au
16/11 — en relisant leurs lignes et en recalculant leurs bornes avec la MÊME table d'horloges que
le scelleur, importée et non recopiée.

CE QU'IL NE FAIT JAMAIS :

* il ne touche **aucun shard** : il ne lit que leurs octets, et seul l'index est réécrit ;
* il n'écrit rien sans **vérifier le SHA-256** d'abord : un shard divergent est laissé tel quel et
  signalé — on ne réindexe pas une donnée dont on ne peut pas prouver l'intégrité ;
* il ne **fabrique aucune date** : une ligne sans horloge reconnue reste sans horloge, et un shard
  dont aucune ligne n'est datable garde sa sentinelle `0000-00-00` ;
* il prend le **verrou du scelleur** : réécrire l'index pendant une certification le corromprait ;
* il **sauvegarde** l'index avant de le remplacer, et l'écriture est atomique.

PAPER / LECTURE SEULE sur les données. `--appliquer` est exigé pour écrire : par défaut, il montre.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.ops import verrou_pid as VP  # noqa: E402

INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
VERROU = Path("runtime") / "data" / "coffre_certificateur.lock"
SENTINELLE = "0000-00-00"


def _horloges():
    """La table d'horloges du SCELLEUR, importée — jamais recopiée."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sceller_pour_reindex", RACINE / "tools" / "sceller_coffre_local.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._ts_primaire, module._jour_utc


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as fh:
        for bloc in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def a_reindexer(shard: dict[str, Any]) -> bool:
    """Ce shard a-t-il besoin d'être réindexé ? Bornes absentes OU jours sentinelles."""
    bornes_ok = type(shard.get("ts_min_ms")) is int and type(shard.get("ts_max_ms")) is int
    jours = shard.get("jours")
    jours_ok = bool(jours) and not (set(map(str, jours)) <= {SENTINELLE})
    return not (bornes_ok and jours_ok)


def mesurer_shard(root: Path, shard: dict[str, Any], ts_primaire, jour_utc) -> dict[str, Any]:
    """Relit le shard et rend ses VRAIES bornes. Ne modifie rien."""
    rel = str(shard.get("shard") or "")
    chemin = (root / rel).resolve()
    try:
        chemin.relative_to(root.resolve())
    except ValueError:
        return {"statut": "HORS_COFFRE"}
    if not chemin.is_file():
        return {"statut": "ABSENT"}
    attendu = shard.get("sha256")
    if not isinstance(attendu, str) or len(attendu) != 64:
        return {"statut": "SHA_ABSENT"}
    if _sha256(chemin) != attendu:
        return {"statut": "SHA_DIVERGENT"}

    famille = str(shard.get("famille") or "")
    jours: Counter[str] = Counter()
    tmin = tmax = None
    lues = sans_horloge = 0
    ouvrir = gzip.open if chemin.suffix == ".gz" else open
    try:
        with ouvrir(chemin, "rt", encoding="utf-8") as fh:
            for brut in fh:
                if not brut.strip():
                    continue
                try:
                    ligne = json.loads(brut)
                except ValueError:
                    continue
                if not isinstance(ligne, dict):
                    continue
                lues += 1
                instant = ts_primaire(ligne, famille)
                if type(instant) is not int or instant <= 0:
                    sans_horloge += 1
                    continue
                jours[jour_utc(instant)] += 1
                tmin = instant if tmin is None else min(tmin, instant)
                tmax = instant if tmax is None else max(tmax, instant)
    except (OSError, EOFError, gzip.BadGzipFile) as erreur:
        return {"statut": "LECTURE_INTERROMPUE", "detail": type(erreur).__name__}
    if tmin is None:
        # Aucune ligne datable : on NE FABRIQUE PAS de date, la sentinelle reste.
        return {"statut": "AUCUNE_HORLOGE", "lignes": lues, "sans_horloge": sans_horloge}
    return {
        "statut": "MESURE", "ts_min_ms": tmin, "ts_max_ms": tmax,
        "jours": sorted(jours), "lignes": lues, "sans_horloge": sans_horloge,
    }


def reindexer(root: Path, *, appliquer: bool, familles: set[str] | None = None,
              limite: int = 0) -> dict[str, Any]:
    ts_primaire, jour_utc = _horloges()
    chemin_index = root / INDEX
    index = json.loads(chemin_index.read_text(encoding="utf-8"))
    shards = index.get("shards") or []

    candidats = [s for s in shards
                 if isinstance(s, dict) and a_reindexer(s)
                 and (familles is None or str(s.get("famille")) in familles)]
    if limite:
        candidats = candidats[:limite]

    statuts: Counter[str] = Counter()
    par_famille: Counter[str] = Counter()
    repares: list[dict[str, Any]] = []
    debut = time.time()
    for rang, shard in enumerate(candidats, 1):
        mesure = mesurer_shard(root, shard, ts_primaire, jour_utc)
        statuts[mesure["statut"]] += 1
        if mesure["statut"] != "MESURE":
            continue
        par_famille[str(shard.get("famille"))] += 1
        repares.append({"shard": shard.get("shard"), "famille": shard.get("famille"),
                        "ts_min_ms": mesure["ts_min_ms"], "ts_max_ms": mesure["ts_max_ms"],
                        "jours": mesure["jours"], "lignes": mesure["lignes"]})
        if appliquer:
            shard["ts_min_ms"] = mesure["ts_min_ms"]
            shard["ts_max_ms"] = mesure["ts_max_ms"]
            shard["jours"] = mesure["jours"]
            shard["reindexe_ms"] = int(time.time() * 1000)
        if rang % 25 == 0 or rang == len(candidats):
            print(f"  [{rang}/{len(candidats)}] {statuts['MESURE']} mesures, "
                  f"{sum(statuts.values()) - statuts['MESURE']} ecartes", flush=True)

    ecrit = False
    sauvegarde = None
    if appliquer and repares:
        sauvegarde = chemin_index.with_name(
            f"LOCAL_INDEX.avant-reindex-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
        shutil.copy2(chemin_index, sauvegarde)
        tmp = chemin_index.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, chemin_index)
        ecrit = True

    return {
        "schema": "hypersmart.reindexage.v1",
        "genere_ms": int(time.time() * 1000),
        "paper_read_only": True, "real_execution": False,
        "candidats": len(candidats), "statuts": dict(statuts),
        "repares_par_famille": dict(par_famille),
        "index_reecrit": ecrit, "sauvegarde": str(sauvegarde) if sauvegarde else None,
        "duree_s": round(time.time() - debut, 1),
        "exemples": repares[:5],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--appliquer", action="store_true",
                   help="ECRIRE l'index (sinon : montre seulement ce qui serait repare)")
    p.add_argument("--familles", default="",
                   help="limiter a ces familles (virgules) ; vide = toutes")
    p.add_argument("--limite", type=int, default=0, help="n'examiner que N shards (diagnostic)")
    a = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = Path(a.root)
    familles = {x.strip() for x in a.familles.split(",") if x.strip()} or None

    verrou = root / VERROU
    obtenu, mot = VP.prendre(verrou, quoi="un scellage")
    if not obtenu:
        print(f"[reindex] REFUS : {mot}. Reecrire l'index pendant une certification le "
              "corromprait. Relancez apres.")
        return 3
    if mot:
        print(f"[reindex] {mot}")
    try:
        print("=" * 84)
        print("  REINDEXAGE DES SHARDS SANS HORLOGE — les shards ne sont JAMAIS modifies")
        print(f"  mode : {'ECRITURE' if a.appliquer else 'SIMULATION (rien ne sera ecrit)'}")
        print("=" * 84)
        rapport = reindexer(root, appliquer=a.appliquer, familles=familles, limite=a.limite)
    finally:
        VP.rendre(verrou)

    print()
    print(f"  candidats           : {rapport['candidats']:,}")
    print(f"  statuts             : {json.dumps(rapport['statuts'])}")
    print(f"  repares par famille : {json.dumps(rapport['repares_par_famille'])}")
    print(f"  index reecrit       : {rapport['index_reecrit']}")
    if rapport["sauvegarde"]:
        print(f"  sauvegarde          : {rapport['sauvegarde']}")
    print(f"  duree               : {rapport['duree_s']} s")
    if not a.appliquer and rapport["repares_par_famille"]:
        print("\n  -> relancez avec --appliquer pour ecrire l'index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
