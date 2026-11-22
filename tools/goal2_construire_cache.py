r"""Cache de recherche de la mission 2 : fills de leaders, bougies 1 h, funding — en colonnes.

POURQUOI. Le coffre certifie stocke des `.jsonl.gz` par shard : parfait pour la preuve, lent
pour chercher. Chaque hypothese de la chasse a l'alpha relit les memes 7 mois ; les decompresser
a chaque essai couterait des minutes et des gigaoctets. On les range donc UNE fois en parquet,
colonnes typees, dedoublonnees.

CE QUE CE CACHE N'EST PAS. Une source de verite. Il derive EXCLUSIVEMENT des shards du coffre
LOCAL certifie (`runtime/coffre_certifie/local/shards`), il enregistre la liste et l'empreinte de
ce qu'il a lu (`MANIFESTE.json`), et il se reconstruit a l'identique. Il vit sous
`runtime/research_lab/data/` : un dossier `data/` est ignore par Git, donc il ne part pas au push.

SOBRIETE MEMOIRE. Un shard a la fois, ecrit par groupe de lignes ; jamais le corpus entier en
dictionnaires Python. La machine doit rester disponible pour le reste.

IDENTITE NATIVE DES COINS : jamais de majuscules (`kPEPE`, `xyz:XYZ100`).

LECTURE SEULE sur le coffre. PAPER.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import pathlib
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

import goal2_commun as G  # bornes des segments : une seule source

RACINE = pathlib.Path(__file__).resolve().parents[1]
COFFRE = pathlib.Path("runtime/coffre_certifie/local/shards")
CACHE = pathlib.Path("runtime/research_lab/data/goal2_cache")


def _f(valeur) -> float | None:
    """Un flottant fini, ou None. Jamais un zero de repli : absent n'est pas nul."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        x = float(valeur)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _ecrire(lignes: list[dict], schema: pa.Schema, ecrivain: pq.ParquetWriter) -> None:
    if lignes:
        ecrivain.write_table(pa.Table.from_pylist(lignes, schema=schema))


SCHEMA_FILLS = pa.schema([
    ("vault", pa.string()), ("ts_ms", pa.int64()), ("coin", pa.string()),
    ("px", pa.float64()), ("sz", pa.float64()), ("signe", pa.int8()),
    ("dir", pa.string()), ("start_position", pa.float64()),
    ("crossed", pa.bool_()), ("fee", pa.float64()), ("closed_pnl", pa.float64()),
    ("tid", pa.int64()),
])
SCHEMA_BOUGIES = pa.schema([
    ("coin", pa.string()), ("t_ms", pa.int64()), ("o", pa.float64()), ("h", pa.float64()),
    ("l", pa.float64()), ("c", pa.float64()), ("v", pa.float64()),
])
SCHEMA_FUNDING = pa.schema([
    ("coin", pa.string()), ("ts_ms", pa.int64()), ("funding", pa.float64()),
    ("premium", pa.float64()),
])


def _ligne_fill(o: dict) -> dict | None:
    vault, coin, ts = o.get("vault"), o.get("coin"), o.get("ts_ms")
    px, sz, signe = _f(o.get("px")), _f(o.get("sz")), o.get("signe")
    if not vault or not coin or not isinstance(ts, int) or px is None or sz is None:
        return None
    if signe not in (1, -1) or px <= 0 or sz <= 0:
        return None
    crossed = o.get("crossed")
    tid = o.get("tid")
    return {
        "vault": str(vault).lower(), "ts_ms": ts, "coin": str(coin), "px": px, "sz": sz,
        "signe": int(signe), "dir": str(o.get("dir") or ""),
        "start_position": _f(o.get("start_position")),
        "crossed": crossed if isinstance(crossed, bool) else None,
        "fee": _f(o.get("fee")), "closed_pnl": _f(o.get("closedPnl")),
        "tid": tid if isinstance(tid, int) and not isinstance(tid, bool) else None,
    }


def _ligne_bougie(o: dict) -> dict | None:
    coin, t = o.get("coin"), o.get("t_ms")
    c = _f(o.get("c"))
    if not coin or not isinstance(t, int) or c is None or c <= 0:
        return None
    return {"coin": str(coin), "t_ms": t, "o": _f(o.get("o")), "h": _f(o.get("h")),
            "l": _f(o.get("l")), "c": c, "v": _f(o.get("v"))}


def _ligne_funding(o: dict) -> dict | None:
    coin, t = o.get("coin"), o.get("ts_ms")
    f = _f(o.get("funding"))
    if not coin or not isinstance(t, int) or f is None:
        return None
    return {"coin": str(coin), "ts_ms": t, "funding": f, "premium": _f(o.get("premium"))}


def convertir(racine: pathlib.Path, famille: str, motif: str, sortie: pathlib.Path,
              schema: pa.Schema, lire_ligne, *, depuis_ms: int = 0, avant_ms: int = 0) -> dict:
    """Un shard a la fois -> parquet. Rend le compte et l'empreinte de ce qui a ete lu."""
    shards = sorted((racine / COFFRE / famille).glob(f"*{motif}*.jsonl.gz"))
    sortie.parent.mkdir(parents=True, exist_ok=True)
    provisoire = sortie.with_suffix(".parquet.partial")
    lues = gardees = illisibles = 0
    empreinte = hashlib.sha256()
    with pq.ParquetWriter(provisoire, schema, compression="zstd") as ecrivain:
        for shard in shards:
            empreinte.update(shard.name.encode("utf-8"))
            empreinte.update(str(shard.stat().st_size).encode("ascii"))
            lot: list[dict] = []
            with gzip.open(shard, "rt", encoding="utf-8", errors="replace") as flux:
                for brut in flux:
                    lues += 1
                    try:
                        o = json.loads(brut)
                    except ValueError:
                        illisibles += 1
                        continue
                    ligne = lire_ligne(o) if isinstance(o, dict) else None
                    if ligne is None:
                        illisibles += 1
                        continue
                    instant = int(ligne.get("ts_ms") or ligne.get("t_ms") or 0)
                    if depuis_ms and instant < depuis_ms:
                        continue
                    if avant_ms and instant >= avant_ms:      # rien au-dela : pas meme dans le cache
                        continue
                    lot.append(ligne)
                    if len(lot) >= 200_000:
                        _ecrire(lot, schema, ecrivain)
                        gardees += len(lot)
                        lot = []
            _ecrire(lot, schema, ecrivain)
            gardees += len(lot)
    provisoire.replace(sortie)
    return {"famille": famille, "motif": motif, "shards": len(shards), "lignes_lues": lues,
            "lignes_gardees": gardees, "illisibles_ou_refusees": illisibles,
            "empreinte_des_shards": empreinte.hexdigest(), "sortie": sortie.as_posix()}


def dedoublonner(chemin: pathlib.Path, clefs: list[str], tri: list[str]) -> dict:
    """Retire les doublons inter-shards (un meme fill rattrape deux fois). Compte ce qui part."""
    import pandas as pd

    df = pd.read_parquet(chemin)
    avant = len(df)
    df = df.drop_duplicates(subset=clefs, keep="first").sort_values(tri, kind="stable")
    df.to_parquet(chemin, compression="zstd", index=False)
    return {"avant": avant, "apres": len(df), "doublons_retires": avant - len(df)}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--funding-depuis-ms", type=int, default=1_775_000_000_000,
                   help="borne basse du funding garde (defaut : debut avril 2026)")
    p.add_argument("--seulement", default="",
                   help="tables a (re)construire, separees par des virgules ; les autres sont gardees")
    args = p.parse_args(argv)
    seulement = {s for s in args.seulement.split(",") if s}
    racine = pathlib.Path(args.racine).resolve()
    cache = racine / CACHE
    debut = time.time()
    manifeste: dict = {"genere_ms": int(debut * 1000), "source": COFFRE.as_posix(), "tables": {}}
    if seulement and (cache / "MANIFESTE.json").is_file():       # reconstruction partielle : on garde le reste
        manifeste["tables"] = json.loads((cache / "MANIFESTE.json").read_text(encoding="utf-8")).get("tables", {})

    plan = [
        ("fills", "fills_backfill", "leader_fills_backfill", SCHEMA_FILLS, _ligne_fill, 0, 0,
         ["vault", "tid", "ts_ms", "coin", "px", "sz", "signe"], ["ts_ms", "vault"]),
        ("candles_1h", "candle", "candles_1h", SCHEMA_BOUGIES, _ligne_bougie, 0, 0,
         ["coin", "t_ms"], ["coin", "t_ms"]),
        # 5 min : du debut du segment d'execution au VERROU de l'OOS final, pas une bougie de plus
        ("candles_5m", "candle", "candles_5m", SCHEMA_BOUGIES, _ligne_bougie,
         G.SEGMENTS["execution"][0] - G.JOUR_MS, G.SEGMENTS["oos_final"][0],
         ["coin", "t_ms"], ["coin", "t_ms"]),
        ("funding_1h", "funding_history", "funding_1h", SCHEMA_FUNDING, _ligne_funding,
         args.funding_depuis_ms, 0, ["coin", "ts_ms"], ["coin", "ts_ms"]),
    ]
    for nom, famille, motif, schema, lecteur, depuis, avant, clefs, tri in plan:
        if seulement and nom not in seulement:
            continue
        t0 = time.time()
        bilan = convertir(racine, famille, motif, cache / f"{nom}.parquet", schema, lecteur,
                          depuis_ms=depuis, avant_ms=avant)
        bilan["dedoublonnage"] = dedoublonner(cache / f"{nom}.parquet", clefs, tri)
        bilan["secondes"] = round(time.time() - t0, 1)
        manifeste["tables"][nom] = bilan
        print(f"  {nom:<11} {bilan['shards']:>4} shards | lues {bilan['lignes_lues']:>10,}"
              f" | gardees {bilan['dedoublonnage']['apres']:>10,}"
              f" | doublons {bilan['dedoublonnage']['doublons_retires']:>9,}"
              f" | refusees {bilan['illisibles_ou_refusees']:>8,} | {bilan['secondes']} s")
    (cache / "MANIFESTE.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"  cache : {(cache).as_posix()}  ({round(time.time() - debut)} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
