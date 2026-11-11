"""Vérification PAR RÉFÉRENCE du magasin de ticks natifs (``runtime/data/market_ticks``).

Les collecteurs de venues écrivent un magasin auto-manifesté : par source / canal / instrument,
un ruban actif ``ticks.current.jsonl`` et des shards immuables ``shards/ticks.<...>.jsonl.gz``,
chacun accompagné d'un manifeste (SHA-256, taille, nombre d'événements, bornes temporelles).
Ce magasin pèse des dizaines de Go : le recopier dans le coffre le doublerait sans rien prouver
de plus. Le certificateur le **vérifie en place** — chaque shard relu, son SHA-256 et sa taille
comparés à son manifeste — et le **référence** dans ``MARKET_TICKS_INDEX.json``.

* Incrémental : un shard déjà vérifié (même taille, même date) n'est pas relu ; un dossier dont
  le manifeste n'a pas bougé est sauté sans être listé.
* Borné : ``budget_s`` plafonne chaque passage (la fermeture des collecteurs ne doit pas attendre
  une heure) ; le passage suivant reprend où l'on s'est arrêté. L'index dit toujours honnêtement
  ce qui est vérifié, ce qui reste, et les anomalies.
* Les rubans ``ticks.current.jsonl`` ne sont pas immuables : ils sont recensés « en cours »
  (nombre, taille) et deviennent vérifiables à leur rotation.

Lecture seule vis-à-vis du réseau et des données : rien n'est modifié dans le magasin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
STORE = Path("runtime") / "data" / "market_ticks"
ETAT = Path("runtime") / "coffre_certifie" / "ticks_verifies.sqlite3"
INDEX = Path("runtime") / "coffre_certifie" / "MARKET_TICKS_INDEX.json"
SCHEMA_INDEX = "hypersmart.coffre_certifie.market_ticks_index.v1"

OK = "OK"
MANIFESTE_ABSENT = "MANIFESTE_ABSENT"
MANIFESTE_ILLISIBLE = "MANIFESTE_ILLISIBLE"
TAILLE_DIFFERENTE = "TAILLE_DIFFERENTE"
SHA_DIFFERENT = "SHA_DIFFERENT"


def _connexion(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    cnx = sqlite3.connect(path)
    cnx.execute("PRAGMA journal_mode=WAL")
    cnx.execute(
        "CREATE TABLE IF NOT EXISTS shards (chemin TEXT PRIMARY KEY, source TEXT, canal TEXT, "
        "octets INTEGER, mtime_ns INTEGER, sha256 TEXT, evenements INTEGER, premier_ms INTEGER, "
        "dernier_ms INTEGER, statut TEXT)"
    )
    cnx.execute(
        "CREATE TABLE IF NOT EXISTS dossiers (chemin TEXT PRIMARY KEY, manifeste_mtime_ns INTEGER, "
        "manifeste_octets INTEGER, complet INTEGER)"
    )
    cnx.execute("CREATE INDEX IF NOT EXISTS shards_flux ON shards (source, canal)")
    return cnx


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for bloc in iter(lambda: handle.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def verifier_shard(shard: Path) -> tuple[str, dict[str, Any]]:
    """Statut d'un shard immuable face à son manifeste. Ne lève jamais : tout défaut est un statut."""
    manifeste = shard.with_name(shard.name + ".manifest.json")
    try:
        meta = json.loads(manifeste.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not isinstance(meta.get("sha256"), str):
            return MANIFESTE_ILLISIBLE, {}
    except FileNotFoundError:
        return MANIFESTE_ABSENT, {}
    except (OSError, ValueError):
        return MANIFESTE_ILLISIBLE, {}
    infos = {
        "sha256": meta["sha256"],
        "evenements": meta.get("event_count") if type(meta.get("event_count")) is int else None,
        "premier_ms": meta.get("first_received_ts_ms") if type(meta.get("first_received_ts_ms")) is int else None,
        "dernier_ms": meta.get("last_received_ts_ms") if type(meta.get("last_received_ts_ms")) is int else None,
    }
    try:
        taille = shard.stat().st_size
        if type(meta.get("bytes")) is int and meta["bytes"] != taille:
            return TAILLE_DIFFERENTE, infos
        if _sha256(shard) != meta["sha256"]:
            return SHA_DIFFERENT, infos
    except OSError:
        return MANIFESTE_ILLISIBLE, infos
    return OK, infos


def _dossiers_instrument(store: Path):
    """(source, canal, dossier) triés, Hyperliquid d'abord : c'est la venue que le labo exploite."""
    try:
        sources = sorted((e for e in os.scandir(store) if e.is_dir()),
                         key=lambda e: (not e.name.startswith("hyperliquid"), e.name))
    except OSError:
        return
    for source in sources:
        for canal in sorted((e for e in os.scandir(source.path) if e.is_dir()), key=lambda e: e.name):
            for instrument in sorted((e for e in os.scandir(canal.path) if e.is_dir()), key=lambda e: e.name):
                yield source.name, canal.name, Path(instrument.path)


def verifier_store(root: Path, *, budget_s: float = 45.0, horloge=time.monotonic) -> dict[str, Any]:
    """Un passage borné de vérification ; renvoie (et écrit) l'état d'ensemble du magasin."""
    root = Path(root).resolve()
    store = root / STORE
    if not store.is_dir():
        return {"present": False}
    cnx = _connexion(root / ETAT)
    debut = horloge()
    verifies = anomalies = 0
    restants = 0          # dossiers non terminés pendant ce passage
    en_cours: dict[tuple[str, str], list[int]] = {}
    epuise = False
    for source, canal, dossier in _dossiers_instrument(store):
        relatif = dossier.relative_to(root).as_posix()
        courant = dossier / "ticks.current.jsonl"
        try:
            taille_courant = courant.stat().st_size
        except OSError:
            taille_courant = 0
        if taille_courant:
            cumul = en_cours.setdefault((source, canal), [0, 0])
            cumul[0] += 1
            cumul[1] += taille_courant
        try:
            st = (dossier / "ticks.manifest.json").stat()
            empreinte = (st.st_mtime_ns, st.st_size)
        except OSError:
            empreinte = (0, 0)
        connu = cnx.execute(
            "SELECT manifeste_mtime_ns, manifeste_octets, complet FROM dossiers WHERE chemin = ?", (relatif,)
        ).fetchone()
        if connu and connu[2] and (connu[0], connu[1]) == empreinte:
            continue                                  # rien de nouveau ici : sauté sans lister les shards
        if epuise:
            restants += 1
            continue
        shards_dir = dossier / "shards"
        try:
            shards = sorted((e for e in os.scandir(shards_dir) if e.name.endswith(".jsonl.gz")), key=lambda e: e.name)
        except OSError:
            shards = []
        deja = {
            ligne[0]: (ligne[1], ligne[2])
            for ligne in cnx.execute("SELECT chemin, octets, mtime_ns FROM shards WHERE chemin LIKE ?",
                                     (relatif + "/shards/%",))
        }
        termine = True
        for entree in shards:
            cle = f"{relatif}/shards/{entree.name}"
            st = entree.stat()
            if deja.get(cle) == (st.st_size, st.st_mtime_ns):
                continue                              # déjà vérifié, inchangé
            if horloge() - debut > budget_s:
                epuise = True
                termine = False
                break
            statut, infos = verifier_shard(Path(entree.path))
            cnx.execute(
                "INSERT OR REPLACE INTO shards VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cle, source, canal, st.st_size, st.st_mtime_ns, infos.get("sha256"), infos.get("evenements"),
                 infos.get("premier_ms"), infos.get("dernier_ms"), statut),
            )
            verifies += 1
            anomalies += statut != OK
        cnx.execute("INSERT OR REPLACE INTO dossiers VALUES (?,?,?,?)", (relatif, empreinte[0], empreinte[1], int(termine)))
        cnx.commit()
        if not termine:
            restants += 1
    par_flux = []
    for ligne in cnx.execute(
        "SELECT source, canal, COUNT(*), SUM(octets), SUM(evenements), MIN(premier_ms), MAX(dernier_ms), "
        "SUM(statut != 'OK') FROM shards GROUP BY source, canal ORDER BY source, canal"
    ):
        actif = en_cours.pop((ligne[0], ligne[1]), [0, 0])
        par_flux.append({
            "source": ligne[0], "canal": ligne[1], "shards_verifies": ligne[2], "octets": ligne[3] or 0,
            "evenements": ligne[4], "premier_ms": ligne[5], "dernier_ms": ligne[6], "anomalies": ligne[7] or 0,
            "rubans_en_cours": actif[0], "octets_en_cours": actif[1],
        })
    for (source, canal), actif in sorted(en_cours.items()):   # flux sans aucun shard immuable
        par_flux.append({"source": source, "canal": canal, "shards_verifies": 0, "octets": 0, "evenements": None,
                         "premier_ms": None, "dernier_ms": None, "anomalies": 0,
                         "rubans_en_cours": actif[0], "octets_en_cours": actif[1]})
    liste_anomalies = [
        {"shard": ligne[0], "statut": ligne[1]}
        for ligne in cnx.execute("SELECT chemin, statut FROM shards WHERE statut != 'OK' ORDER BY chemin LIMIT 200")
    ]
    total = cnx.execute("SELECT COUNT(*), SUM(octets), SUM(statut != 'OK') FROM shards").fetchone()
    cnx.close()
    resume = {
        "schema": SCHEMA_INDEX, "present": True, "genere_ms": int(time.time() * 1000),
        "mode": "VERIFIE_ET_REFERENCE_EN_PLACE",
        "shards_verifies": total[0] or 0, "octets_verifies": total[1] or 0, "anomalies": total[2] or 0,
        "verifies_ce_passage": verifies, "anomalies_ce_passage": anomalies,
        "dossiers_restants": restants, "complet": restants == 0,
        "rubans_en_cours": sum(f["rubans_en_cours"] for f in par_flux),
        "octets_en_cours": sum(f["octets_en_cours"] for f in par_flux),
        "par_flux": par_flux, "liste_anomalies": liste_anomalies,
        "read_only": True, "real_execution": False,
    }
    index = root / INDEX
    tmp = index.with_suffix(".json.partial")
    tmp.write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, index)
    return resume


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--budget-s", type=float, default=45.0, help="durée maximale de ce passage (s)")
    args = p.parse_args(argv)
    resume = verifier_store(Path(args.root), budget_s=args.budget_s)
    if not resume.get("present"):
        print("[ticks] aucun magasin de ticks natifs.")
        return 0
    etat = "COMPLET" if resume["complet"] else f"PARTIEL ({resume['dossiers_restants']} dossier(s) restant(s))"
    print(f"[ticks] {resume['shards_verifies']:,} shard(s) vérifié(s) ({resume['octets_verifies'] / 1e9:.2f} Go), "
          f"dont {resume['verifies_ce_passage']:,} à ce passage ; anomalies : {resume['anomalies']} ; état : {etat} ; "
          f"en cours (non immuables) : {resume['rubans_en_cours']} ruban(s), {resume['octets_en_cours'] / 1e9:.2f} Go.")
    return 4 if resume["anomalies"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
