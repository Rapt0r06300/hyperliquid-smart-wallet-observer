"""[LAB α] INVENTAIRE + LECTEURS multi-format pour le laboratoire de recherche d'alpha. Découvre les données
réellement présentes dans les dossiers cibles, vérifie ce qui est LISIBLE et CONSOMMABLE (JSONL/JSON/CSV/SQLite/
ZIP/GZIP/LZ4), et les convertit en BUNDLES pour le chemin canonique unique (feed_adapter → MegaCablage) via
runner._row_to_bundle (aucun parseur dupliqué). LZ4 est honnête-optionnel : si la lib manque → statut BLOQUÉ,
jamais une lecture inventée. Pur/lecture seule ; 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sqlite3
import zipfile
from pathlib import Path
from typing import Any, Iterator

from hl_observer.mega_cablage.runner import _row_to_bundle

CONSOMMABLES = {".jsonl", ".ndjson", ".json", ".csv", ".tsv", ".sqlite", ".sqlite3", ".db",
                ".zip", ".gz", ".gzip", ".lz4"}

DOSSIERS_CIBLES = ("runtime/replay", "runtime/data", "runtime/data/market_ticks", "research_lab/data",
                   "archives", "logs", "logs/logs a envoyer", "logs/logs à envoyer")


def classer_format(ext: str) -> str:
    ext = ext.lower()
    if ext in (".jsonl", ".ndjson"):
        return "JSONL"
    if ext == ".json":
        return "JSON"
    if ext in (".csv", ".tsv"):
        return "CSV"
    if ext in (".sqlite", ".sqlite3", ".db"):
        return "SQLITE"
    if ext == ".zip":
        return "ZIP"
    if ext in (".gz", ".gzip"):
        return "GZIP"
    if ext == ".lz4":
        return "LZ4"
    return "AUTRE"


def _hash_fichier(chemin: Path, taille: int, *, max_octets: int = 1_048_576) -> str:
    """Hash déterministe : taille + jusqu'à max_octets de contenu (suffit à distinguer, borne le coût I/O)."""
    h = hashlib.sha256()
    h.update(str(taille).encode())
    try:
        with open(chemin, "rb") as fh:
            h.update(fh.read(max_octets))
    except OSError:
        return "UNREADABLE"
    return h.hexdigest()[:16]


def _lignes_texte(fh: Any) -> Iterator[dict[str, Any]]:
    for ligne in fh:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            row = json.loads(ligne)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(row, dict):
            yield row


def _lignes_csv(fh: Any, *, delim: str) -> Iterator[dict[str, Any]]:
    for row in csv.DictReader(fh, delimiter=delim):
        out: dict[str, Any] = {}
        for k, v in row.items():
            if k is None:
                continue
            try:
                out[k] = float(v) if v not in (None, "") and str(v).replace(".", "", 1).lstrip("-").isdigit() else v
            except (TypeError, ValueError):
                out[k] = v
        yield out


def _lignes_json(chemin: Path) -> Iterator[dict[str, Any]]:
    try:
        obj = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(obj, list):
        for r in obj:
            if isinstance(r, dict):
                yield r
    elif isinstance(obj, dict):
        for v in obj.values():                     # dict {liste} : on déroule la première liste de dicts
            if isinstance(v, list) and v and isinstance(v[0], dict):
                for r in v:
                    if isinstance(r, dict):
                        yield r
                return
        yield obj


def _lignes_sqlite(chemin: Path, *, max_lignes: int = 200_000) -> Iterator[dict[str, Any]]:
    con = None
    for essai in ("uri", "plain"):                 # read-only si possible, robuste Windows/Linux
        try:
            if essai == "uri":
                con = sqlite3.connect(Path(chemin).resolve().as_uri() + "?mode=ro", uri=True)
            else:
                con = sqlite3.connect(str(chemin))
            break
        except (sqlite3.Error, ValueError):
            con = None
    if con is None:
        return
    try:
        con.row_factory = sqlite3.Row
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        n = 0
        for t in tables:
            try:
                for row in con.execute('SELECT * FROM "%s"' % t):
                    yield dict(row)
                    n += 1
                    if n >= max_lignes:
                        return
            except sqlite3.Error:
                continue
    finally:
        con.close()


def lire_lignes(chemin: str | Path) -> Iterator[dict[str, Any]]:
    """Itère les lignes/rows d'un fichier consommable selon son extension. LZ4 sans lib → LabFormatBloque."""
    p = Path(chemin)
    ext = p.suffix.lower()
    if ext in (".jsonl", ".ndjson"):
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            yield from _lignes_texte(fh)
    elif ext == ".json":
        yield from _lignes_json(p)
    elif ext in (".csv", ".tsv"):
        with open(p, "r", encoding="utf-8", errors="replace", newline="") as fh:
            yield from _lignes_csv(fh, delim="\t" if ext == ".tsv" else ",")
    elif ext in (".sqlite", ".sqlite3", ".db"):
        yield from _lignes_sqlite(p)
    elif ext in (".gz", ".gzip"):
        interne = p.stem
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
            if interne.endswith(".csv") or interne.endswith(".tsv"):
                yield from _lignes_csv(fh, delim="\t" if interne.endswith(".tsv") else ",")
            else:
                yield from _lignes_texte(fh)
    elif ext == ".zip":
        with zipfile.ZipFile(p) as zf:
            for nom in zf.namelist():
                if nom.endswith("/"):
                    continue
                with zf.open(nom) as raw:
                    texte = (l.decode("utf-8", "replace") for l in raw)
                    if nom.endswith(".csv") or nom.endswith(".tsv"):
                        yield from _lignes_csv(texte, delim="\t" if nom.endswith(".tsv") else ",")
                    else:
                        yield from _lignes_texte(texte)
    elif ext == ".lz4":
        try:
            import lz4.frame as lz4frame
        except ImportError as exc:
            raise LabFormatBloque("LZ4 non disponible (lib lz4 absente)") from exc
        with lz4frame.open(p, "rt", encoding="utf-8", errors="replace") as fh:
            yield from _lignes_texte(fh)


class LabFormatBloque(RuntimeError):
    """Format présent mais non consommable ici (ex. LZ4 sans lib installée) → statut BLOQUÉ honnête."""


def _lisibilite(chemin: Path, fmt: str) -> tuple[bool, str]:
    """Tente de lire une première ligne/row. Rend (lisible, raison). Aucun contenu inventé."""
    if fmt == "LZ4":
        try:
            import lz4.frame  # noqa: F401
        except ImportError:
            return False, "BLOQUE_LZ4_LIB_ABSENTE"
    try:
        for _ in lire_lignes(chemin):
            return True, "OK"
        return True, "VIDE"
    except LabFormatBloque as exc:
        return False, str(exc)
    except (OSError, sqlite3.Error, zipfile.BadZipFile, gzip.BadGzipFile, UnicodeDecodeError) as exc:
        return False, "ERREUR_%s" % type(exc).__name__


def inventorier(racine: str | Path, *, dossiers: tuple[str, ...] = DOSSIERS_CIBLES,
                max_fichiers: int = 50_000, profondeur_max: int = 8) -> dict[str, Any]:
    """Découvre les fichiers CONSOMMABLES dans les dossiers cibles (récursif borné). Pour chaque : format, taille,
    lisibilité, hash. Rend un manifeste {dossiers, fichiers, total_octets, total_fichiers, lisibles, bloques}."""
    racine = Path(racine)
    dossiers_rap: list[dict[str, Any]] = []
    fichiers: list[dict[str, Any]] = []
    total_octets = 0
    n = 0
    for rel in dossiers:
        base = racine / rel
        if not base.is_dir():
            dossiers_rap.append({"dossier": rel, "present": False})
            continue
        d_octets = 0
        d_formats: dict[str, int] = {}
        for cur, _sous, noms in os.walk(base):
            prof = len(Path(cur).relative_to(base).parts)
            if prof > profondeur_max:
                continue
            for nom in noms:
                ext = os.path.splitext(nom)[1].lower()
                if ext not in CONSOMMABLES:
                    continue
                p = Path(cur) / nom
                try:
                    taille = p.stat().st_size
                except OSError:
                    continue
                fmt = classer_format(ext)
                lisible, raison = _lisibilite(p, fmt)
                fichiers.append({"chemin": str(p), "rel": str(p.relative_to(racine)), "dossier": rel,
                                 "format": fmt, "octets": taille, "lisible": lisible, "raison": raison,
                                 "hash": _hash_fichier(p, taille)})
                d_octets += taille
                total_octets += taille
                d_formats[fmt] = d_formats.get(fmt, 0) + 1
                n += 1
                if n >= max_fichiers:
                    break
            if n >= max_fichiers:
                break
        dossiers_rap.append({"dossier": rel, "present": True, "n_fichiers": d_formats and sum(d_formats.values()) or 0,
                             "octets": d_octets, "formats": d_formats})
    lisibles = sum(1 for f in fichiers if f["lisible"])
    bloques = sum(1 for f in fichiers if not f["lisible"])
    return {"racine": str(racine), "dossiers": dossiers_rap, "fichiers": fichiers,
            "total_fichiers": len(fichiers), "total_octets": total_octets,
            "lisibles": lisibles, "bloques": bloques}


def bundles_depuis_fichier(chemin: str | Path, *, max_lignes: int = 500_000) -> list[dict[str, Any]]:
    """Lit un fichier consommable → bundles pour le chemin canonique (via runner._row_to_bundle). Borne le nombre
    de lignes pour la mémoire. Aucune donnée fabriquée : un format bloqué lève LabFormatBloque."""
    bundles: list[dict[str, Any]] = []
    for i, row in enumerate(lire_lignes(chemin)):
        if i >= max_lignes:
            break
        bundles.append(_row_to_bundle(row))
    return bundles


__all__ = ["CONSOMMABLES", "DOSSIERS_CIBLES", "classer_format", "lire_lignes", "inventorier",
           "bundles_depuis_fichier", "LabFormatBloque"]
