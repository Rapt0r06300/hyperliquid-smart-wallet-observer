r"""Retire du coffre que lit le labo les lignes en double MESURÉES, sans rien supprimer ni réécrire.

    tools\python\python.exe tools\auditer_doublons_coffre.py        1) mesure (DOUBLONS_MESURES.json)
    tools\python\python.exe tools\dedoublonner_coffre.py --plan     2) dit ce qui serait fait
    tools\python\python.exe tools\dedoublonner_coffre.py            3) le fait, sous le verrou du certificateur

23/11/2026. Un shard du coffre est immuable : il n'est jamais modifié ni effacé. Pour chaque shard qui contient des
lignes en double (selon ``DOUBLONS_MESURES.json`` : même identité qu'une ligne d'un lot plus ancien) :
- ses lignes UNIQUES sont copiées À L'OCTET PRÈS dans un nouveau shard ``<lot>__<ruban>__dd<marque>.jsonl.gz`` ;
- dans ``LOCAL_INDEX.json`` (ce que lit le labo), ce nouveau shard prend sa place ; l'entrée d'origine passe, complète,
  dans ``shards_remplaces`` avec ``remplace_par`` et le nombre de doublons. Le fichier d'origine reste sur le disque.
- un shard entièrement en double n'a pas de remplaçant : il passe seul dans ``shards_remplaces``.
Chaque nouveau shard est relu et vérifié (nombre de lignes, empreinte) avant que l'index ne change. Un shard dont le
nombre de lignes ne correspond plus à la mesure n'est pas touché (mesure périmée).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

COFFRE = Path("runtime") / "coffre_certifie"
INDEX = COFFRE / "LOCAL_INDEX.json"
MESURES = COFFRE / "DOUBLONS_MESURES.json"
RAPPORT = COFFRE / "DEDOUBLONNAGE.json"
VERROU = Path("runtime") / "data" / "coffre_certificateur.lock"
CHAMPS_CALCULES = ("batch_id", "shard", "sha256", "octets", "deposes", "coins", "jours", "ts_min_ms", "ts_max_ms")


def _ecrire_atomique(chemin: Path, donnees: Any, indent: int | None = 2) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + f".{os.getpid()}.partial")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=indent), encoding="utf-8")
    for essai in range(20):
        try:
            os.replace(tmp, chemin)
            return
        except PermissionError:          # Windows : un lecteur tient le fichier un instant (WinError 5)
            time.sleep(0.25 * (essai + 1))
    os.replace(tmp, chemin)


def _masque(n: int, plages: list[list[int]]) -> bytearray:
    m = bytearray(n)
    for a, b in plages:
        m[a:b] = b"\x01" * (b - a)
    return m


def nom_du_remplacant(shard: str, lot: str) -> str:
    p = Path(shard)
    reste = p.name.split("__", 1)[1] if "__" in p.name else p.name
    reste = reste[: -len(".jsonl.gz")] if reste.endswith(".jsonl.gz") else reste
    marque = hashlib.blake2b(shard.encode("utf-8"), digest_size=4).hexdigest()   # deux originaux de même nom
    return (p.parent / f"{lot}__{reste}__dd{marque}.jsonl.gz").as_posix()


def construire_remplacant(root: Path, entree: dict[str, Any], mesure: dict[str, Any], lot: str) -> dict[str, Any]:
    """Écrit le shard des lignes uniques et rend son entrée d'index (ou ``remplace_par=None`` s'il n'en reste aucune).
    Lève ValueError si la mesure ne correspond plus au fichier."""
    import sceller_coffre_local as S

    famille = entree["famille"]
    with gzip.open(root / entree["shard"], "rb") as g:
        lignes = g.read().splitlines(keepends=True)
    if len(lignes) != int(mesure["lignes"]):
        raise ValueError(f"mesure perimee : {len(lignes)} lignes lues, {mesure['lignes']} mesurees")
    double = _masque(len(lignes), mesure["lignes_en_double"])
    gardees = [b for b, d in zip(lignes, double) if not d]
    retirees = len(lignes) - len(gardees)
    if retirees != int(mesure["doublons"]):
        raise ValueError(f"plages incoherentes : {retirees} != {mesure['doublons']}")
    if not gardees:
        return {"remplace_par": None, "retirees": retirees, "gardees": 0}
    coins: dict[str, int] = {}
    jours: dict[str, int] = {}
    ts_min = ts_max = None
    for brut in gardees:
        rec = json.loads(brut)
        c = str(rec.get("coin") or "?")
        coins[c] = coins.get(c, 0) + 1
        t = S._ts_primaire(rec, famille)
        j = S._jour_utc(t)
        jours[j] = jours.get(j, 0) + 1
        if isinstance(t, int) and not isinstance(t, bool):
            ts_min = t if ts_min is None else min(ts_min, t)
            ts_max = t if ts_max is None else max(ts_max, t)
    rel = nom_du_remplacant(entree["shard"], lot)
    cible = root / rel
    if gardees[-1][-1:] != b"\n":
        gardees[-1] = gardees[-1] + b"\n"
    tmp = cible.with_name(cible.name + ".partial")
    with gzip.open(tmp, "wb", compresslevel=6) as g:
        g.writelines(gardees)
    with gzip.open(tmp, "rb") as g:
        relu = g.read().splitlines(keepends=True)
    if relu != gardees:
        tmp.unlink()
        raise ValueError("relecture du remplacant differente")
    os.replace(tmp, cible)
    nouvelle = {k: v for k, v in entree.items() if k not in CHAMPS_CALCULES}
    nouvelle = {
        "batch_id": lot, "famille": famille, "shard": rel,
        "sha256": hashlib.sha256(cible.read_bytes()).hexdigest(), "octets": cible.stat().st_size,
        "deposes": len(gardees), "coins": [k for k, _ in sorted(coins.items(), key=lambda kv: -kv[1])],
        "jours": sorted(jours), "ts_min_ms": ts_min, "ts_max_ms": ts_max, **nouvelle,
        "derive_de": entree["shard"], "lignes_retirees_en_double": retirees,
    }
    return {"remplace_par": nouvelle, "retirees": retirees, "gardees": len(gardees)}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--plan", action="store_true")
    p.add_argument("--attente-verrou-s", type=float, default=3600.0)
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    from hl_observer.ops import verrou_pid

    mesures = json.loads((root / MESURES).read_text(encoding="utf-8"))
    a_traiter = {m["shard"]: m for m in mesures.get("shards", []) if m.get("doublons")}
    print(f"  mesure du {time.strftime('%d/%m %H:%M', time.localtime(mesures['genere_ms'] / 1000))} : "
          f"{len(a_traiter):,} shard(s), {sum(m['doublons'] for m in a_traiter.values()):,} ligne(s) en double",
          flush=True)
    if a.plan:
        for fam, b in sorted((mesures.get("bilan") or {}).items()):
            if b.get("doublons"):
                print(f"    {fam:<18} {b['doublons']:>12,} / {b['lignes']:>12,} ({100 * b['part']:.2f} %)")
        return 0
    lot = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
    debut = time.time()
    while True:
        obtenu, mot = verrou_pid.prendre(root / VERROU, quoi="le dedoublonnage du coffre")
        if obtenu:
            break
        if time.time() - debut > a.attente_verrou_s:
            print(f"  [!] {mot} : abandon apres {a.attente_verrou_s:.0f} s, rien n'a change", flush=True)
            return 3
        time.sleep(15)
    try:
        index = json.loads((root / INDEX).read_text(encoding="utf-8"))   # relu SOUS le verrou : la derniere version
        bilan = {"lot": lot, "genere_ms": int(time.time() * 1000), "mesure_ms": mesures["genere_ms"],
                 "remplaces": 0, "sans_remplacant": 0, "lignes_retirees": 0, "lignes_gardees": 0,
                 "ignores_mesure_perimee": [], "absents_de_l_index": 0, "par_famille": {}}
        manifeste_fichiers: list[dict[str, Any]] = []
        nouveaux: list[dict[str, Any]] = []
        remplaces = index.setdefault("shards_remplaces", [])
        for entree in index.get("shards", []):
            m = a_traiter.get(entree.get("shard"))
            if m is None:
                nouveaux.append(entree)
                continue
            try:
                r = construire_remplacant(root, entree, m, lot)
            except (ValueError, OSError) as exc:
                bilan["ignores_mesure_perimee"].append({"shard": entree["shard"], "motif": str(exc)})
                nouveaux.append(entree)
                continue
            fam = entree["famille"]
            pf = bilan["par_famille"].setdefault(fam, {"shards": 0, "retirees": 0})
            pf["shards"] += 1
            pf["retirees"] += r["retirees"]
            bilan["lignes_retirees"] += r["retirees"]
            bilan["lignes_gardees"] += r["gardees"]
            remplaces.append({**entree, "remplace_par": r["remplace_par"]["shard"] if r["remplace_par"] else None,
                              "lignes_en_double": r["retirees"], "retire_de_l_index_ms": bilan["genere_ms"],
                              "motif": "lignes deja au coffre dans un lot plus ancien (DOUBLONS_MESURES.json) ; "
                                       "fichier conserve sur le disque"})
            if r["remplace_par"]:
                nouveaux.append(r["remplace_par"])
                bilan["remplaces"] += 1
            else:
                bilan["sans_remplacant"] += 1
            manifeste_fichiers.append({"famille": fam, "derive_de": entree["shard"],
                                       "shard": r["remplace_par"]["shard"] if r["remplace_par"] else None,
                                       "deposes": r["gardees"], "lignes_retirees_en_double": r["retirees"]})
        bilan["absents_de_l_index"] = len(set(a_traiter) - {e.get("shard") for e in index.get("shards", [])})
        if manifeste_fichiers:
            index["shards"] = nouveaux
            index.setdefault("lots", []).append({"batch_id": lot, "genere_ms": bilan["genere_ms"], "mode":
                                                 "dedoublonnage", "total": {"deposes": bilan["lignes_gardees"],
                                                 "doublons": bilan["lignes_retirees"]}})
            manifeste = {"schema": "hypersmart.coffre_certifie.local.v1", "batch_id": lot, "tier": "LOCAL",
                         "mode": "dedoublonnage", "genere_ms": bilan["genere_ms"],
                         "outil": "tools/dedoublonner_coffre.py",
                         "regle": mesures.get("regle"), "fichiers": manifeste_fichiers}
            _ecrire_atomique(root / COFFRE / "local" / "manifests" / f"{lot}.json", manifeste)
            _ecrire_atomique(root / INDEX, index)
            import sceller_coffre_local as S

            S._maj_coffre_index(root, root / COFFRE)
        historique = []
        try:
            historique = json.loads((root / RAPPORT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        historique = historique if isinstance(historique, list) else [historique]
        historique.append(bilan)
        _ecrire_atomique(root / RAPPORT, historique)
    finally:
        verrou_pid.rendre(root / VERROU)
    print(f"  {bilan['remplaces']:,} shard(s) remplace(s) par leurs lignes uniques, {bilan['sans_remplacant']:,} "
          f"entierement en double ; {bilan['lignes_retirees']:,} ligne(s) en double retiree(s) de l'index, "
          f"{bilan['lignes_gardees']:,} gardee(s) ; {len(bilan['ignores_mesure_perimee'])} ignore(s) (mesure perimee)",
          flush=True)
    for fam, pf in sorted(bilan["par_famille"].items()):
        print(f"    {fam:<18} {pf['retirees']:>12,} retirees dans {pf['shards']:,} shard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
