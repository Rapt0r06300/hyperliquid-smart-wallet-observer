"""Detailed, bounded audit for a continuous-research shutdown.

This module is deliberately read-only with respect to research inputs. It only
writes final report companions below ``<run>/results``. Large JSONL files are
streamed, and only a bounded tail is retained in memory.
"""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable
import csv
import json
import os
import tempfile
import time
from pathlib import Path


MAX_JSONL_ROWS_PARSED = 250_000
TAIL_ROWS = 20


def _read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _atomic_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=".%s.%s." % (path.name, os.getpid()),
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _write_json(path: Path, value) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def _write_csv(path: Path, columns: Iterable[str], rows: Iterable[dict]) -> None:
    path = Path(path)
    columns = list(columns)
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    _atomic_text(path, buffer.getvalue())


def _file_time(value) -> str | None:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return None


def _human_bytes(value: int | float | None) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "0 o"
    units = ("o", "Kio", "Mio", "Gio", "Tio")
    index = 0
    while size >= 1024.0 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return ("%.2f %s" % (size, units[index])) if index else ("%d o" % int(size))


def _safe_stat(path: Path) -> dict:
    try:
        stat = path.stat()
        return {"size": stat.st_size, "mtime": stat.st_mtime}
    except OSError as exc:
        return {"size": 0, "mtime": None, "error": "%s: %s" % (type(exc).__name__, exc)}


def _jsonl_summary(path: Path, *, max_rows_parsed: int = MAX_JSONL_ROWS_PARSED) -> dict:
    """Stream a JSONL file and retain only counters and a small recent tail."""
    path = Path(path)
    result = {
        "path": str(path),
        "exists": path.exists(),
        "bytes": 0,
        "rows_total": 0,
        "rows_parsed": 0,
        "invalid_rows": 0,
        "parse_limited": False,
        "first_timestamp": None,
        "last_timestamp": None,
        "by_type": {},
        "by_status": {},
        "by_verdict": {},
        "recent": [],
    }
    if not path.exists():
        return result
    result["bytes"] = _safe_stat(path)["size"]
    by_type, by_status, by_verdict = Counter(), Counter(), Counter()
    recent = deque(maxlen=TAIL_ROWS)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                result["rows_total"] += 1
                if result["rows_parsed"] >= max_rows_parsed:
                    result["parse_limited"] = True
                    continue
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except ValueError:
                    result["invalid_rows"] += 1
                    continue
                result["rows_parsed"] += 1
                if not isinstance(item, dict):
                    continue
                by_type[str(item.get("type") or "ABSENT")] += 1
                by_status[str(item.get("status") or item.get("statut") or "ABSENT")] += 1
                by_verdict[str(item.get("verdict") or "ABSENT")] += 1
                timestamp = (
                    item.get("ts")
                    or item.get("timestamp")
                    or item.get("ts_wall")
                    or item.get("ts_wall_ms")
                    or item.get("exchange_ts")
                )
                if timestamp is not None:
                    try:
                        timestamp = float(timestamp)
                        if timestamp > 10_000_000_000:
                            timestamp /= 1000.0
                        if result["first_timestamp"] is None:
                            result["first_timestamp"] = timestamp
                        result["last_timestamp"] = timestamp
                    except (TypeError, ValueError):
                        pass
                recent.append(item)
    except OSError as exc:
        result["read_error"] = "%s: %s" % (type(exc).__name__, exc)
    result["by_type"] = dict(by_type.most_common())
    result["by_status"] = dict(by_status.most_common())
    result["by_verdict"] = dict(by_verdict.most_common())
    result["recent"] = list(recent)
    result["first_timestamp_iso"] = _file_time(result["first_timestamp"])
    result["last_timestamp_iso"] = _file_time(result["last_timestamp"])
    return result


def _csv_summary(path: Path, *, group_fields: tuple[str, ...]) -> dict:
    path = Path(path)
    result = {
        "path": str(path),
        "exists": path.exists(),
        "bytes": 0,
        "rows": 0,
        "invalid_rows": 0,
        "groups": {field: {} for field in group_fields},
        "recent": [],
    }
    if not path.exists():
        return result
    result["bytes"] = _safe_stat(path)["size"]
    groups = {field: Counter() for field in group_fields}
    recent = deque(maxlen=TAIL_ROWS)
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    result["invalid_rows"] += 1
                    continue
                result["rows"] += 1
                for field in group_fields:
                    groups[field][str(row.get(field) or "ABSENT")] += 1
                recent.append(row)
    except (OSError, csv.Error) as exc:
        result["read_error"] = "%s: %s" % (type(exc).__name__, exc)
    result["groups"] = {
        field: dict(counter.most_common()) for field, counter in groups.items()
    }
    result["recent"] = list(recent)
    return result


def _campaigns(rundir: Path) -> list[dict]:
    rows = []
    base = rundir / "campagnes"
    if not base.exists():
        return rows
    for campaign_dir in sorted(path for path in base.glob("camp-*") if path.is_dir()):
        campaign = _read_json(campaign_dir / "campaign.json", {})
        scheduler = _read_json(campaign_dir / "scheduler_state.json", {})
        pipeline = _read_json(campaign_dir / "resultats" / "pipeline_resume.json", {})
        verdicts = _read_json(campaign_dir / "resultats" / "final_verdicts.json", [])
        trial_summary = _jsonl_summary(campaign_dir / "ledger" / "trials_results.jsonl")
        if pipeline:
            status = "INTERRUPTED" if pipeline.get("interrompu") else "COMPLETED"
            stopped_at = pipeline.get("phase") or pipeline.get("stopped_reason")
        elif campaign:
            status = "IN_PROGRESS_OR_INTERRUPTED"
            stopped_at = None
        else:
            status = "INCOMPLETE_METADATA"
            stopped_at = None
        stat = {"files": 0, "bytes": 0}
        for path in campaign_dir.rglob("*"):
            if not path.is_file():
                continue
            info = _safe_stat(path)
            stat["files"] += 1
            stat["bytes"] += int(info.get("size") or 0)
        rows.append({
            "campaign_id": campaign.get("campaign_id") or campaign_dir.name,
            "cycle": campaign.get("cycle"),
            "status": status,
            "stopped_at": stopped_at,
            "n_new_events": campaign.get("n_new_events", 0),
            "sources_with_new_data": campaign.get("sources_avec_nouveaute", 0),
            "new_variants": campaign.get("n_variantes_nouvelles", 0),
            "scheduler_queues_consumed": len(scheduler.get("files_consommees") or []),
            "scheduler_all_consumed": scheduler.get("toutes_consommees"),
            "fast_screen": pipeline.get("n_fast_screen", 0),
            "exact_replays": pipeline.get("n_exact_replays", 0),
            "survivors": pipeline.get("n_survivants", 0),
            "pass_forward": pipeline.get("n_pass", 0),
            "final_verdicts": len(verdicts) if isinstance(verdicts, list) else 0,
            "trial_rows": trial_summary.get("rows_total", 0),
            "invalid_trial_rows": trial_summary.get("invalid_rows", 0),
            "files": stat["files"],
            "bytes": stat["bytes"],
            "bytes_human": _human_bytes(stat["bytes"]),
        })
    return rows


def _cursor_summary(rundir: Path) -> dict:
    cursors = _read_json(rundir / "cursors.json", {})
    result = {
        "exists": bool(cursors),
        "sources": 0,
        "stream_sources": 0,
        "identity_sources": 0,
        "offset_bytes": 0,
        "source_bytes": 0,
        "remaining_bytes": 0,
        "rotations": 0,
        "new_events_last_scan": 0,
        "sources_with_new_events": 0,
        "coverage_pct": None,
        "top_sources": [],
    }
    if not isinstance(cursors, dict):
        return result
    top = []
    for name, info in cursors.items():
        if not isinstance(info, dict):
            continue
        result["sources"] += 1
        if "offset" in info or "taille" in info:
            result["stream_sources"] += 1
            offset = max(0, int(info.get("offset") or 0))
            size = max(offset, int(info.get("taille") or offset))
            remaining = max(0, size - offset)
            new_events = max(0, int(info.get("n_nouveaux") or 0))
            result["offset_bytes"] += offset
            result["source_bytes"] += size
            result["remaining_bytes"] += remaining
            result["new_events_last_scan"] += new_events
            result["sources_with_new_events"] += int(new_events > 0)
            result["rotations"] += int(bool(info.get("rotation")))
            top.append({
                "source": name,
                "offset": offset,
                "size": size,
                "remaining": remaining,
                "new_events": new_events,
                "rotation": bool(info.get("rotation")),
            })
        elif info.get("sig"):
            result["identity_sources"] += 1
    if result["source_bytes"]:
        result["coverage_pct"] = round(
            100.0 * result["offset_bytes"] / result["source_bytes"], 4
        )
    result["top_sources"] = sorted(
        top,
        key=lambda item: (item["new_events"], item["remaining"], item["size"]),
        reverse=True,
    )[:30]
    return result


def _canonical_summary(rundir: Path) -> dict:
    base = rundir / "canonical"
    maturation = _read_json(base / "maturation.json", {})
    snapshot = _read_json(base / "snapshot.json", {})
    files = []
    if base.exists():
        for path in sorted(path for path in base.rglob("*") if path.is_file()):
            stat = _safe_stat(path)
            files.append({
                "path": str(path.relative_to(rundir)),
                "bytes": stat.get("size", 0),
                "bytes_human": _human_bytes(stat.get("size", 0)),
                "modified_at": _file_time(stat.get("mtime")),
            })
    return {
        "maturation": maturation,
        "snapshot": snapshot,
        "files": files,
        "bytes": sum(int(item.get("bytes") or 0) for item in files),
    }


def _inventory(rundir: Path) -> dict:
    rows, errors = [], []
    by_area, by_extension = Counter(), Counter()
    total_bytes = 0
    for path in sorted(rundir.rglob("*")):
        if not path.is_file():
            continue
        stat = _safe_stat(path)
        if stat.get("error"):
            errors.append({"path": str(path), "error": stat["error"]})
            continue
        relative = path.relative_to(rundir)
        area = relative.parts[0] if relative.parts else "."
        extension = path.suffix.lower() or "(sans extension)"
        size = int(stat.get("size") or 0)
        total_bytes += size
        by_area[area] += size
        by_extension[extension] += size
        rows.append({
            "path": relative.as_posix(),
            "area": area,
            "extension": extension,
            "bytes": size,
            "bytes_human": _human_bytes(size),
            "modified_at": _file_time(stat.get("mtime")),
        })
    return {
        "files": len(rows),
        "bytes": total_bytes,
        "bytes_human": _human_bytes(total_bytes),
        "by_area_bytes": dict(by_area.most_common()),
        "by_extension_bytes": dict(by_extension.most_common()),
        "largest": sorted(rows, key=lambda item: item["bytes"], reverse=True)[:30],
        "rows": rows,
        "errors": errors,
    }


def collecter(rundir: str | Path, ident: dict) -> dict:
    """Collect a factual final snapshot and write its machine-readable companions."""
    rundir = Path(rundir)
    results = rundir / "results"
    results.mkdir(parents=True, exist_ok=True)
    context = _read_json(results / "FINAL-INTERRUPTION-CONTEXT.json", {})
    live = _read_json(rundir / "LIVE-RESEARCH-STATE.json", {})
    finalization = _read_json(results / "FINALIZATION-STATE.json", {})
    safety = _read_json(results / "FINAL-SAFETY-AUDIT.json", {})
    campaigns = _campaigns(rundir)
    cursors = _cursor_summary(rundir)
    canonical = _canonical_summary(rundir)
    errors = _jsonl_summary(results / "RUN-ERRORS.jsonl")
    accounting = _csv_summary(
        results / "data_source_accounting.csv",
        group_fields=("statut", "status", "type", "format", "source"),
    )
    exclusions = _csv_summary(
        results / "data_source_exclusions.csv",
        group_fields=("raison", "reason", "type", "statut", "status"),
    )
    inventory = _inventory(rundir)
    now = time.time()
    started_ms = ident.get("t0_wall_ms")
    duration = (
        max(0.0, now - float(started_ms) / 1000.0)
        if started_ms is not None
        else None
    )
    summary = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_epoch": now,
        "run": {
            "run_id": ident.get("run_id"),
            "code_sha": ident.get("code_sha"),
            "cycle": ident.get("cycle_courant"),
            "read_only": ident.get("read_only"),
            "real_execution": ident.get("real_execution"),
            "duration_seconds": duration,
        },
        "stop_context": context,
        "live_state": live,
        "finalization": finalization,
        "safety": safety,
        "campaigns": campaigns,
        "campaign_totals": {
            "count": len(campaigns),
            "completed": sum(row["status"] == "COMPLETED" for row in campaigns),
            "interrupted_or_incomplete": sum(row["status"] != "COMPLETED" for row in campaigns),
            "new_events": sum(int(row.get("n_new_events") or 0) for row in campaigns),
            "sources_with_new_data": sum(
                int(row.get("sources_with_new_data") or 0) for row in campaigns
            ),
            "variants": sum(int(row.get("new_variants") or 0) for row in campaigns),
            "fast_screen": sum(int(row.get("fast_screen") or 0) for row in campaigns),
            "exact_replays": sum(int(row.get("exact_replays") or 0) for row in campaigns),
            "pass_forward": sum(int(row.get("pass_forward") or 0) for row in campaigns),
        },
        "cursors": cursors,
        "canonical": canonical,
        "runtime_errors": errors,
        "source_accounting": accounting,
        "source_exclusions": exclusions,
        "inventory": {
            key: value for key, value in inventory.items() if key != "rows"
        },
    }
    _write_json(results / "FINAL-RUN-SUMMARY.json", summary)
    _write_csv(
        results / "FINAL-CAMPAIGN-STATUS.csv",
        (
            "campaign_id", "cycle", "status", "stopped_at", "n_new_events",
            "sources_with_new_data", "new_variants", "scheduler_queues_consumed",
            "scheduler_all_consumed", "fast_screen", "exact_replays", "survivors",
            "pass_forward", "final_verdicts", "trial_rows", "invalid_trial_rows",
            "files", "bytes", "bytes_human",
        ),
        campaigns,
    )
    _write_csv(
        results / "FINAL-ERRORS.csv",
        ("timestamp", "timestamp_iso", "type", "phase", "cycle", "error", "raw"),
        _error_rows(errors),
    )
    _write_csv(
        results / "FINAL-ARTIFACT-INVENTORY.csv",
        ("path", "area", "extension", "bytes", "bytes_human", "modified_at"),
        inventory["rows"],
    )
    _write_csv(
        results / "FINAL-CURSOR-COVERAGE.csv",
        ("source", "offset", "size", "remaining", "new_events", "rotation"),
        cursors["top_sources"],
    )
    return summary


def _error_rows(errors: dict) -> list[dict]:
    rows = []
    for item in errors.get("recent") or []:
        timestamp = item.get("ts") or item.get("timestamp")
        rows.append({
            "timestamp": timestamp,
            "timestamp_iso": _file_time(timestamp),
            "type": item.get("type"),
            "phase": item.get("phase"),
            "cycle": item.get("cycle"),
            "error": item.get("erreur") or item.get("error"),
            "raw": json.dumps(item, ensure_ascii=False, default=str),
        })
    return rows


def markdown(summary: dict) -> str:
    """Render factual Markdown sections appended to the main final report."""
    campaigns = summary.get("campaigns") or []
    totals = summary.get("campaign_totals") or {}
    cursors = summary.get("cursors") or {}
    canonical = summary.get("canonical") or {}
    maturation = canonical.get("maturation") or {}
    errors = summary.get("runtime_errors") or {}
    inventory = summary.get("inventory") or {}
    context = summary.get("stop_context") or {}
    live = summary.get("live_state") or {}
    progress = context.get("progress") or live.get("progression") or {}
    safety = summary.get("safety") or {}
    lines = [
        "## 46. Contexte exact de l'arrêt",
        "- raison : **%s** · signaux Ctrl+C reçus : **%s** · urgence : **%s**"
        % (
            context.get("reason") or context.get("raison") or "non précisée",
            context.get("signal_count", 0),
            context.get("emergency", False),
        ),
        "- cycle/phase au moment de l'arrêt : **%s / %s** · tâche : **%s**"
        % (
            context.get("cycle") or live.get("cycle") or live.get("cycle_courant") or "inconnu",
            context.get("phase") or live.get("phase") or "inconnue",
            progress.get("job") or "non publiée",
        ),
        "- progression capturée : **%s%%** · %s/%s · boucle interne %s/%s · ETA au signal %ss"
        % (
            progress.get("pourcentage", 0),
            progress.get("fait", 0),
            progress.get("total", 0),
            progress.get("traite", "—"),
            progress.get("traite_total", "—"),
            progress.get("eta", "—"),
        ),
        "",
        "## 47. Campagnes terminées et travail interrompu",
        "- campagnes : **%s** · terminées : **%s** · incomplètes/interrompues : **%s**"
        % (
            totals.get("count", 0),
            totals.get("completed", 0),
            totals.get("interrupted_or_incomplete", 0),
        ),
        "- données annoncées par les campagnes : **%s événements**, **%s sources avec nouveauté**, **%s variantes**"
        % (
            totals.get("new_events", 0),
            totals.get("sources_with_new_data", 0),
            totals.get("variants", 0),
        ),
        "",
        "| campagne | cycle | état | événements | sources | variantes | fast | exact | PASS | arrêt |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in campaigns[:50]:
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                row.get("campaign_id"),
                row.get("cycle"),
                row.get("status"),
                row.get("n_new_events"),
                row.get("sources_with_new_data"),
                row.get("new_variants"),
                row.get("fast_screen"),
                row.get("exact_replays"),
                row.get("pass_forward"),
                row.get("stopped_at") or "—",
            )
        )
    if not campaigns:
        lines.append("| — | — | aucune campagne écrite | 0 | 0 | 0 | 0 | 0 | 0 | — |")
    lines.extend([
        "",
        "## 48. Couverture des données et curseurs",
        "- sources suivies : **%s** (JSONL %s · identité %s) · couverture octets : **%s%%**"
        % (
            cursors.get("sources", 0),
            cursors.get("stream_sources", 0),
            cursors.get("identity_sources", 0),
            cursors.get("coverage_pct") if cursors.get("coverage_pct") is not None else "inconnue",
        ),
        "- consommé : **%s** / **%s** · restant actuellement visible : **%s** · rotations détectées : **%s**"
        % (
            _human_bytes(cursors.get("offset_bytes")),
            _human_bytes(cursors.get("source_bytes")),
            _human_bytes(cursors.get("remaining_bytes")),
            cursors.get("rotations", 0),
        ),
        "- événements du dernier passage de curseurs : **%s** sur **%s** sources."
        % (
            cursors.get("new_events_last_scan", 0),
            cursors.get("sources_with_new_events", 0),
        ),
        "",
        "## 49. Maturation canonique",
        "- mariés : **%s** · consommés : **%s** · expirés : **%s** · backlog : **%s**"
        % (
            maturation.get("maries", "—"),
            maturation.get("consommes", "—"),
            maturation.get("expires", "—"),
            maturation.get("backlog", "—"),
        ),
        "- stockage canonique : **%s**. Le détail des états/horizons reste dans `canonical/maturation.json`."
        % _human_bytes(canonical.get("bytes")),
        "",
        "## 50. Erreurs, reprises et intégrité des journaux",
        "- erreurs runtime enregistrées : **%s** · lignes invalides : **%s** · analyse bornée : **%s**"
        % (
            errors.get("rows_total", 0),
            errors.get("invalid_rows", 0),
            errors.get("parse_limited", False),
        ),
    ])
    for item in (errors.get("recent") or [])[-10:]:
        lines.append(
            "- `%s` · cycle %s · phase %s · %s : %s"
            % (
                _file_time(item.get("ts")) or item.get("ts") or "heure inconnue",
                item.get("cycle", "—"),
                item.get("phase", "—"),
                item.get("type", "Erreur"),
                str(item.get("erreur") or item.get("error") or "sans détail")[:300],
            )
        )
    if not errors.get("rows_total"):
        lines.append("- aucune erreur structurée enregistrée.")
    lines.extend([
        "",
        "## 51. Inventaire des artefacts conservés",
        "- fichiers : **%s** · volume : **%s** · erreurs d'inventaire : **%s**"
        % (
            inventory.get("files", 0),
            inventory.get("bytes_human", "0 o"),
            len(inventory.get("errors") or []),
        ),
    ])
    for item in (inventory.get("largest") or [])[:10]:
        lines.append("- `%s` · %s" % (item.get("path"), item.get("bytes_human")))
    lines.extend([
        "",
        "## 52. Qualité des sources et exclusions",
        "- accounting : **%s lignes** · exclusions : **%s lignes**."
        % (
            (summary.get("source_accounting") or {}).get("rows", 0),
            (summary.get("source_exclusions") or {}).get("rows", 0),
        ),
        "- répartitions complètes : `FINAL-RUN-SUMMARY.json` et fichiers CSV de source existants.",
        "",
        "## 53. Annexes générées au Ctrl+C",
        "- `results/FINAL-RUN-SUMMARY.json` : état machine complet du run.",
        "- `results/FINAL-CAMPAIGN-STATUS.csv` : une ligne par campagne.",
        "- `results/FINAL-ERRORS.csv` : erreurs récentes structurées.",
        "- `results/FINAL-ARTIFACT-INVENTORY.csv` : inventaire des fichiers conservés.",
        "- `results/FINAL-CURSOR-COVERAGE.csv` : sources les plus actives ou en retard.",
        "- `results/FINAL-INTERRUPTION-CONTEXT.json` : état exact capturé au signal.",
        "",
        "## 54. Audit final et prochaine reprise",
        "- audit sécurité final : **%s** · fichiers scannés : **%s** · constats : **%s**"
        % (
            safety.get("securise", "pas encore disponible"),
            safety.get("fichiers_scannes", "—"),
            len(safety.get("findings") or []),
        ),
        "- toute campagne non `COMPLETED` reste explicitement incomplète et ses paramètres ne sont pas annoncés comme validés.",
        "- prochaine reprise : relire `FINAL-RUN-SUMMARY.json`, corriger les erreurs listées, puis reprendre les campagnes incomplètes sans effacer les curseurs.",
        "",
    ])
    return "\n".join(lines)


__all__ = ["collecter", "markdown"]
