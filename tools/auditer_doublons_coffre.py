r"""Mesure EXACTE des lignes en double dans tout le coffre certifié (lecture seule).

    tools\python\python.exe tools\auditer_doublons_coffre.py                      toutes les familles
    tools\python\python.exe tools\auditer_doublons_coffre.py --famille fills_backfill

23/11/2026 -- POURQUOI. Le certificateur dédoublonne PAR PASSAGE : il ne compare une ligne qu'à celles du même
passage. Un ruban réécrit au lieu d'être allongé (``vault_episodes.jsonl`` a été relu depuis son début 40 fois
sans jamais être remis à zéro), une rotation au préfixe non reconnu ou une preuve qui fait la course avec la campagne
redéposent donc des lignes que le coffre a déjà. ``DOUBLONS_CONNUS.json`` n'en consignait que ceux que j'avais vus.
Ici, chaque ligne de chaque shard de l'index est mesurée.

Règle : deux lignes sont en double quand leur IDENTITÉ (``coffre_certifie.identite``, celle du certificateur) est la
même. La copie gardée est celle du lot le plus ancien (``batch_id``, puis chemin du shard, puis rang de la ligne) ;
toutes les autres sont des doublons. Rien n'est modifié : le rapport ``runtime/coffre_certifie/DOUBLONS_MESURES.json``
dit, shard par shard, quelles lignes (par rang) sont en double. ``tools/dedoublonner_coffre.py`` s'en sert.

Méthode (mémoire bornée, 370 M lignes) : 1) chaque shard -> un fichier d'empreintes (blake2b-16 de l'identité, une par
ligne, dans l'ordre) ; 2) par famille et par tranche du premier octet d'empreinte, tri lexicographique (numpy) ;
une empreinte vue deux fois désigne un doublon.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

INDEX = Path("runtime") / "coffre_certifie" / "LOCAL_INDEX.json"
RAPPORT = Path("runtime") / "coffre_certifie" / "DOUBLONS_MESURES.json"
LIGNES_PAR_TRANCHE = 16_000_000          # ~0,5 Go par tranche de tri


def empreinte(record: Any, famille: str) -> bytes:
    from hl_observer.datasets import coffre_certifie as C

    return hashlib.blake2b(repr(C.identite(record, famille)).encode("utf-8"), digest_size=16).digest()


def _empreintes_d_un_shard(root: str, rel: str, famille: str, sortie: str) -> dict[str, Any]:
    """Une empreinte de 16 octets par ligne, dans l'ordre des lignes. Une ligne illisible reçoit une empreinte unique
    (elle n'est jamais déclarée doublon)."""
    import numpy as np

    morceaux = bytearray()
    lues = illisibles = 0
    try:
        with gzip.open(Path(root) / rel, "rb") as g:
            for brut in g:
                lues += 1
                try:
                    morceaux += empreinte(json.loads(brut), famille)
                except (ValueError, TypeError, AttributeError, KeyError):
                    illisibles += 1
                    morceaux += hashlib.blake2b(b"\x00illisible\x00" + rel.encode() + str(lues).encode(),
                                                digest_size=16).digest()
    except (OSError, EOFError) as exc:
        return {"shard": rel, "erreur": f"{type(exc).__name__}: {exc}", "lignes": lues}
    tableau = np.frombuffer(bytes(morceaux), dtype=np.uint8).reshape(-1, 16)
    tmp = sortie + ".tmp.npy"
    np.save(tmp, tableau)
    os.replace(tmp, sortie)
    return {"shard": rel, "lignes": lues, "illisibles": illisibles}


def _contenu_d_un_shard(root: str, rel: str, sortie: str) -> dict[str, Any]:
    """Empreinte du CONTENU (8 octets, octets bruts de la ligne sans sa fin) de chaque ligne, dans l'ordre.

    23/11/2026 : deux lignes de même identité n'ont pas toujours le même contenu -- 21 % des fills retirés à la
    première passe portaient des champs (``closedPnl``, ``fee``, ``pos_avant``...) que la copie gardée n'avait pas ;
    une bougie est vue à plusieurs états ; un même fill est reçu par deux transports. Seul un contenu identique À
    L'OCTET est un doublon sans perte. Deux sérialisations différentes du même enregistrement sont donc gardées
    (prudence : on préfère garder un doublon que perdre une information)."""
    import numpy as np

    valeurs = []
    try:
        with gzip.open(Path(root) / rel, "rb") as g:
            for brut in g:
                valeurs.append(int.from_bytes(hashlib.blake2b(brut.rstrip(b"\r\n"), digest_size=8).digest(), "little"))
    except (OSError, EOFError) as exc:
        return {"shard": rel, "erreur": f"{type(exc).__name__}: {exc}"}
    tmp = sortie + ".tmp.npy"
    np.save(tmp, np.array(valeurs, dtype=np.uint64))
    os.replace(tmp, sortie)
    return {"shard": rel, "lignes": len(valeurs)}


def _fichier_contenu(sortie: str) -> str:
    return sortie[: -len(".npy")] + ".contenu.npy"


def _plages(rangs) -> list[list[int]]:
    """Rangs triés -> plages [début, fin) contiguës."""
    plages: list[list[int]] = []
    for r in rangs:
        r = int(r)
        if plages and plages[-1][1] == r:
            plages[-1][1] = r + 1
        else:
            plages.append([r, r + 1])
    return plages


def doublons_d_une_famille(fichiers: list[tuple[int, str]], total: int,
                           versions: dict[str, int] | None = None) -> dict[int, list[int]]:
    """``fichiers`` = [(rang du shard, fichier d'empreintes d'identité)] dans l'ordre de priorité.

    -> {rang: [lignes en double]}. Une ligne est en double quand une ligne de rang plus petit a la même IDENTITÉ et
    le même CONTENU (octets). Même identité mais contenu différent : gardée, comptée dans ``versions["lignes"]``."""
    import numpy as np

    tranches = max(1, -(-total // LIGNES_PAR_TRANCHE))
    bornes = [round(256 * k / tranches) for k in range(tranches + 1)]
    resultat: dict[int, list[int]] = {}
    for k in range(tranches):
        bas, haut = bornes[k], bornes[k + 1]
        hi, lo, ct, rangs, lignes = [], [], [], [], []
        for rang, chemin in fichiers:
            e = np.load(chemin, mmap_mode="r")
            if not len(e):
                continue
            idx = np.nonzero((e[:, 0] >= bas) & (e[:, 0] < haut))[0]
            if not len(idx):
                continue
            c = np.load(_fichier_contenu(chemin), mmap_mode="r")
            if len(c) != len(e):
                raise ValueError(f"empreintes incoherentes pour {chemin} : {len(e)} identites, {len(c)} contenus")
            d = np.ascontiguousarray(e[idx]).view(np.uint64).reshape(-1, 2)
            hi.append(d[:, 0].copy())
            lo.append(d[:, 1].copy())
            ct.append(np.asarray(c[idx], dtype=np.uint64))
            rangs.append(np.full(len(idx), rang, dtype=np.uint32))
            lignes.append(idx.astype(np.uint32))
        if not hi:
            continue
        hi_, lo_, ct_, rg_, li_ = (np.concatenate(x) for x in (hi, lo, ct, rangs, lignes))
        del hi, lo, ct, rangs, lignes
        ordre = np.lexsort((li_, rg_, ct_, lo_, hi_))
        hs, ls, cs = hi_[ordre], lo_[ordre], ct_[ordre]
        meme_identite = np.zeros(len(ordre), dtype=bool)
        meme_identite[1:] = (hs[1:] == hs[:-1]) & (ls[1:] == ls[:-1])
        double = meme_identite.copy()
        double[1:] &= cs[1:] == cs[:-1]
        if versions is not None:
            versions["lignes"] = versions.get("lignes", 0) + int((meme_identite & ~double).sum())
        for rang, ligne in zip(rg_[ordre][double].tolist(), li_[ordre][double].tolist()):
            resultat.setdefault(rang, []).append(ligne)
        del hi_, lo_, ct_, rg_, li_, ordre, hs, ls, cs, double, meme_identite
    for v in resultat.values():
        v.sort()
    return resultat


def mesurer(root: Path, travail: Path, familles: set[str] | None = None, ouvriers: int = 4,
            log=print) -> dict[str, Any]:
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    shards = [s for s in index.get("shards", []) if isinstance(s, dict) and s.get("shard") and s.get("famille")
              and (familles is None or s["famille"] in familles)]
    shards.sort(key=lambda s: (str(s.get("batch_id") or ""), str(s["shard"])))
    travail.mkdir(parents=True, exist_ok=True)
    taches = []
    for rang, s in enumerate(shards):
        nom = hashlib.blake2b(s["shard"].encode(), digest_size=10).hexdigest()
        sortie = travail / s["famille"] / f"{nom}.npy"
        sortie.parent.mkdir(parents=True, exist_ok=True)
        taches.append((rang, s, str(sortie)))
    erreurs: list[dict[str, Any]] = []
    for genre, fonction, fichier in (("identites", _empreintes_d_un_shard, lambda x: x),
                                     ("contenus", _contenu_d_un_shard, _fichier_contenu)):
        a_faire = [t for t in taches if not Path(fichier(t[2])).exists()]
        log(f"  {len(shards):,} shards ; {genre} : {len(a_faire):,} a lire ({len(taches) - len(a_faire):,} deja mesures)")
        t0 = time.time()

        def lancer(s, sortie, _f=fonction, _x=fichier):
            if _f is _empreintes_d_un_shard:
                return (_f, (str(root), s["shard"], s["famille"], sortie))
            return (_f, (str(root), s["shard"], _x(sortie)))

        if ouvriers <= 1:                                   # en ligne (tests, petits coffres)
            for _, s, sortie in a_faire:
                f, args = lancer(s, sortie)
                r = f(*args)
                if r.get("erreur"):
                    erreurs.append(r)
        else:
            with ProcessPoolExecutor(max_workers=ouvriers) as pool:
                futurs = {}
                for _, s, sortie in a_faire:
                    f, args = lancer(s, sortie)
                    futurs[pool.submit(f, *args)] = s
                for n, fut in enumerate(as_completed(futurs), 1):
                    r = fut.result()
                    if r.get("erreur"):
                        erreurs.append(r)
                    if n % 500 == 0 or n == len(futurs):
                        log(f"    lus {n:,}/{len(futurs):,} ({time.time() - t0:.0f} s)")
    import numpy as np

    par_famille: dict[str, list[tuple[int, str, dict]]] = {}
    for rang, s, sortie in taches:
        if Path(sortie).exists() and Path(_fichier_contenu(sortie)).exists():
            par_famille.setdefault(s["famille"], []).append((rang, sortie, s))
    rapport_shards: list[dict[str, Any]] = []
    bilan: dict[str, Any] = {}
    ecarts: list[dict[str, Any]] = []
    for fam, liste in sorted(par_famille.items()):
        tailles = {rang: int(np.load(chemin, mmap_mode="r").shape[0]) for rang, chemin, _ in liste}
        total = sum(tailles.values())
        t1 = time.time()
        versions: dict[str, int] = {}
        doubles = doublons_d_une_famille([(r, c) for r, c, _ in liste], total, versions)
        n_doubles = sum(len(v) for v in doubles.values())
        bilan[fam] = {"lignes": total, "doublons": n_doubles, "shards": len(liste), "shards_touches": len(doubles),
                      "part": round(n_doubles / total, 6) if total else 0.0,
                      "meme_identite_contenu_different": versions.get("lignes", 0)}
        log(f"  {fam:<18} {total:>12,} lignes  {n_doubles:>11,} en double ({100 * n_doubles / max(1, total):.2f} %) "
            f"dans {len(doubles):,} shard(s) ; {versions.get('lignes', 0):>10,} meme identite / autre contenu (gardees)"
            f"  [{time.time() - t1:.0f} s]")
        for rang, chemin, s in liste:
            if s.get("deposes") is not None and int(s["deposes"]) != tailles[rang]:
                ecarts.append({"shard": s["shard"], "deposes_index": s["deposes"], "lignes_lues": tailles[rang]})
            if rang in doubles:
                rapport_shards.append({"shard": s["shard"], "famille": fam, "batch_id": s.get("batch_id"),
                                       "lignes": tailles[rang], "doublons": len(doubles[rang]),
                                       "lignes_en_double": _plages(doubles[rang])})
    rapport = {
        "schema": "hypersmart.coffre_certifie.doublons_mesures.v1", "genere_ms": int(time.time() * 1000),
        "regle": "doublon = meme identite du certificateur (coffre_certifie.identite) ET meme contenu a l'octet ; la "
                 "copie gardee est celle du lot le plus ancien (batch_id, puis chemin du shard, puis rang de ligne) ; "
                 "meme identite mais autre contenu = gardee (versions, receptions multiples) ; rangs comptes depuis 0",
        "outil": "tools/auditer_doublons_coffre.py", "familles_mesurees": sorted(bilan),
        "bilan": bilan, "total_lignes": sum(b["lignes"] for b in bilan.values()),
        "total_doublons": sum(b["doublons"] for b in bilan.values()),
        "shards": rapport_shards, "shards_illisibles": erreurs, "ecarts_index": ecarts,
    }
    return rapport


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--famille", action="append", help="limite a cette famille (repetable)")
    p.add_argument("--travail", default="", help="dossier des empreintes (defaut : runtime/coffre_certifie/_audit_doublons)")
    p.add_argument("--ouvriers", type=int, default=4)
    p.add_argument("--rapport", default="", help="chemin du rapport (defaut : runtime/coffre_certifie/DOUBLONS_MESURES.json)")
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    travail = Path(a.travail) if a.travail else root / "runtime" / "coffre_certifie" / "_audit_doublons"
    rapport = mesurer(root, travail, set(a.famille) if a.famille else None, a.ouvriers)
    sortie = Path(a.rapport) if a.rapport else root / RAPPORT
    if a.famille and sortie.exists() and not a.rapport:
        # mesure partielle : elle remplace les familles mesurées et garde les autres
        ancien = json.loads(sortie.read_text(encoding="utf-8"))
        garde = [s for s in ancien.get("shards", []) if s.get("famille") not in rapport["familles_mesurees"]]
        bilan = {k: v for k, v in (ancien.get("bilan") or {}).items() if k not in rapport["familles_mesurees"]}
        bilan.update(rapport["bilan"])
        rapport["shards"] = garde + rapport["shards"]
        rapport["bilan"] = bilan
        rapport["familles_mesurees"] = sorted(bilan)
        rapport["total_lignes"] = sum(b["lignes"] for b in bilan.values())
        rapport["total_doublons"] = sum(b["doublons"] for b in bilan.values())
    tmp = sortie.with_name(sortie.name + ".tmp")
    tmp.write_text(json.dumps(rapport, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, sortie)
    print(f"  TOTAL : {rapport['total_doublons']:,} lignes en double sur {rapport['total_lignes']:,} "
          f"-> {sortie.relative_to(root) if sortie.is_relative_to(root) else sortie}", flush=True)
    if rapport["shards_illisibles"]:
        print(f"  [!] {len(rapport['shards_illisibles'])} shard(s) illisible(s)", flush=True)
    if rapport["ecarts_index"]:
        print(f"  [!] {len(rapport['ecarts_index'])} shard(s) dont le nombre de lignes differe de l'index", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
