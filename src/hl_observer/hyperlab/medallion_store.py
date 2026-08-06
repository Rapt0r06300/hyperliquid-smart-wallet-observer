"""[Bloc 29-31 / DATA-115,116,117 / AUD-300,366,367] Persistance medaillon REELLE sur disque.

BRONZE : raw ecrit en JSONL, adresse par le HASH de contenu (fichier part-<sha8>.jsonl) + sidecar
         .sha256 -> immuable (toute alteration change le hash et donc le chemin).
SILVER : schema CANONIQUE ecrit en Parquet PARTITIONNE par venue/date (pyarrow).
GOLD   : features derivees (notionnel = prix*taille) en Parquet + lineage vers le silver.
Un champ manquant reste None (jamais invente). pyarrow requis ; 0 reseau ; deterministe (ts fournis).
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

CHAMPS_SILVER = ("ts", "venue", "symbole", "type", "prix", "taille", "side")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _date_de_ts(ts) -> str:
    """Derive une date YYYY-MM-DD depuis un ts (ms int, s int, ou ISO str). Inconnu -> 'unknown'
    (jamais invente)."""
    if ts is None:
        return "unknown"
    try:
        if isinstance(ts, str):
            s = ts.strip()
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return s[:10]
            ts = float(s)
        v = float(ts)
        if v > 1e12:      # millisecondes
            v = v / 1000.0
        import datetime as _dt
        return _dt.datetime.utcfromtimestamp(v).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"


def ecrire_bronze(root: str, venue: str, records: Sequence[Mapping]) -> dict:
    """Ecrit un lot RAW immuable, adresse par hash de contenu. Reecrire un contenu identique retombe
    sur le meme fichier (immuable) ; un contenu different produit un autre hash/chemin."""
    payload = json.dumps(list(records), sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    h = _sha256_bytes(payload)
    d = os.path.join(root, "bronze", "venue=%s" % venue)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "part-%s.jsonl" % h[:16])
    if not os.path.exists(path):
        with open(path, "wb") as f:
            for r in records:
                f.write(json.dumps(r, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8") + b"\n")
        with open(path + ".sha256", "w", encoding="utf-8") as f:
            f.write(h)
    return {"path": path, "n": len(records), "hash": h, "immutable": True}


def verifier_bronze(path: str) -> bool:
    """Verifie l'integrite : le hash du sidecar doit correspondre au contenu recompose."""
    if not os.path.exists(path) or not os.path.exists(path + ".sha256"):
        return False
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    payload = json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(payload) == open(path + ".sha256", encoding="utf-8").read().strip()


def _table_silver(rows: Sequence[Mapping]) -> pa.Table:
    cols = {c: [] for c in CHAMPS_SILVER}
    cols["date"] = []
    for r in rows:
        for c in CHAMPS_SILVER:
            cols[c].append(r.get(c))
        cols["date"].append(_date_de_ts(r.get("ts")))
    # types stables : prix/taille float, le reste string (sauf ts garde en string pour robustesse)
    arrays = {
        "ts": pa.array([None if v is None else str(v) for v in cols["ts"]], pa.string()),
        "venue": pa.array([None if v is None else str(v) for v in cols["venue"]], pa.string()),
        "symbole": pa.array([None if v is None else str(v) for v in cols["symbole"]], pa.string()),
        "type": pa.array([None if v is None else str(v) for v in cols["type"]], pa.string()),
        "prix": pa.array([_f(v) for v in cols["prix"]], pa.float64()),
        "taille": pa.array([_f(v) for v in cols["taille"]], pa.float64()),
        "side": pa.array([None if v is None else str(v) for v in cols["side"]], pa.string()),
        "date": pa.array(cols["date"], pa.string()),
    }
    return pa.table(arrays)


def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def to_silver_parquet(root: str, venue: str, silver_rows: Sequence[Mapping]) -> dict:
    """Ecrit le silver canonique en Parquet partitionne par venue/date. Retourne chemins + lineage."""
    d = os.path.join(root, "silver")
    os.makedirs(d, exist_ok=True)
    rows = [dict(r, venue=r.get("venue") or venue) for r in silver_rows]
    table = _table_silver(rows)
    pq.write_to_dataset(table, root_path=d, partition_cols=["venue", "date"])
    dates = sorted({_date_de_ts(r.get("ts")) for r in rows})
    return {"dir": d, "n": len(rows), "venue": venue, "dates": dates,
            "lineage": {"etage": "silver", "depuis": "bronze"}}


def to_gold_parquet(root: str, silver_rows: Sequence[Mapping]) -> dict:
    """Features gold (notionnel). Une feature dont l'entree manque reste None (pas de faux 0)."""
    d = os.path.join(root, "gold")
    os.makedirs(d, exist_ok=True)
    ts_c, sym_c, notio_c = [], [], []
    for r in silver_rows:
        px, sz = _f(r.get("prix")), _f(r.get("taille"))
        ts_c.append(None if r.get("ts") is None else str(r.get("ts")))
        sym_c.append(None if r.get("symbole") is None else str(r.get("symbole")))
        notio_c.append((px * sz) if (px is not None and sz is not None) else None)
    table = pa.table({"ts": pa.array(ts_c, pa.string()), "symbole": pa.array(sym_c, pa.string()),
                      "notionnel": pa.array(notio_c, pa.float64())})
    path = os.path.join(d, "gold.parquet")
    pq.write_table(table, path)
    return {"path": path, "n": len(silver_rows), "lineage": {"etage": "gold", "depuis": "silver"}}


def relire_parquet(path_or_dir: str) -> list:
    """Relit un fichier ou un dataset Parquet -> liste de dicts."""
    return pq.read_table(path_or_dir).to_pylist()
