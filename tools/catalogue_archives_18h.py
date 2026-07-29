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
import time

DOSSIERS = ("runtime/data", "runtime/research_lab", "data", "logs", "archives", "backups", "reports")
EXTS = (".jsonl", ".json", ".csv", ".parquet", ".sqlite", ".sqlite3", ".db", ".gz", ".zip")
PARSE_LIGNES = (".jsonl",)          # seuls formats parsés ligne à ligne ; le reste = métadonnées seules
MAX_LIGNES = 200_000                 # borne de lecture par fichier (anti-saturation)
STATUTS = ("VALID", "PARTIAL", "STALE", "TRUNCATED", "SCHEMA_MISMATCH", "DUPLICATED", "CORRUPTED", "UNUSABLE")


def _publier_progression(callback, *, courant: int, total: int | None, detail: str, unite: str) -> None:
    if callback is None:
        return
    try:
        callback(courant=courant, total=total, detail=detail, unite=unite)
    except TypeError:
        callback(courant, total, detail)


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


def cataloguer_complet(
    root: str | Path,
    rundir: str | Path,
    *,
    dossiers=DOSSIERS,
    max_events_par_source: int | None = None,
    sha_integral_max_octets: int = 256 * 1024 * 1024,
    source_offset: int = 0,
    max_sources: int | None = None,
    max_batch_bytes: int | None = None,
    source_paths: list[str] | None = None,
    progress_callback=None,
    stop_event=None,
) -> dict:
    """CATALOGUE COMPLET (LOT18H-DATA-COMPLETE) — AUCUN plafond silencieux de fichiers. Chaque source détectée
    est soit PARSÉE (via le lecteur de son format) et comptée, soit EXCLUE avec une RAISON précise. SHA-256
    INTÉGRAL (prefix_hash seulement au-delà d'un seuil de taille, marqué). Écrit data_source_accounting.csv +
    data_source_exclusions.csv. Accounting : détectées/cataloguées/parsées/inutilisables/exclues/erreurs +
    octets + événements + completeness_ratio."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lecteurs_18h as LEC
    root, rundir = Path(root), Path(rundir)
    (rundir / "catalogue").mkdir(parents=True, exist_ok=True)
    (rundir / "results").mkdir(parents=True, exist_ok=True)
    detectees = catalogue = parsees = inutilisables = exclues = erreurs = 0
    octets = events = 0
    entrees, exclusions = [], []
    candidats: list[Path] = []
    dernier_affichage = 0.0
    if source_paths is not None:
        for raw_path in source_paths:
            p = Path(raw_path)
            candidats.append(p if p.is_absolute() else root / p)
    else:
        for dd in dossiers:
            base = root / dd
            if not base.exists():
                continue
            for p in sorted(base.rglob("*")):
                if stop_event is not None and stop_event.is_set():
                    break
                if not p.is_file() or p.suffix.lower() not in EXTS + tuple("." + e for e in LEC.FORMATS_TEXTE):
                    continue
                if str(rundir) in str(p):
                    continue
                # anti self-ingestion : ne jamais cataloguer les SORTIES du labo (ses propres runs) comme des
                # sources de recherche -> sinon le corpus grossit tout seul a chaque cycle. Les ledgers/logs
                # utiles restent lus par logs_18h ; les donnees marche vivent dans runtime/data.
                if ("continuous" in p.parts) or any("overnight" in part for part in p.parts):
                    continue
                candidats.append(p)
                maintenant = time.monotonic()
                if maintenant - dernier_affichage >= 0.5:
                    _publier_progression(
                        progress_callback,
                        courant=len(candidats),
                        total=None,
                        detail=f"découverte des sources : {len(candidats)} fichier(s) trouvé(s)",
                        unite="sources",
                    )
                    dernier_affichage = maintenant
    total_candidats = len(candidats)
    source_offset = max(0, min(int(source_offset), total_candidats))
    fin = total_candidats if max_sources is None else min(
        total_candidats,
        source_offset + max(1, int(max_sources)),
    )
    lot = candidats[source_offset:fin]
    if max_batch_bytes is not None and lot:
        budget = max(1, int(max_batch_bytes))
        lot_borne: list[Path] = []
        octets_lot = 0
        for p in lot:
            try:
                taille = max(0, int(p.stat().st_size))
            except OSError:
                taille = 0
            if lot_borne and octets_lot + taille > budget:
                break
            lot_borne.append(p)
            octets_lot += taille
        lot = lot_borne or lot[:1]
    fin_lot = source_offset + len(lot)
    _publier_progression(
        progress_callback,
        courant=source_offset,
        total=total_candidats,
        detail=(
            f"inventaire terminé : lot {source_offset + 1 if lot else source_offset}/"
            f"{fin_lot} sur {total_candidats} source(s)"
        ),
        unite="sources",
    )
    for numero_lot, p in enumerate(lot, 1):
            numero_source = source_offset + numero_lot
            if stop_event is not None and stop_event.is_set():
                break
            detectees += 1
            fmt = p.suffix.lower().lstrip(".")
            try:
                taille = p.stat().st_size
            except OSError:
                erreurs += 1
                exclusions.append({"chemin": str(p), "raison": "STAT_ECHEC"})
                continue
            octets += taille
            _publier_progression(
                progress_callback,
                courant=numero_source - 1,
                total=total_candidats,
                detail=(
                    f"source {numero_source}/{total_candidats} : empreinte et lecture de {p.name} "
                    f"({taille / (1024 * 1024):.1f} Mio)"
                ),
                unite="sources",
            )
            sha = LEC.sha256_integral(p) if taille <= sha_integral_max_octets else None
            pref = LEC.prefix_hash(p)
            e = {"chemin": str(p.relative_to(root)), "format": fmt, "octets": taille,
                 "sha256": sha, "sha256_integral": bool(sha), "prefix_hash": pref,
                 "vivant": ("research_lab" in str(p) and p.suffix in (".jsonl", ".json"))}
            # ZIP : inventaire seulement (jamais ouvert en aveugle) -> catalogué, PENDING pour extraction
            if fmt == "zip":
                inv = LEC.inventorier_zip(p)
                e.update({"statut": "PENDING_EXTRACTION", "n_entrees_zip": len(inv), "events": 0})
                entrees.append(e); catalogue += 1
                exclusions.append({"chemin": e["chemin"], "raison": "ZIP_A_EXTRAIRE_VERS_STAGING"})
                continue
            if fmt in LEC.FORMATS_TEXTE:
                e.update({"statut": "TEXTE", "classe": LEC.classifier_texte(p), "events": 0})
                entrees.append(e); catalogue += 1
                continue
            lecteur = LEC.LECTEURS.get(fmt)
            if lecteur is None:
                e.update({"statut": "UNUSABLE", "events": 0}); entrees.append(e)
                inutilisables += 1; exclusions.append({"chemin": e["chemin"], "raison": "FORMAT_SANS_LECTEUR"}); continue
            n_ev = 0
            try:
                for _off, _rec in lecteur(p, max_records=max_events_par_source):
                    if stop_event is not None and stop_event.is_set():
                        break
                    n_ev += 1
                    maintenant = time.monotonic()
                    if maintenant - dernier_affichage >= 0.5:
                        _publier_progression(
                            progress_callback,
                            courant=numero_source - 1,
                            total=total_candidats,
                            detail=(
                                f"source {numero_source}/{total_candidats} {p.name} : "
                                f"{n_ev} événement(s) vérifié(s)"
                            ),
                            unite="sources",
                        )
                        dernier_affichage = maintenant
            except ImportError as ie:                    # ex : Parquet sans moteur -> EXCLU avec raison
                e.update({"statut": "EXCLUDED", "events": 0, "raison": "MOTEUR_ABSENT:%s" % str(ie)[:40]})
                entrees.append(e); exclues += 1
                exclusions.append({"chemin": e["chemin"], "raison": "MOTEUR_LECTEUR_ABSENT (%s)" % fmt}); continue
            except Exception as ex:  # noqa: BLE001
                e.update({"statut": "CORRUPTED", "events": n_ev, "raison": str(ex)[:80]})
                entrees.append(e); erreurs += 1
                exclusions.append({"chemin": e["chemin"], "raison": "LECTURE_ECHEC:%s" % str(ex)[:60]}); continue
            e.update({"statut": ("VALID" if n_ev > 0 else "UNUSABLE"), "events": n_ev})
            events += n_ev
            entrees.append(e); catalogue += 1
            if n_ev > 0:
                parsees += 1
            else:
                inutilisables += 1
            _publier_progression(
                progress_callback,
                courant=numero_source,
                total=total_candidats,
                detail=(
                    f"source {numero_source}/{total_candidats} terminée : "
                    f"{n_ev} événement(s), statut {e['statut']}"
                ),
                unite="sources",
            )
    completeness = round(parsees / detectees, 4) if detectees else 0.0
    acc = {"n_total_detected": total_candidats, "n_batch_detected": detectees,
           "n_catalogued": catalogue, "n_parsed": parsees,
           "n_unusable": inutilisables, "n_excluded": exclues, "n_pending": sum(1 for e in entrees if e.get("statut") == "PENDING_EXTRACTION"),
           "errors": erreurs, "octets": octets, "events": events, "completeness_ratio": completeness,
           "source_offset": source_offset, "next_source_offset": fin_lot,
           "n_deferred": max(0, total_candidats - fin_lot),
           "bootstrap_complete": bool(fin_lot >= total_candidats)}
    (rundir / "catalogue" / "DATA_CATALOG_COMPLET.json").write_text(
        json.dumps({"accounting": acc, "sources": entrees}, ensure_ascii=False, indent=1), encoding="utf-8")
    _ecrire_csv(rundir / "results" / "data_source_accounting.csv",
                ["chemin", "format", "statut", "octets", "events", "sha256_integral", "vivant"], entrees)
    _ecrire_csv(rundir / "results" / "data_source_exclusions.csv", ["chemin", "raison"], exclusions)
    source_plan = []
    for p in candidats:
        try:
            source_plan.append(str(p.relative_to(root)))
        except ValueError:
            source_plan.append(str(p))
    return {
        "accounting": acc,
        "n_sources": len(entrees),
        "sources": entrees,
        "source_plan": source_plan,
        "source_offset": source_offset,
        "next_source_offset": fin_lot,
        "bootstrap_complete": bool(fin_lot >= total_candidats),
    }


def _ecrire_csv(p: Path, cols: list[str], lignes: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for l in lignes:
        w.writerow(l)
    p.write_text(buf.getvalue(), encoding="utf-8")


__all__ = ["cataloguer", "cataloguer_complet", "apercu_rapide", "analyser_jsonl", "STATUTS", "DOSSIERS"]
