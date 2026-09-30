from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.research_lab_selector import (
    load_research_profile,
    select_research_files,
)
from hl_observer.datasets.source_discovery import DATASET_PROVENANCE
from hl_observer.datasets.sqlite_research_source import build_sqlite_research_catalog

EXPERIMENT_PLAN_DIR = Path("runtime") / "reports" / "datasets" / "experiment_plans"
CURRENT_EXPERIMENT_PLAN = EXPERIMENT_PLAN_DIR / "CURRENT_EXPERIMENT_PLAN.json"
CURRENT_EXPERIMENT_PLAN_MD = EXPERIMENT_PLAN_DIR / "CURRENT_EXPERIMENT_PLAN.md"

_COPY_IMPLICIT_TABLES = {
    "fills",
    "positions",
    "position_deltas",
    "wallet_snapshots",
    "wallet_scores",
    "wallet_candidates",
    "wallet_candidate_scores",
}


def _relative(root: Path, value: object) -> str:
    path = Path(str(value)).resolve()
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load_provenance(root: Path) -> dict[str, Any]:
    path = root / DATASET_PROVENANCE
    if not path.is_file():
        return {
            "status": "MISSING",
            "source_release_id": None,
            "suite": None,
            "selection_digest": None,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "status": "UNREADABLE",
            "source_release_id": None,
            "suite": None,
            "selection_digest": None,
        }
    if not isinstance(raw, Mapping):
        return {
            "status": "INVALID",
            "source_release_id": None,
            "suite": None,
            "selection_digest": None,
        }
    return {
        "status": "READY",
        "source_release_id": raw.get("source_release_id"),
        "source_repository": raw.get("source_repository") or raw.get("repository"),
        "suite": raw.get("suite") or raw.get("dataset_suite"),
        "selection_digest": raw.get("selection_digest"),
        "matched_files": raw.get("matched_files") or raw.get("file_count"),
        "matched_raw_bytes": raw.get("matched_raw_bytes") or raw.get("raw_bytes"),
    }


def _normalize_criteria(
    *,
    start_ms: int | None,
    end_ms: int | None,
    family: str | None,
    coin: str | None,
    wallet: str | None,
    metric: str | None,
    require_complete_research: bool,
    include_unknown_time: bool,
) -> dict[str, Any]:
    if start_ms is not None and end_ms is not None and int(start_ms) > int(end_ms):
        raise ValueError("start_ms doit être inférieur ou égal à end_ms")
    return {
        "start_ms": int(start_ms) if start_ms is not None else None,
        "end_ms": int(end_ms) if end_ms is not None else None,
        "family": str(family).strip() if family else None,
        "coin": str(coin).strip().upper() if coin else None,
        "wallet": str(wallet).strip() if wallet else None,
        "metric": str(metric).strip() if metric else None,
        "require_complete_research": bool(require_complete_research),
        "include_unknown_time": bool(include_unknown_time),
    }


def _research_plan(root: Path, criteria: Mapping[str, Any]) -> dict[str, Any]:
    try:
        profile = load_research_profile(root)
    except ValueError as exc:
        return {
            "status": "PROFILE_MISSING",
            "message": str(exc),
            "selected_file_count": 0,
            "selected_source_bytes": 0,
            "selected_source_gib": 0.0,
            "uncertain_selected_file_count": 0,
            "files": [],
            "raw_events_copied": False,
        }

    selection = select_research_files(
        profile,
        start_ms=criteria.get("start_ms"),
        end_ms=criteria.get("end_ms"),
        family=criteria.get("family"),
        coin=criteria.get("coin"),
        metric=criteria.get("metric"),
        require_complete=bool(criteria.get("require_complete_research")),
        include_unknown_time=bool(criteria.get("include_unknown_time")),
    )
    files: list[dict[str, Any]] = []
    for raw in selection.get("files", []):
        if not isinstance(raw, Mapping):
            continue
        files.append(
            {
                "relative_path": raw.get("relative_path"),
                "source_size": int(raw.get("source_size") or 0),
                "timestamp_min_ms": raw.get("timestamp_min_ms"),
                "timestamp_max_ms": raw.get("timestamp_max_ms"),
                "complete": raw.get("complete") is True,
                "selection_uncertain": raw.get("selection_uncertain") is True,
            }
        )
    return {
        "status": "READY" if files else "NO_MATCH",
        "profile_schema": selection.get("profile_schema"),
        "selection_digest": selection.get("selection_digest"),
        "candidate_file_count": selection.get("candidate_file_count", 0),
        "selected_file_count": len(files),
        "selected_source_bytes": selection.get("selected_source_bytes", 0),
        "selected_source_gib": selection.get("selected_source_gib", 0),
        "uncertain_selected_file_count": selection.get("uncertain_selected_file_count", 0),
        "rejected_counts": selection.get("rejected_counts", {}),
        "files": files,
        "raw_events_copied": False,
    }


def _family_mode(table: str, family: str | None, family_filter_supported: bool) -> tuple[bool, str]:
    if not family:
        return True, "NOT_REQUESTED"
    if family_filter_supported:
        return True, "DIRECT_FILTER"
    normalized = family.casefold().replace("-", "_")
    if normalized == "copy_vault" and table in _COPY_IMPLICIT_TABLES:
        return True, "IMPLICIT_COPY_SOURCE"
    if table == "source_health":
        return True, "SUPPORTING_HEALTH_SOURCE"
    return False, "UNSUPPORTED"


def _sqlite_plan(root: Path, criteria: Mapping[str, Any]) -> dict[str, Any]:
    catalog = build_sqlite_research_catalog(root)
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    start_requested = criteria.get("start_ms") is not None or criteria.get("end_ms") is not None
    coin_requested = bool(criteria.get("coin"))
    wallet_requested = bool(criteria.get("wallet"))
    metric = str(criteria.get("metric") or "")
    family = str(criteria.get("family") or "") or None

    raw_databases = catalog.get("databases")
    databases = raw_databases if isinstance(raw_databases, list) else []
    for database in databases:
        if not isinstance(database, Mapping) or database.get("status") != "READABLE_READ_ONLY":
            continue
        database_path = _relative(root, database.get("path"))
        raw_tables = database.get("tables")
        tables = raw_tables if isinstance(raw_tables, list) else []
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            name = str(table.get("name") or "")
            reasons: list[str] = []
            if start_requested and not table.get("time_filter_column"):
                reasons.append("TIME_FILTER_UNSUPPORTED")
            if coin_requested and not table.get("coin_filter_supported"):
                reasons.append("COIN_FILTER_UNSUPPORTED")
            if wallet_requested and not table.get("wallet_filter_column"):
                reasons.append("WALLET_FILTER_UNSUPPORTED")
            family_ok, family_mode = _family_mode(
                name,
                family,
                bool(table.get("family_filter_supported")),
            )
            if not family_ok:
                reasons.append("FAMILY_FILTER_UNSUPPORTED")
            safe_columns = [str(column) for column in (table.get("safe_columns") or [])]
            if metric and metric not in safe_columns:
                reasons.append("METRIC_NOT_EXPOSED")

            row = {
                "database": database_path,
                "table": name,
                "safe_columns": safe_columns,
                "time_filter_column": table.get("time_filter_column"),
                "coin_filter_supported": bool(table.get("coin_filter_supported")),
                "wallet_filter_column": table.get("wallet_filter_column"),
                "family_filter_supported": bool(table.get("family_filter_supported")),
                "family_mode": family_mode,
                "max_rowid_upper_bound": table.get("max_rowid_upper_bound"),
                "filters": {
                    "start_ms": criteria.get("start_ms") if table.get("time_filter_column") else None,
                    "end_ms": criteria.get("end_ms") if table.get("time_filter_column") else None,
                    "coin": criteria.get("coin") if table.get("coin_filter_supported") else None,
                    "wallet": criteria.get("wallet") if table.get("wallet_filter_column") else None,
                    "family": criteria.get("family") if table.get("family_filter_supported") else None,
                },
                "read_only": True,
            }
            if reasons:
                rejected.append({**row, "reasons": reasons})
            else:
                selected.append(row)

    selected.sort(key=lambda item: (str(item["database"]).casefold(), str(item["table"]).casefold()))
    rejected.sort(key=lambda item: (str(item["database"]).casefold(), str(item["table"]).casefold()))
    return {
        "status": "READY" if selected else ("NO_MATCH" if catalog.get("readable_database_count") else "NO_DATABASE"),
        "catalog_schema": catalog.get("schema"),
        "database_count": catalog.get("database_count", 0),
        "readable_database_count": catalog.get("readable_database_count", 0),
        "selected_source_count": len(selected),
        "rejected_source_count": len(rejected),
        "selected": selected,
        "rejected": rejected,
        "read_only": True,
        "safe_columns_only": True,
    }


def build_experiment_plan(
    root: str | Path,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    family: str | None = None,
    coin: str | None = None,
    wallet: str | None = None,
    metric: str | None = None,
    require_complete_research: bool = False,
    include_unknown_time: bool = False,
) -> dict[str, Any]:
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"Workspace absent: {resolved}")
    criteria = _normalize_criteria(
        start_ms=start_ms,
        end_ms=end_ms,
        family=family,
        coin=coin,
        wallet=wallet,
        metric=metric,
        require_complete_research=require_complete_research,
        include_unknown_time=include_unknown_time,
    )
    provenance = _load_provenance(resolved)
    research = _research_plan(resolved, criteria)
    sqlite = _sqlite_plan(resolved, criteria)

    warnings: list[str] = []
    if provenance.get("status") != "READY":
        warnings.append("PROVENANCE_NOT_READY")
    if research.get("status") == "PROFILE_MISSING":
        warnings.append("RESEARCH_PROFILE_MISSING")
    if int(research.get("uncertain_selected_file_count") or 0) > 0:
        warnings.append("RESEARCH_SELECTION_HAS_UNCERTAIN_FILES")
    if sqlite.get("status") in {"NO_DATABASE", "NO_MATCH"}:
        warnings.append("SQLITE_SELECTION_EMPTY")

    digest_material = {
        "criteria": criteria,
        "source_release_id": provenance.get("source_release_id"),
        "suite": provenance.get("suite"),
        "source_selection_digest": provenance.get("selection_digest"),
        "research_files": [item.get("relative_path") for item in research.get("files", [])],
        "sqlite_sources": [
            [item.get("database"), item.get("table")]
            for item in sqlite.get("selected", [])
        ],
    }
    digest = hashlib.sha256(
        json.dumps(digest_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    ready_sources = int(research.get("selected_file_count") or 0) + int(sqlite.get("selected_source_count") or 0)
    return {
        "schema": "hypersmart.dataset_experiment_plan.v1",
        "root": str(resolved),
        "experiment_digest": digest,
        "criteria": criteria,
        "provenance": provenance,
        "research_lab": research,
        "sqlite": sqlite,
        "ready_source_count": ready_sources,
        "status": "READY" if ready_sources > 0 else "NO_MATCH",
        "warnings": warnings,
        "read_only": True,
        "network_used": False,
        "raw_data_copied": False,
        "real_execution": False,
    }


def render_experiment_plan_markdown(plan: Mapping[str, Any]) -> str:
    criteria = plan.get("criteria") if isinstance(plan.get("criteria"), Mapping) else {}
    provenance = plan.get("provenance") if isinstance(plan.get("provenance"), Mapping) else {}
    research = plan.get("research_lab") if isinstance(plan.get("research_lab"), Mapping) else {}
    sqlite = plan.get("sqlite") if isinstance(plan.get("sqlite"), Mapping) else {}
    lines = [
        "# Plan d'expérience FULL/COLD",
        "",
        f"- Statut : **{plan.get('status')}**",
        f"- Digest : `{plan.get('experiment_digest')}`",
        f"- Release source : `{provenance.get('source_release_id')}`",
        f"- Suite : `{provenance.get('suite')}`",
        "- Lecture locale/read-only uniquement; aucune donnée brute n'est copiée par ce plan.",
        "",
        "## Critères",
        "",
        "| Critère | Valeur |",
        "|---|---|",
    ]
    for key in ("start_ms", "end_ms", "family", "coin", "wallet", "metric", "require_complete_research", "include_unknown_time"):
        lines.append(f"| {key} | `{criteria.get(key)}` |")
    lines.extend(
        [
            "",
            "## Research Lab",
            "",
            f"- Statut : **{research.get('status')}**",
            f"- Fichiers sélectionnés : **{research.get('selected_file_count', 0)}**.",
            f"- Volume brut ciblé : **{research.get('selected_source_gib', 0)} Gio**.",
            f"- Fichiers incertains : **{research.get('uncertain_selected_file_count', 0)}**.",
            "",
            "## SQLite",
            "",
            f"- Statut : **{sqlite.get('status')}**",
            f"- Bases lisibles : **{sqlite.get('readable_database_count', 0)}**.",
            f"- Couples base/table retenus : **{sqlite.get('selected_source_count', 0)}**.",
            f"- Couples rejetés par les filtres : **{sqlite.get('rejected_source_count', 0)}**.",
            "",
            "| Base | Table | Temps | Coin | Wallet | Famille |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in sqlite.get("selected", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('database')}` | `{item.get('table')}` | "
            f"`{item.get('time_filter_column')}` | {item.get('coin_filter_supported')} | "
            f"`{item.get('wallet_filter_column')}` | `{item.get('family_mode')}` |"
        )
    warnings = plan.get("warnings") if isinstance(plan.get("warnings"), list) else []
    lines.extend(["", "## Avertissements", ""])
    if warnings:
        lines.extend(f"- `{warning}`" for warning in warnings)
    else:
        lines.append("- Aucun avertissement structurel.")
    lines.extend(
        [
            "",
            "> Ce plan sélectionne les sources; il ne constitue pas un résultat de backtest, une validation OOS ou une preuve de PnL.",
            "",
        ]
    )
    return "\n".join(lines)


def write_experiment_plan(
    root: str | Path,
    **criteria: Any,
) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    plan = build_experiment_plan(resolved, **criteria)
    directory = resolved / EXPERIMENT_PLAN_DIR
    directory.mkdir(parents=True, exist_ok=True)
    digest = str(plan["experiment_digest"])
    json_path = directory / f"experiment_{digest[:16]}.json"
    md_path = directory / f"experiment_{digest[:16]}.md"
    json_text = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_experiment_plan_markdown(plan)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    (resolved / CURRENT_EXPERIMENT_PLAN).write_text(json_text, encoding="utf-8")
    (resolved / CURRENT_EXPERIMENT_PLAN_MD).write_text(markdown, encoding="utf-8")
    return json_path, md_path, plan


__all__ = [
    "CURRENT_EXPERIMENT_PLAN",
    "CURRENT_EXPERIMENT_PLAN_MD",
    "EXPERIMENT_PLAN_DIR",
    "build_experiment_plan",
    "render_experiment_plan_markdown",
    "write_experiment_plan",
]
