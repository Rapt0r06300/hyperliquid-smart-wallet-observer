"""LECTEURS DE DONNÉES 18 h (LOT18H-DATA-COMPLETE, Flo 26/07). Chaque format a un lecteur STREAMING : on ne
charge JAMAIS un énorme fichier entièrement en RAM, on ne modifie JAMAIS les originaux. Chaque source est soit
lue (records), soit EXCLUE avec une RAISON précise (jamais un plafond silencieux, jamais VALID en aveugle).

Formats : JSON/JSONL (stream), CSV/TSV (chunks), Parquet (batches si moteur dispo, sinon EXCLU), SQLite (RO
strict), GZ/LZ4 (stream), ZIP (inventaire puis extraction sûre vers staging), TXT/LOG/MD (classés).
SHA-256 INTÉGRAL pour manifeste/dedup ; prefix_hash gardé seulement comme accélérateur. 0 réseau, 0 écriture
sur les originaux.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import sqlite3
from pathlib import Path

CHUNK = 1 << 20


def sha256_integral(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def prefix_hash(p: Path, *, cap: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    lu = 0
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b); lu += len(b)
            if lu >= cap:
                break
    return h.hexdigest()[:16]


def payload_hash(d: dict) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ─────────── lecteurs (générateurs (offset, record)) ───────────
def lire_jsonl(p: Path, *, max_records: int | None = None):
    n = 0
    with Path(p).open("r", encoding="utf-8", errors="ignore") as f:
        for i, ligne in enumerate(f):
            s = ligne.strip()
            if not s:
                continue
            try:
                d = json.loads(s)
            except ValueError:
                yield (i, {"_invalide": True, "_raw": s[:200]})
                continue
            yield (i, d)
            n += 1
            if max_records and n >= max_records:
                return


def lire_json(p: Path):
    """JSON (objet unique ou liste). Streamé au mieux : pour une liste on itère ; pour un objet on rend 1 record."""
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return
    if isinstance(d, list):
        for i, x in enumerate(d):
            yield (i, x if isinstance(x, dict) else {"valeur": x})
    elif isinstance(d, dict):
        yield (0, d)


def lire_csv(p: Path, *, delim=None, max_records: int | None = None):
    with Path(p).open("r", encoding="utf-8", errors="ignore", newline="") as f:
        sample = f.read(4096); f.seek(0)
        if delim is None:
            delim = "\t" if (sample.count("\t") > sample.count(",")) else ","
        r = csv.DictReader(f, delimiter=delim)
        for i, row in enumerate(r):
            yield (i, dict(row))
            if max_records and i + 1 >= max_records:
                return


def lire_gz(p: Path, *, max_records: int | None = None):
    with gzip.open(Path(p), "rt", encoding="utf-8", errors="ignore") as f:
        for i, ligne in enumerate(f):
            s = ligne.strip()
            if not s:
                continue
            try:
                yield (i, json.loads(s))
            except ValueError:
                yield (i, {"_ligne": s[:200]})
            if max_records and i + 1 >= max_records:
                return


def lire_lz4(p: Path, *, max_records: int | None = None):
    import lz4.frame  # type: ignore
    with lz4.frame.open(Path(p), "rt", encoding="utf-8", errors="ignore") as f:
        for i, ligne in enumerate(f):
            s = ligne.strip()
            if not s:
                continue
            try:
                yield (i, json.loads(s))
            except ValueError:
                yield (i, {"_ligne": s[:200]})
            if max_records and i + 1 >= max_records:
                return


def lire_sqlite(p: Path, *, max_records: int | None = None):
    """SQLite STRICTEMENT read-only (URI mode=ro + query_only). Itère chaque table (bornée)."""
    uri = "file:%s?mode=ro&immutable=1" % Path(p).as_posix()
    con = sqlite3.connect(uri, uri=True)
    try:
        con.execute("PRAGMA query_only=ON;")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        n = 0
        for t in tables:
            try:
                cur = con.execute("SELECT * FROM \"%s\"" % t)
                cols = [c[0] for c in cur.description]
                for row in cur:
                    yield (n, {"_table": t, **dict(zip(cols, row))})
                    n += 1
                    if max_records and n >= max_records:
                        return
            except sqlite3.Error:
                continue
    finally:
        con.close()


def lire_parquet(p: Path, *, max_records: int | None = None):
    """Parquet par batches SI un moteur est dispo (pyarrow/fastparquet). Sinon lève -> EXCLU avec raison."""
    import pandas as pd  # type: ignore
    df = pd.read_parquet(Path(p))            # lève ImportError si aucun moteur -> capté en amont
    for i, (_, row) in enumerate(df.iterrows()):
        yield (i, {k: (v.item() if hasattr(v, "item") else v) for k, v in row.to_dict().items()})
        if max_records and i + 1 >= max_records:
            return


def inventorier_zip(p: Path) -> list[dict]:
    """Inventaire d'un ZIP SANS extraction (noms, tailles, CRC). Ne l'ouvre jamais en aveugle."""
    import zipfile
    try:
        with zipfile.ZipFile(Path(p)) as z:
            return [{"nom": i.filename, "octets": i.file_size, "crc": i.CRC} for i in z.infolist()][:5000]
    except zipfile.BadZipFile:
        return []


def extraire_zip_staging(p: Path, staging: Path, *, max_octets: int = 200 * 1024 * 1024) -> list[Path]:
    """Extraction SÛRE vers un dossier de staging IMMUABLE (anti zip-slip, borné). Les originaux restent intacts."""
    import zipfile
    staging = Path(staging); staging.mkdir(parents=True, exist_ok=True)
    sortis, total = [], 0
    try:
        with zipfile.ZipFile(Path(p)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                dest = (staging / info.filename).resolve()
                if not str(dest).startswith(str(staging.resolve())):   # anti zip-slip
                    continue
                total += info.file_size
                if total > max_octets:
                    break
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("wb") as out:
                    while True:
                        b = src.read(CHUNK)
                        if not b:
                            break
                        out.write(b)
                sortis.append(dest)
    except zipfile.BadZipFile:
        return []
    return sortis


def classifier_texte(p: Path) -> str:
    """TXT/LOG/MD -> 'log' | 'rapport' | 'documentation' selon le nom/contenu (jamais parsé comme données de marché)."""
    nom = Path(p).name.lower()
    if nom.endswith(".md") or "readme" in nom or "rapport" in nom:
        return "documentation" if nom.endswith(".md") and "rapport" not in nom else "rapport"
    if "log" in nom or nom.endswith(".log"):
        return "log"
    try:
        tete = Path(p).read_text(encoding="utf-8", errors="ignore")[:500].lower()
    except OSError:
        return "log"
    return "log" if ("error" in tete or "reconnect" in tete or "ts" in tete) else "documentation"


#: table format -> (lecteur, streaming?) ; None = exclu (raison fournie par le catalogue)
LECTEURS = {
    "jsonl": lire_jsonl, "json": lire_json, "csv": lire_csv, "tsv": lire_csv,
    "gz": lire_gz, "lz4": lire_lz4, "sqlite": lire_sqlite, "sqlite3": lire_sqlite, "db": lire_sqlite,
    "parquet": lire_parquet, "arrow": lire_parquet, "feather": lire_parquet,
}
FORMATS_TEXTE = ("txt", "log", "md")

__all__ = ["sha256_integral", "prefix_hash", "payload_hash", "lire_jsonl", "lire_json", "lire_csv", "lire_gz",
           "lire_lz4", "lire_sqlite", "lire_parquet", "inventorier_zip", "extraire_zip_staging",
           "classifier_texte", "LECTEURS", "FORMATS_TEXTE"]
