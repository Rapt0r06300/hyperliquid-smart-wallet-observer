r"""Retire du coffre que lit le labo les lignes en double MESURÉES, sans rien supprimer ni réécrire.

    tools\python\python.exe tools\auditer_doublons_coffre.py        1) mesure (DOUBLONS_MESURES.json)
    tools\python\python.exe tools\dedoublonner_coffre.py --plan     2) dit ce qui serait fait
    tools\python\python.exe tools\dedoublonner_coffre.py            3) le fait ; le verrou du certificateur n'est tenu
                                                                       que le temps d'échanger les entrées d'index
    tools\python\python.exe tools\dedoublonner_coffre.py --annuler <lot>   défait un lot (originaux remis dans l'index)

23/11/2026. Un shard du coffre est immuable : il n'est jamais modifié ni effacé. Pour chaque shard qui contient des
lignes en double (selon ``DOUBLONS_MESURES.json`` : même identité ET même contenu à l'octet qu'une ligne d'un lot plus
ancien) :
- ses autres lignes sont copiées À L'OCTET PRÈS dans un nouveau shard ``<lot>__<ruban>__dd<marque>.jsonl.gz`` ;
- dans ``LOCAL_INDEX.json`` (ce que lit le labo), ce nouveau shard prend sa place ; l'entrée d'origine passe, complète,
  dans ``shards_remplaces`` avec ``remplace_par``, ``retire_par_lot`` et le nombre de doublons. Le fichier d'origine
  reste sur le disque.
- un shard entièrement en double n'a pas de remplaçant : il passe seul dans ``shards_remplaces``.
Chaque nouveau shard est relu et vérifié avant que l'index ne change ; un shard dont le nombre de lignes ne correspond
plus à la mesure, ou dont l'entrée d'index a changé entre la construction et l'échange, n'est pas touché.

``--annuler`` existe parce que la première passe (23/11, 20 h) retirait par IDENTITÉ seule : 21 % des fills retirés
portaient des champs (``closedPnl``, ``fee``, ``pos_avant``...) que la copie gardée n'avait pas.
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
    """Écrit le shard des lignes gardées et rend son entrée d'index (``remplace_par=None`` s'il n'en reste aucune).
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
    autres = {k: v for k, v in entree.items() if k not in CHAMPS_CALCULES}
    nouvelle = {
        "batch_id": lot, "famille": famille, "shard": rel,
        "sha256": hashlib.sha256(cible.read_bytes()).hexdigest(), "octets": cible.stat().st_size,
        "deposes": len(gardees), "coins": [k for k, _ in sorted(coins.items(), key=lambda kv: -kv[1])],
        "jours": sorted(jours), "ts_min_ms": ts_min, "ts_max_ms": ts_max, **autres,
        "derive_de": entree["shard"], "lignes_retirees_en_double": retirees,
    }
    return {"remplace_par": nouvelle, "retirees": retirees, "gardees": len(gardees)}


def echanger(index: dict[str, Any], construits: dict[str, dict[str, Any]], lot: str, genere_ms: int,
             bilan: dict[str, Any]) -> list[dict[str, Any]]:
    """Sous le verrou : remplace dans ``index`` chaque entrée construite dont l'entrée d'index n'a pas changé."""
    remplaces = index.setdefault("shards_remplaces", [])
    nouveaux: list[dict[str, Any]] = []
    manifeste: list[dict[str, Any]] = []
    for entree in index.get("shards", []):
        c = construits.get(entree.get("shard"))
        if c is None:
            nouveaux.append(entree)
            continue
        if entree.get("sha256") != c["entree"].get("sha256") or entree.get("deposes") != c["entree"].get("deposes"):
            bilan["ignores_entree_changee"].append(entree["shard"])
            nouveaux.append(entree)
            continue
        r = c["resultat"]
        fam = entree["famille"]
        pf = bilan["par_famille"].setdefault(fam, {"shards": 0, "retirees": 0})
        pf["shards"] += 1
        pf["retirees"] += r["retirees"]
        bilan["lignes_retirees"] += r["retirees"]
        bilan["lignes_gardees"] += r["gardees"]
        remplaces.append({**entree, "remplace_par": r["remplace_par"]["shard"] if r["remplace_par"] else None,
                          "lignes_en_double": r["retirees"], "retire_de_l_index_ms": genere_ms,
                          "retire_par_lot": lot,
                          "motif": "lignes identiques (identite ET contenu) deja au coffre dans un lot plus ancien "
                                   "(DOUBLONS_MESURES.json) ; fichier conserve sur le disque"})
        if r["remplace_par"]:
            nouveaux.append(r["remplace_par"])
            bilan["remplaces"] += 1
        else:
            bilan["sans_remplacant"] += 1
        manifeste.append({"famille": fam, "derive_de": entree["shard"],
                          "shard": r["remplace_par"]["shard"] if r["remplace_par"] else None,
                          "deposes": r["gardees"], "lignes_retirees_en_double": r["retirees"]})
    index["shards"] = nouveaux
    return manifeste


def annuler(index: dict[str, Any], lot: str, motif: str, maintenant_ms: int) -> dict[str, int]:
    """Défait le lot ``lot`` : ses remplaçants sortent de l'index (vers ``shards_remplaces``, marqués annulés), les
    originaux qu'il avait retirés y reviennent à leur place. Rien n'est effacé."""
    lot_ms = next((l.get("genere_ms") for l in index.get("lots", []) if l.get("batch_id") == lot), None)
    remplaces = index.setdefault("shards_remplaces", [])

    def du_lot(o: dict[str, Any]) -> bool:
        return o.get("retire_par_lot") == lot or (
            o.get("retire_par_lot") is None and lot_ms is not None and o.get("retire_de_l_index_ms") == lot_ms)

    originaux = [o for o in remplaces if du_lot(o) and not o.get("annule_ms")]
    par_remplacant = {o["remplace_par"]: o for o in originaux if o.get("remplace_par")}
    sans = [o for o in originaux if not o.get("remplace_par")]
    nouveaux, sortis, remis = [], [], set()
    for e in index.get("shards", []):
        if e.get("batch_id") == lot and e.get("shard") in par_remplacant:
            sortis.append({**e, "annule_ms": maintenant_ms, "motif": motif})
            nouveaux.append(_restaure(par_remplacant[e["shard"]]))
            remis.add(e["shard"])
        else:
            nouveaux.append(e)
    # un original dont le remplaçant n'est plus dans l'index revient quand même : jamais d'original perdu de vue
    nouveaux += [_restaure(o) for o in sans] + [_restaure(o) for r, o in par_remplacant.items() if r not in remis]
    index["shards"] = nouveaux
    gardes = [o for o in remplaces if o not in originaux]
    index["shards_remplaces"] = gardes + sortis
    index.setdefault("historique_dedoublonnage", []).append(
        {"annulation_de": lot, "ms": maintenant_ms, "motif": motif, "originaux_remis": len(originaux),
         "remplacants_sortis": len(sortis), "originaux": [o["shard"] for o in originaux]})
    return {"originaux_remis": len(originaux), "remplacants_sortis": len(sortis)}


def _restaure(o: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in o.items() if k not in ("remplace_par", "lignes_en_double", "retire_de_l_index_ms",
                                                     "retire_par_lot", "motif")}


def _prendre_verrou(root: Path, attente_s: float) -> bool:
    from hl_observer.ops import verrou_pid

    debut = time.time()
    while True:
        obtenu, mot = verrou_pid.prendre(root / VERROU, quoi="le dedoublonnage du coffre")
        if obtenu:
            return True
        if time.time() - debut > attente_s:
            print(f"  [!] {mot} : abandon apres {attente_s:.0f} s, rien n'a change", flush=True)
            return False
        time.sleep(15)


def _journal(root: Path, bilan: dict[str, Any]) -> None:
    historique: Any = []
    try:
        historique = json.loads((root / RAPPORT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    historique = historique if isinstance(historique, list) else [historique]
    historique.append(bilan)
    _ecrire_atomique(root / RAPPORT, historique)


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--plan", action="store_true")
    p.add_argument("--annuler", default="", help="lot de dedoublonnage a defaire")
    p.add_argument("--motif", default="annulation demandee")
    p.add_argument("--famille", action="append", help="limite le dedoublonnage a cette famille (repetable)")
    p.add_argument("--attente-verrou-s", type=float, default=3600.0)
    a = p.parse_args(argv)
    root = Path(a.racine).resolve()
    from hl_observer.ops import verrou_pid
    import sceller_coffre_local as S

    if a.annuler:
        if not _prendre_verrou(root, a.attente_verrou_s):
            return 3
        try:
            index = json.loads((root / INDEX).read_text(encoding="utf-8"))
            ms = int(time.time() * 1000)
            r = annuler(index, a.annuler, a.motif, ms)
            if r["originaux_remis"]:
                index.setdefault("lots", []).append({"batch_id": f"{a.annuler}_annule", "genere_ms": ms,
                                                     "mode": "annulation_dedoublonnage", "total": r})
                _ecrire_atomique(root / INDEX, index)
                S._maj_coffre_index(root, root / COFFRE)
            _journal(root, {"annulation_de": a.annuler, "genere_ms": ms, "motif": a.motif, **r})
        finally:
            verrou_pid.rendre(root / VERROU)
        print(f"  lot {a.annuler} annule : {r['originaux_remis']:,} original(aux) remis dans l'index, "
              f"{r['remplacants_sortis']:,} remplacant(s) sorti(s) (gardes sur le disque)", flush=True)
        return 0

    mesures = json.loads((root / MESURES).read_text(encoding="utf-8"))
    a_traiter = {m["shard"]: m for m in mesures.get("shards", []) if m.get("doublons")
                 and (not a.famille or m.get("famille") in a.famille)}
    print(f"  mesure du {time.strftime('%d/%m %H:%M', time.localtime(mesures['genere_ms'] / 1000))} : "
          f"{len(a_traiter):,} shard(s), {sum(m['doublons'] for m in a_traiter.values()):,} ligne(s) en double",
          flush=True)
    if a.plan:
        for fam, b in sorted((mesures.get("bilan") or {}).items()):
            if b.get("doublons") and (not a.famille or fam in a.famille):
                print(f"    {fam:<18} {b['doublons']:>12,} / {b['lignes']:>12,} ({100 * b['part']:.2f} %)")
        return 0
    lot = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
    bilan: dict[str, Any] = {"lot": lot, "mesure_ms": mesures["genere_ms"], "remplaces": 0, "sans_remplacant": 0,
                             "lignes_retirees": 0, "lignes_gardees": 0, "ignores_mesure_perimee": [],
                             "ignores_entree_changee": [], "par_famille": {}}
    # 1) HORS VERROU : les remplaçants sont de nouveaux fichiers, l'index n'est pas touché
    index = json.loads((root / INDEX).read_text(encoding="utf-8"))
    construits: dict[str, dict[str, Any]] = {}
    t0 = time.time()
    for n, entree in enumerate(e for e in index.get("shards", []) if e.get("shard") in a_traiter):
        try:
            construits[entree["shard"]] = {"entree": dict(entree), "resultat": construire_remplacant(
                root, entree, a_traiter[entree["shard"]], lot)}
        except (ValueError, OSError) as exc:
            bilan["ignores_mesure_perimee"].append({"shard": entree["shard"], "motif": str(exc)})
        if (n + 1) % 200 == 0:
            print(f"    remplacants construits : {n + 1:,}/{len(a_traiter):,} ({time.time() - t0:.0f} s)", flush=True)
    # 2) SOUS VERROU, bref : échange des entrées
    if not _prendre_verrou(root, a.attente_verrou_s):
        return 3
    try:
        index = json.loads((root / INDEX).read_text(encoding="utf-8"))   # relu SOUS le verrou : la dernière version
        bilan["genere_ms"] = int(time.time() * 1000)
        manifeste_fichiers = echanger(index, construits, lot, bilan["genere_ms"], bilan)
        if manifeste_fichiers:
            index.setdefault("lots", []).append({"batch_id": lot, "genere_ms": bilan["genere_ms"], "mode":
                                                 "dedoublonnage", "total": {"deposes": bilan["lignes_gardees"],
                                                 "doublons": bilan["lignes_retirees"]}})
            _ecrire_atomique(root / COFFRE / "local" / "manifests" / f"{lot}.json", {
                "schema": "hypersmart.coffre_certifie.local.v1", "batch_id": lot, "tier": "LOCAL",
                "mode": "dedoublonnage", "genere_ms": bilan["genere_ms"], "outil": "tools/dedoublonner_coffre.py",
                "regle": mesures.get("regle"), "fichiers": manifeste_fichiers})
            _ecrire_atomique(root / INDEX, index)
            S._maj_coffre_index(root, root / COFFRE)
        _journal(root, bilan)
    finally:
        verrou_pid.rendre(root / VERROU)
    print(f"  {bilan['remplaces']:,} shard(s) remplace(s) par leurs lignes gardees, {bilan['sans_remplacant']:,} "
          f"entierement en double ; {bilan['lignes_retirees']:,} ligne(s) en double retiree(s) de l'index, "
          f"{bilan['lignes_gardees']:,} gardee(s) ; ignores : {len(bilan['ignores_mesure_perimee'])} (mesure "
          f"perimee), {len(bilan['ignores_entree_changee'])} (entree changee)", flush=True)
    for fam, pf in sorted(bilan["par_famille"].items()):
        print(f"    {fam:<18} {pf['retirees']:>12,} retirees dans {pf['shards']:,} shard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
