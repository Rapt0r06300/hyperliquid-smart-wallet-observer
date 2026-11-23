r"""Preuve de scellement PAR IDENTITÉ des fichiers « à prouver » du recensement : 100 % sans un seul doublon.

    tools\python\python.exe tools\prouver_scellement.py --plan       mesure, n'écrit que le rapport
    tools\python\python.exe tools\prouver_scellement.py              prouve, verse les seules lignes absentes, fait sceller

Un fichier est « à prouver » quand son contenu a sans doute été scellé, mais que l'état du certificateur n'en garde
plus la trace (session antérieure à la règle de l'archiveur du 11/11/2026, rotation dont le préfixe est sorti de
l'historique). Le sceller en entier redéposerait ce que le coffre a déjà (vu le 23/11 : 784 648 lignes BBO) ;
l'ignorer laisserait peut-être des lignes hors du coffre. Ici, chaque ligne est certifiée avec les règles d'aujourd'hui
et son IDENTITÉ (celle du coffre) est cherchée dans les shards de la même famille qui recouvrent sa période :
- toutes présentes -> le fichier est PROUVÉ scellé (``runtime/coffre_certifie/PREUVES_SCELLEMENT.json``, que le
  recensement lit : taille et date du fichier doivent correspondre) ;
- des absentes -> elles seules sont versées, une fois, marquées ``prouve_absent_du_coffre``, dans un ruban de
  transit scellé par le certificateur habituel. Les fichiers prouvés ne sont jamais modifiés.
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
from collections import Counter
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402

INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
PREUVES = Path("runtime") / "coffre_certifie" / "PREUVES_SCELLEMENT.json"
HISTOIRE = Path("runtime") / "history"
MARGE_MS = 3_600_000


def _emp(identite: tuple) -> bytes:
    return hashlib.blake2b(repr(identite).encode("utf-8"), digest_size=16).digest()


def _ouvrir(chemin: Path):
    return gzip.open(chemin, "rt", encoding="utf-8", errors="replace") if chemin.suffix == ".gz" else \
        chemin.open(encoding="utf-8", errors="replace")


class Coffre:
    """Empreintes d'identité des shards d'une famille, lues à la demande et gardées en cache."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.index = json.loads((root / INDEX).read_text(encoding="utf-8"))
        self._cache: dict[str, set[bytes]] = {}

    def shards(self, famille: str, tmin: int, tmax: int) -> list[dict]:
        return [s for s in self.index.get("shards", []) if s.get("famille") == famille
                and (s.get("ts_max_ms") or 0) >= tmin - MARGE_MS and (s.get("ts_min_ms") or 9e18) <= tmax + MARGE_MS]

    def empreintes(self, shard: dict, famille: str) -> set[bytes]:
        cle = shard["shard"]
        if cle not in self._cache:
            ens: set[bytes] = set()
            try:
                with gzip.open(self.root / cle, "rt", encoding="utf-8") as g:
                    for ligne in g:
                        try:
                            ens.add(_emp(C.identite(json.loads(ligne), famille)))
                        except (ValueError, TypeError):
                            continue
            except OSError:
                pass
            if len(self._cache) > 64:                       # mémoire bornée : on garde les shards récents
                self._cache.pop(next(iter(self._cache)))
            self._cache[cle] = ens
        return self._cache[cle]


def prouver_un(root: Path, rel: str, famille: str, coffre: Coffre, now_ms: int, sortie) -> dict[str, Any]:
    """Compte présentes / absentes ; écrit les absentes dans ``sortie`` (ou rien si ``sortie`` est None)."""
    import sceller_coffre_local as S

    chemin = root / rel
    lignes: list[tuple[int, bytes, dict]] = []
    bilan: Counter = Counter()
    with _ouvrir(chemin) as f:
        for brut in f:
            brut = brut.strip()
            if not brut:
                continue
            bilan["lues"] += 1
            try:
                rec = json.loads(brut)
            except ValueError:
                bilan["json_invalide"] += 1
                continue
            norm, decision, motif = C.certifier_record(rec, famille=famille, source=str(rec.get("source") or famille),
                                                       now_ms=now_ms)
            if decision == C.QUARANTAINE:
                bilan[f"refusee:{motif}"] += 1
                continue
            ts = S._ts_primaire(norm, famille)
            lignes.append((int(ts) if isinstance(ts, (int, float)) else 0, _emp(C.identite(norm, famille)), rec))
    if not lignes:
        return {"fichier": rel, **bilan, "presentes": 0, "absentes": 0}
    datees = [t for t, _, _ in lignes if t]
    tmin, tmax = (min(datees), max(datees)) if datees else (0, 9e18)
    connues: set[bytes] = set()
    for s in coffre.shards(famille, tmin, tmax):
        connues |= coffre.empreintes(s, famille)
    vues: set[bytes] = set()
    presentes = absentes = 0
    for _, cle, rec in lignes:
        if cle in connues:
            presentes += 1
        elif cle not in vues:
            absentes += 1
            vues.add(cle)
            if sortie is not None:
                sortie.write(json.dumps({**rec, "prouve_absent_du_coffre": {"fichier": rel,
                                         "outil": "tools/prouver_scellement.py"}},
                                        ensure_ascii=False, separators=(",", ":")) + "\n")
    st = chemin.stat()
    return {"fichier": rel, **bilan, "presentes": presentes, "absentes": absentes, "famille": famille,
            "taille": st.st_size, "mtime_ns": st.st_mtime_ns}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--plan", action="store_true")
    p.add_argument("--now-ms", type=int, default=0)
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    now_ms = a.now_ms or int(time.time() * 1000)
    from hl_observer.datasets import recensement_donnees as R

    rapport = R.recenser(root, max_listes=1_000_000)
    a_prouver = rapport["listes"].get("A_PROUVER", [])
    print(f"  {len(a_prouver)} fichier(s) a prouver", flush=True)
    coffre = Coffre(root)
    preuves = {}
    try:
        preuves = json.loads((root / PREUVES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    rubans: list[str] = []
    resultats = []
    for x in sorted(a_prouver, key=lambda x: x["fichier"]):
        rel = x["fichier"]
        fam = (x.get("famille") or [None])[0]
        if fam is None:
            continue
        sortie = part = nom = None
        if not a.plan:
            tronc = Path(rel).name.split(".")[0]
            import re
            tronc = re.sub(r"_\d{10,}$", "", tronc)
            nom = f"{tronc}_{zlib.crc32(rel.encode()):010d}{int(time.time() * 1000) % 10**13:013d}.jsonl.gz"
            detecte = C.detecter_famille(nom)
            if detecte is None or detecte[0] != fam:
                print(f"  [!] {rel} : le ruban {nom} ne serait pas reconnu ({detecte}) : fichier laissé à prouver")
                continue
            part = root / HISTOIRE / (nom + ".part")
            part.parent.mkdir(parents=True, exist_ok=True)
            sortie = gzip.open(part, "wt", encoding="utf-8", newline="\n")
        try:
            r = prouver_un(root, rel, fam, coffre, now_ms, sortie)
        finally:
            if sortie is not None:
                sortie.close()
        resultats.append(r)
        print(f"  {rel[:90]:<90} presentes {r['presentes']:>9,} absentes {r['absentes']:>9,}", flush=True)
        if not a.plan:
            if r["absentes"]:
                os.replace(part, root / HISTOIRE / nom)
                rubans.append(nom)
            elif part is not None and part.exists():
                part.unlink()
            preuves[rel] = {"taille": r.get("taille"), "mtime_ns": r.get("mtime_ns"), "famille": fam,
                            "presentes": r["presentes"], "absentes_versees": r["absentes"],
                            "ruban_des_absentes": nom if r["absentes"] else None, "prouve_ms": now_ms}
    code = 0
    if rubans:
        cmd = [sys.executable, str(RACINE / "tools" / "sceller_coffre_local.py"), "--root", str(root)]
        for n in rubans:
            cmd += ["--nom", n]
        code = subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False).returncode
    if not a.plan:
        tmp = (root / PREUVES).with_name(PREUVES.name + ".tmp")
        tmp.write_text(json.dumps(preuves, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, root / PREUVES)
    tot = Counter()
    for r in resultats:
        tot["presentes"] += r["presentes"]
        tot["absentes"] += r["absentes"]
    print(f"  bilan : {len(resultats)} fichier(s), {tot['presentes']:,} lignes deja au coffre, {tot['absentes']:,} absentes"
          + ("" if a.plan else f" (versees dans {len(rubans)} ruban(s))"), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
