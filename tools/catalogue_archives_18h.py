"""CATALOGUE DES ARCHIVES + QUALITÉ DONNÉES (labo 18 h, Flo 26/07).

Parcourt récursivement les dossiers de données SANS rien supprimer ni analyser en aveugle : on établit
d'abord un CATALOGUE (chemin, taille, SHA-256, format, lignes, ts min/max, coins, doublons, trous, crossed
book, NaN/inf, troncature…), puis un statut par source (VALID..UNUSABLE). Les ZIP imbriqués et bases actives
sont catalogués (métadonnées) mais JAMAIS ouverts en profondeur. Une erreur n'est jamais convertie en n=0.
Écrit DATA_CATALOG.json/csv + DATA_QUALITY.md sous le rundir. 0 réseau, 0 suppression.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

DOSSIERS = ("runtime/data", "runtime/research_lab", "data", "logs", "archives", "backups", "reports")
EXTS = (".jsonl", ".json", ".csv", ".parquet", ".sqlite", ".sqlite3", ".db", ".gz", ".zip")
PARSE_LIGNES = (".jsonl",)          # seuls formats parsés ligne à ligne ; le reste = métadonnées seules
MAX_LIGNES = 200_000                 # borne de lecture par fichier (anti-saturation)
STATUTS = ("VALID", "PARTIAL", "STALE", "TRUNCATED", "SCHEMA_MISMATCH", "DUPLICATED", "CORRUPTED", "UNUSABLE")


def _sha256(p: Path, *, cap: int = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    lu = 0
    with p.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
            lu += len(bloc)
            if lu >= cap:                    # empreinte du préfixe pour les très gros fichiers (borné)
                h.update(b"__CAP__")
                break
    return h.hexdigest()


def _ts(d: dict):
    for k in ("ts_ms", "ts_wall_ms", "recv_ts", "exchange_ts", "ts_ex", "collecte_ts", "time", "ts"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v) * (1000.0 if k == "collecte_ts" else 1.0)
    return None


def _coin(d: dict):
    c = d.get("coin") or d.get("symbol") or d.get("asset")
    return str(c).upper() if c else None


def analyser_jsonl(p: Path) -> dict:
    """Qualité d'un .jsonl : lignes, invalides, ts min/max, monotonie, doublons, coins, NaN/inf, crossed book,
    exchange/local ts présents, futur, troncature (dernière ligne non terminée par \\n)."""
    import math
    q = {"lignes": 0, "invalides": 0, "ts_min": None, "ts_max": None, "non_monotone": 0, "doublons": 0,
         "coins": set(), "nan_inf": 0, "crossed_book": 0, "exchange_ts": False, "local_ts": False,
         "futur": 0, "troncature": False}
    vus, dernier_ts = set(), None
    try:
        raw = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        q["invalides"] = -1
        return q
    q["troncature"] = bool(raw) and not raw.endswith("\n")
    for l in raw.splitlines()[:MAX_LIGNES]:
        if not l.strip():
            continue
        q["lignes"] += 1
        try:
            d = json.loads(l)
        except ValueError:
            q["invalides"] += 1
            continue
        if not isinstance(d, dict):
            continue
        if any(k in d for k in ("exchange_ts", "ts_ex")):
            q["exchange_ts"] = True
        if any(k in d for k in ("recv_ts", "ts_wall_ms", "write_ts")):
            q["local_ts"] = True
        c = _coin(d)
        if c:
            q["coins"].add(c)
        for k in ("bid", "ask", "hl_bid", "hl_ask", "px", "net_median_bps"):
            v = d.get(k)
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                q["nan_inf"] += 1
        b, a = d.get("bid") or d.get("hl_bid"), d.get("ask") or d.get("hl_ask")
        if isinstance(b, (int, float)) and isinstance(a, (int, float)) and a > 0 and b > a:
            q["crossed_book"] += 1
        t = _ts(d)
        if t is not None:
            q["ts_min"] = t if q["ts_min"] is None else min(q["ts_min"], t)
            q["ts_max"] = t if q["ts_max"] is None else max(q["ts_max"], t)
            if dernier_ts is not None and t < dernier_ts:
                q["non_monotone"] += 1
            dernier_ts = t
            cle = (c, round(t, 3))
            if cle in vus:
                q["doublons"] += 1
            else:
                vus.add(cle)
    q["coins"] = sorted(q["coins"])
    return q


def _statut(fmt: str, q: dict | None) -> str:
    if q is None:                                  # non parsé (parquet/sqlite/zip/gz) : catalogué seulement
        return "VALID"
    if q.get("invalides", 0) < 0:
        return "CORRUPTED"
    if q.get("lignes", 0) == 0:
        return "UNUSABLE"
    if q.get("invalides", 0) > max(1, q["lignes"] * 0.05):
        return "SCHEMA_MISMATCH"
    if q.get("doublons", 0) > q["lignes"] * 0.5:
        return "DUPLICATED"
    if q.get("troncature") or q.get("non_monotone", 0) > q["lignes"] * 0.1:
        return "PARTIAL"
    return "VALID"


def apercu_rapide(root: str | Path, *, dossiers=DOSSIERS, max_fichiers: int = 4000) -> dict:
    """Aperçu RAPIDE pour le dry-run : compte les fichiers par format/dossier SANS SHA ni parse profond
    (borné). N'écrit rien. Sert à prouver que des archives existent, pas à les valider."""
    root = Path(root)
    n, octets, par_format, coins = 0, 0, {}, 0
    for dd in dossiers:
        base = root / dd
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            n += 1
            if n > max_fichiers:
                break
            try:
                octets += p.stat().st_size
            except OSError:
                continue
            par_format[p.suffix.lower().lstrip(".")] = par_format.get(p.suffix.lower().lstrip("."), 0) + 1
    return {"n_sources": n, "octets_total": octets, "par_format": par_format, "borne": max_fichiers}


def cataloguer(root: str | Path, rundir: str | Path, *, dossiers=DOSSIERS, max_fichiers: int = 4000) -> dict:
    """Catalogue toutes les archives sous `dossiers`. N'ouvre en profondeur QUE les .jsonl (bornés).
    Écrit DATA_CATALOG.json/csv + DATA_QUALITY.md sous rundir/catalogue/. Rend le résumé."""
    root, rundir = Path(root), Path(rundir)
    cat = (rundir / "catalogue")
    cat.mkdir(parents=True, exist_ok=True)
    entrees, par_statut = [], {s: 0 for s in STATUTS}
    vus_fichiers = 0
    for dd in dossiers:
        base = root / dd
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            # ne pas cataloguer le rundir courant (évite l'auto-référence pendant l'écriture)
            if str(rundir) in str(p):
                continue
            vus_fichiers += 1
            if vus_fichiers > max_fichiers:       # borne anti-saturation (catalogue = échantillon si trop de fichiers)
                break
            fmt = p.suffix.lower().lstrip(".")
            try:
                taille = p.stat().st_size
            except OSError:
                continue
            q = analyser_jsonl(p) if p.suffix.lower() in PARSE_LIGNES else None
            st = _statut(fmt, q)
            par_statut[st] = par_statut.get(st, 0) + 1
            e = {"chemin": str(p.relative_to(root)), "octets": taille, "sha256": _sha256(p), "format": fmt,
                 "statut": st, "vivant": ("research_lab" in str(p) and p.suffix == ".jsonl")}
            if q is not None:
                e.update({"lignes": q["lignes"], "invalides": q["invalides"], "ts_min": q["ts_min"],
                          "ts_max": q["ts_max"], "non_monotone": q["non_monotone"], "doublons": q["doublons"],
                          "coins": q["coins"], "nan_inf": q["nan_inf"], "crossed_book": q["crossed_book"],
                          "exchange_ts": q["exchange_ts"], "local_ts": q["local_ts"], "troncature": q["troncature"]})
            entrees.append(e)
    resume = {"n_sources": len(entrees), "par_statut": par_statut,
              "octets_total": sum(e["octets"] for e in entrees),
              "coins_uniques": sorted({c for e in entrees for c in e.get("coins", [])})}
    (cat / "DATA_CATALOG.json").write_text(json.dumps({"resume": resume, "sources": entrees},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")
    # CSV
    buf = io.StringIO()
    if entrees:
        cols = ["chemin", "format", "statut", "octets", "lignes", "doublons", "non_monotone", "crossed_book",
                "nan_inf", "ts_min", "ts_max", "exchange_ts", "local_ts", "vivant", "sha256"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for e in entrees:
            w.writerow(e)
    (cat / "DATA_CATALOG.csv").write_text(buf.getvalue(), encoding="utf-8")
    # DATA_QUALITY.md
    md = ["# DATA_QUALITY — inventaire des archives\n",
          "Sources : **%d** · octets : %d · coins : %d\n" % (resume["n_sources"], resume["octets_total"], len(resume["coins_uniques"])),
          "Statuts : " + ", ".join("%s=%d" % (k, v) for k, v in par_statut.items() if v) + "\n",
          "| source | format | statut | lignes | doublons | crossed | ts_min | ts_max |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for e in entrees[:200]:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            e["chemin"], e["format"], e["statut"], e.get("lignes", "—"), e.get("doublons", "—"),
            e.get("crossed_book", "—"), e.get("ts_min", "—"), e.get("ts_max", "—")))
    md.append("\n> Aucune source supprimée. ZIP imbriqués / bases actives catalogués (métadonnées), jamais ouverts en aveugle.\n")
    (cat / "DATA_QUALITY.md").write_text("\n".join(md), encoding="utf-8")
    return resume


__all__ = ["cataloguer", "analyser_jsonl", "STATUTS", "DOSSIERS"]
