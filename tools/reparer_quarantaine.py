r"""Réparation des données mises en quarantaine À TORT par une ancienne règle du certificateur.

    tools\python\python.exe tools\reparer_quarantaine.py --plan            compte, ne verse rien (lecture seule)
    tools\python\python.exe tools\reparer_quarantaine.py                   verse ce qui manque, puis fait sceller

Demande de l'opérateur (23/11/2026) : « si des données semblent cassées, il doit aussi les réparer » ; « ne casse
rien, ne jette aucune donnée viable ». Mesure du jour : 6,5 M lignes en quarantaine, presque toutes des lots du 8 au
16/11, rejetées par des règles CORRIGÉES depuis (le BBO `bid`/`ask` sans `px`, une horloge de passage en retard qui
déclarait « futurs » des trades reçus 108 ms après la bourse). Une partie a été récupérée par des relectures
ultérieures ; une autre non (84 % des trades CopyVault « futurs » sont absents du coffre).

Méthode, ligne par ligne :
1. la ligne mise en quarantaine est RECERTIFIÉE avec les règles d'aujourd'hui ; refusée encore -> elle reste où
   elle est, avec sa raison (rien n'est forcé) ;
2. si elle porte une heure de bourse et une heure de réception, la réception ne précède jamais la bourse (5 s) ;
3. son IDENTITÉ (celle du coffre) est cherchée dans le coffre, sur les shards qui recouvrent sa période : présente
   -> rien à faire ; absente -> elle est versée, une seule fois (une ligne peut avoir été mise en quarantaine par
   plusieurs passages) ;
4. elle entre marquée ``repare_depuis_quarantaine`` (lot, raison d'origine), dans un ruban au nom de son ruban
   d'origine, scellé par le certificateur habituel ; les fichiers de quarantaine ne sont JAMAIS modifiés.
Lecture seule côté marché ; aucune écriture hors de ``runtime/history`` (rubans de transit) et du coffre.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402

QUARANTAINE = Path("runtime") / "coffre_certifie" / "quarantine"
INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
HISTOIRE = Path("runtime") / "history"
RAPPORT = Path("runtime") / "coffre_certifie" / "REPARATIONS_QUARANTAINE.json"
JOUR = 86_400_000
CAUSALITE_MS = 5_000


def annoter(rec: dict, cle: str, valeur: Any) -> dict:
    """Ajoute la provenance, SAUF à un enregistrement qui porte son propre contrôle d'intégrité : le ``checksum`` des
    flux de microstructure couvre TOUS ses champs (23/11 : 550 227 lignes réparées remises en quarantaine pour
    ``checksum_invalide`` parce qu'une étiquette leur avait été ajoutée). Celui-là passe tel quel ; sa provenance est
    dans le nom du ruban et dans le rapport."""
    return dict(rec) if "checksum" in rec else {**rec, cle: valeur}


def _empreinte(identite: tuple) -> bytes:
    return hashlib.blake2b(repr(identite).encode("utf-8"), digest_size=16).digest()


def lire_quarantaine(root: Path, familles: set[str] | None) -> Iterator[tuple[str, str, str, str, dict]]:
    """(lot, famille, tronc du ruban d'origine, raison, enregistrement) de chaque ligne en quarantaine."""
    import sceller_coffre_local as S

    for f in sorted((root / QUARANTAINE).rglob("*.jsonl")):
        if "__" not in f.name:
            continue
        famille, base = f.name.split("__", 1)
        if familles and famille not in familles:
            continue
        # « bbo_tape_1793….jsonl » -> « bbo_tape » : le nom de quarantaine porte DÉJÀ « .jsonl » (23/11 : un
        # « .jsonl » de trop gardait la rotation dans le nom, que le certificateur n'aurait pas reconnu)
        tronc = S._tronc(base.split("__")[0])
        with f.open(encoding="utf-8", errors="replace") as h:
            for ligne in h:
                try:
                    x = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(x.get("record"), dict):
                    yield f.parent.name, famille, tronc, str(x.get("raison")), x["record"]


def candidats(root: Path, familles: set[str] | None, now_ms: int) -> tuple[dict, Counter]:
    """Lignes acceptées par les règles d'aujourd'hui, une par identité : {famille: {empreinte: (ts, tronc, rec)}}."""
    import sceller_coffre_local as S

    par: dict[str, dict[bytes, tuple[int, str, dict]]] = defaultdict(dict)
    bilan: Counter = Counter()
    for lot, famille, tronc, raison, rec in lire_quarantaine(root, familles):
        bilan["lues"] += 1
        norm, decision, motif = C.certifier_record(rec, famille=famille, source=str(rec.get("source") or tronc),
                                                   now_ms=now_ms)
        if decision == C.QUARANTAINE:
            bilan[f"toujours_refusee:{motif}"] += 1
            continue
        ex, recu = norm.get("exchange_ts_ms"), norm.get("received_at_ms")
        if isinstance(ex, (int, float)) and isinstance(recu, (int, float)) and recu < ex - CAUSALITE_MS:
            bilan["reception_avant_la_bourse"] += 1
            continue
        ts = S._ts_primaire(norm, famille)
        if not isinstance(ts, (int, float)):
            bilan["sans_horodatage"] += 1
            continue
        cle = _empreinte(C.identite(norm, famille))
        if cle in par[famille]:
            bilan["doublon_dans_la_quarantaine"] += 1
            continue
        par[famille][cle] = (int(ts), tronc)             # empreinte + heure seulement : 4,9 M lignes tiennent en mémoire
        bilan[f"acceptee:{famille}"] += 1
    return par, bilan


def retirer_ce_que_le_coffre_a(root: Path, par: dict, bilan: Counter) -> None:
    """Retire de ``par`` toute identité déjà au coffre (shards de la famille qui recouvrent la période)."""
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    for famille, lignes in par.items():
        if not lignes:
            continue
        tmin = min(v[0] for v in lignes.values()) - JOUR
        tmax = max(v[0] for v in lignes.values()) + JOUR
        shards = [s for s in index.get("shards", []) if s.get("famille") == famille
                  and (s.get("ts_max_ms") or 0) >= tmin and (s.get("ts_min_ms") or 9e18) <= tmax]
        avant = len(lignes)
        for s in shards:
            try:
                with gzip.open(root / s["shard"], "rt", encoding="utf-8") as g:
                    for ligne in g:
                        try:
                            cle = _empreinte(C.identite(json.loads(ligne), famille))
                        except (ValueError, TypeError):
                            continue
                        lignes.pop(cle, None)
            except OSError:
                bilan[f"shard_illisible:{famille}"] += 1
        bilan[f"deja_au_coffre:{famille}"] += avant - len(lignes)
        bilan[f"a_verser:{famille}"] += len(lignes)
        bilan[f"shards_lus:{famille}"] += len(shards)


def verser(root: Path, par: dict, now_ms: int) -> list[str]:
    """Relit la quarantaine et verse, UNE fois, chaque ligne dont l'identité manque au coffre : un ruban de transit
    par (famille, ruban d'origine), au nom que le certificateur reconnaît. La quarantaine n'est jamais modifiée."""
    restants = {f: set(lignes) for f, lignes in par.items()}
    sorties: dict[tuple[str, str], Any] = {}
    noms: dict[tuple[str, str], tuple[str, Path]] = {}
    comptes: Counter = Counter()
    try:
        for lot, famille, tronc, raison, rec in lire_quarantaine(root, set(restants)):
            norm, decision, _ = C.certifier_record(rec, famille=famille, source=str(rec.get("source") or tronc),
                                                   now_ms=now_ms)
            if decision == C.QUARANTAINE:
                continue
            cle = _empreinte(C.identite(norm, famille))
            if cle not in restants.get(famille, ()):
                continue
            restants[famille].discard(cle)                 # une seule fois, même si plusieurs lots l'ont écartée
            g = (famille, tronc)
            if g not in sorties:
                nom = f"{tronc}_{zlib.crc32(f'{famille}|{tronc}|reparation'.encode()):010d}{int(time.time()):010d}.jsonl.gz"
                detecte = C.detecter_famille(nom)
                if detecte is None or detecte[0] != famille:
                    print(f"  [!] {famille}/{tronc} : {nom} ne serait pas reconnu ({detecte}) : non versé")
                    sorties[g] = None
                    continue
                part = root / HISTOIRE / (nom + ".part")
                part.parent.mkdir(parents=True, exist_ok=True)
                noms[g] = (nom, part)
                sorties[g] = gzip.open(part, "wt", encoding="utf-8", newline="\n")
            if sorties[g] is None:
                continue
            sorties[g].write(json.dumps(annoter(rec, "repare_depuis_quarantaine", {
                "lot": lot, "raison_initiale": raison, "outil": "tools/reparer_quarantaine.py"}),
                ensure_ascii=False, separators=(",", ":")) + "\n")
            comptes[g] += 1
    finally:
        for h in sorties.values():
            if h is not None:
                h.close()
    rubans: list[str] = []
    for g, (nom, part) in noms.items():
        os.replace(part, root / HISTOIRE / nom)
        rubans.append(nom)
        print(f"  ruban {nom} : {comptes[g]:,} ligne(s) réparée(s)", flush=True)
    return rubans


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--familles", nargs="*", default=[])
    p.add_argument("--plan", action="store_true", help="compte seulement : rien n'est versé ni scellé")
    p.add_argument("--now-ms", type=int, default=0)
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    now_ms = a.now_ms or int(time.time() * 1000)
    par, bilan = candidats(root, set(a.familles) or None, now_ms)
    retirer_ce_que_le_coffre_a(root, par, bilan)
    for k, v in sorted(bilan.items()):
        print(f"  {k:<50} {v:>12,}", flush=True)
    rubans: list[str] = []
    code = 0
    if not a.plan and any(par.values()):
        rubans = verser(root, par, now_ms)
        if rubans:
            cmd = [sys.executable, str(RACINE / "tools" / "sceller_coffre_local.py"), "--root", str(root)]
            for n in rubans:
                cmd += ["--nom", n]
            code = subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False).returncode
    rapport = {"genere_ms": int(time.time() * 1000), "plan": a.plan, "bilan": dict(bilan), "rubans": rubans,
               "regle": "recertifiee aujourd'hui + absente du coffre par identite ; quarantaine jamais modifiee"}
    historique = {"passages": []}
    try:
        historique = json.loads((root / RAPPORT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    historique["passages"] = (historique.get("passages") or [])[-19:] + [rapport]
    (root / RAPPORT).write_text(json.dumps(historique, ensure_ascii=False, indent=1), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
