from __future__ import annotations

import json
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from hl_observer.datasets.experiment_contract import (
    CURRENT_REPLAY_INPUT_CONTRACT,
    calculate_contract_digest,
)
from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN
from hl_observer.datasets.sqlite_research_source import (
    SAFE_RESEARCH_COLUMNS,
    TIME_FILTER_COLUMN,
    WALLET_FILTER_COLUMN,
    _open_readonly,
    _schema_columns,
    _table_names,
    safe_sqlite_databases,
)

VERIFICATION_DIR = Path("runtime") / "reports" / "datasets" / "experiment_contracts"
CURRENT_CONTRACT_VERIFICATION = VERIFICATION_DIR / "CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.json"
CURRENT_CONTRACT_VERIFICATION_MD = VERIFICATION_DIR / "CURRENT_REPLAY_INPUT_CONTRACT_VERIFICATION.md"


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} absent: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} invalide: objet JSON attendu")
    return raw


def load_current_contract(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    return _load_json(
        resolved / CURRENT_REPLAY_INPUT_CONTRACT,
        label="Contrat de replay courant",
    )


def _resolve_inside(root: Path, value: object, *, label: str) -> Path:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise ValueError(f"{label} vide")
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"{label} absolu refusé: {text}")
    if any(part in {"..", ""} for part in posix.parts):
        raise ValueError(f"{label} avec traversée refusé: {text}")
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} sort du workspace: {text}") from exc
    return candidate


def _filter_support_errors(
    table: str,
    existing: set[str],
    filters: Mapping[str, Any],
    family_mode: object,
) -> list[str]:
    errors: list[str] = []
    start_ms = filters.get("start_ms")
    end_ms = filters.get("end_ms")
    if start_ms is not None and end_ms is not None and int(start_ms) > int(end_ms):
        errors.append("TIME_RANGE_INVERTED")
    if start_ms is not None or end_ms is not None:
        column = TIME_FILTER_COLUMN.get(table)
        if not column or column not in existing:
            errors.append("TIME_FILTER_UNSUPPORTED")
    if filters.get("coin") not in {None, ""} and "coin" not in existing:
        errors.append("COIN_FILTER_UNSUPPORTED")
    if filters.get("wallet") not in {None, ""}:
        column = WALLET_FILTER_COLUMN.get(table)
        if not column or column not in existing:
            errors.append("WALLET_FILTER_UNSUPPORTED")
    if filters.get("family") not in {None, ""} and "family" not in existing:
        if str(family_mode or "") not in {
            "IMPLICIT_COPY_SOURCE",
            "SUPPORTING_HEALTH_SOURCE",
        }:
            errors.append("FAMILY_FILTER_UNSUPPORTED")
    return errors


def verify_replay_input_contract(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise ValueError(f"Workspace absent: {resolved}")
    contract = load_current_contract(resolved)
    plan = _load_json(resolved / CURRENT_EXPERIMENT_PLAN, label="Plan d'expérience courant")

    errors: list[str] = []
    warnings: list[str] = []
    stored_digest = str(contract.get("contract_digest") or "")
    recomputed_digest = calculate_contract_digest(contract)
    digest_ok = bool(stored_digest) and stored_digest == recomputed_digest
    if not digest_ok:
        errors.append("CONTRACT_DIGEST_MISMATCH")

    experiment_digest = str(contract.get("experiment_digest") or "")
    current_experiment_digest = str(plan.get("experiment_digest") or "")
    experiment_link_ok = bool(experiment_digest) and experiment_digest == current_experiment_digest
    if not experiment_link_ok:
        errors.append("EXPERIMENT_DIGEST_MISMATCH")
    if plan.get("status") != "READY":
        errors.append("CURRENT_EXPERIMENT_NOT_READY")

    safety_fields = {
        "paths_relative_to_workspace": contract.get("paths_relative_to_workspace") is True,
        "read_only": contract.get("read_only") is True,
        "network_used_false": contract.get("network_used") is False,
        "raw_data_embedded_false": contract.get("raw_data_embedded") is False,
        "real_execution_false": contract.get("real_execution") is False,
        "sql_strings_embedded_false": contract.get("sql_strings_embedded") is False,
    }
    for key, ok in safety_fields.items():
        if not ok:
            errors.append(f"SAFETY_FIELD_INVALID:{key}")

    research_results: list[dict[str, Any]] = []
    raw_research = contract.get("research_lab_sources")
    research = raw_research if isinstance(raw_research, list) else []
    for raw in research:
        if not isinstance(raw, Mapping):
            errors.append("RESEARCH_SOURCE_INVALID_OBJECT")
            continue
        relative = raw.get("relative_path")
        source_errors: list[str] = []
        try:
            path = _resolve_inside(resolved, relative, label="Chemin Research Lab")
        except ValueError as exc:
            source_errors.append(f"PATH_INVALID:{exc}")
            path = None
        actual_size: int | None = None
        expected_size = int(raw.get("source_size") or 0)
        if path is not None:
            if not path.is_file():
                source_errors.append("FILE_MISSING")
            else:
                try:
                    actual_size = int(path.stat().st_size)
                except OSError:
                    source_errors.append("FILE_STAT_FAILED")
                if expected_size > 0 and actual_size is not None and actual_size != expected_size:
                    source_errors.append("FILE_SIZE_MISMATCH")
                if expected_size <= 0:
                    warnings.append(f"RESEARCH_SIZE_UNKNOWN:{relative}")
        if source_errors:
            errors.extend(f"RESEARCH:{relative}:{item}" for item in source_errors)
        research_results.append(
            {
                "relative_path": relative,
                "expected_size": expected_size,
                "actual_size": actual_size,
                "status": "READY" if not source_errors else "FAILED",
                "errors": source_errors,
            }
        )

    safe_db_paths = {path.resolve() for path in safe_sqlite_databases(resolved)}
    sqlite_results: list[dict[str, Any]] = []
    raw_sqlite = contract.get("sqlite_sources")
    sqlite_sources = raw_sqlite if isinstance(raw_sqlite, list) else []
    for raw in sqlite_sources:
        if not isinstance(raw, Mapping):
            errors.append("SQLITE_SOURCE_INVALID_OBJECT")
            continue
        relative = raw.get("database")
        table = str(raw.get("table") or "")
        source_errors: list[str] = []
        try:
            database = _resolve_inside(resolved, relative, label="Chemin SQLite")
        except ValueError as exc:
            source_errors.append(f"PATH_INVALID:{exc}")
            database = None
        existing_columns: set[str] = set()
        if database is not None:
            if not database.is_file():
                source_errors.append("DATABASE_MISSING")
            elif database.resolve() not in safe_db_paths:
                source_errors.append("DATABASE_NOT_IN_SAFE_ALLOWLIST")
            elif table not in SAFE_RESEARCH_COLUMNS:
                source_errors.append("TABLE_NOT_IN_ALLOWLIST")
            else:
                connection: sqlite3.Connection | None = None
                try:
                    connection = _open_readonly(database)
                    if table not in _table_names(connection):
                        source_errors.append("TABLE_MISSING")
                    else:
                        existing_columns = set(_schema_columns(connection, table))
                        expected_columns = [str(item) for item in (raw.get("safe_columns") or [])]
                        allowlist = set(SAFE_RESEARCH_COLUMNS[table])
                        if any(column not in allowlist for column in expected_columns):
                            source_errors.append("CONTRACT_COLUMN_NOT_ALLOWED")
                        if any(column not in existing_columns for column in expected_columns):
                            source_errors.append("CONTRACT_COLUMN_MISSING")
                        filters = raw.get("filters") if isinstance(raw.get("filters"), Mapping) else {}
                        source_errors.extend(
                            _filter_support_errors(
                                table,
                                existing_columns,
                                filters,
                                raw.get("family_mode"),
                            )
                        )
                except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as exc:
                    source_errors.append(f"SCHEMA_READ_FAILED:{type(exc).__name__}")
                finally:
                    if connection is not None:
                        connection.close()
        if source_errors:
            errors.extend(f"SQLITE:{relative}:{table}:{item}" for item in source_errors)
        sqlite_results.append(
            {
                "database": relative,
                "table": table,
                "existing_safe_columns": sorted(
                    existing_columns & set(SAFE_RESEARCH_COLUMNS.get(table, ()))
                ),
                "status": "READY" if not source_errors else "FAILED",
                "errors": source_errors,
            }
        )

    declared_source_count = int(contract.get("source_count") or 0)
    actual_contract_source_count = len(research) + len(sqlite_sources)
    source_count_ok = declared_source_count == actual_contract_source_count and declared_source_count > 0
    if not source_count_ok:
        errors.append("SOURCE_COUNT_MISMATCH")

    release_id = None
    provenance = contract.get("provenance")
    if isinstance(provenance, Mapping):
        release_id = provenance.get("source_release_id")
    if int(release_id or 0) != 371149058:
        warnings.append("SOURCE_RELEASE_NOT_CANONICAL_371149058")

    return {
        "schema": "hypersmart.replay_input_contract_verification.v1",
        "root": str(resolved),
        "status": "READY" if not errors else "NO_GO",
        "contract_digest": stored_digest,
        "recomputed_contract_digest": recomputed_digest,
        "contract_digest_ok": digest_ok,
        "experiment_digest": experiment_digest,
        "current_experiment_digest": current_experiment_digest,
        "experiment_link_ok": experiment_link_ok,
        "source_count_ok": source_count_ok,
        "declared_source_count": declared_source_count,
        "verified_source_count": sum(
            item.get("status") == "READY" for item in research_results + sqlite_results
        ),
        "research_lab": research_results,
        "sqlite": sqlite_results,
        "safety_fields": safety_fields,
        "errors": errors,
        "warnings": warnings,
        "row_data_read": False,
        "read_only": True,
        "network_used": False,
        "real_execution": False,
    }


def render_contract_verification_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Vérification du contrat de replay ciblé",
        "",
        f"- Statut : **{payload.get('status')}**",
        f"- Digest contrat : **{'OK' if payload.get('contract_digest_ok') else 'NON'}**",
        f"- Lien vers le plan courant : **{'OK' if payload.get('experiment_link_ok') else 'NON'}**",
        f"- Sources déclarées : **{payload.get('declared_source_count', 0)}**.",
        f"- Sources vérifiées : **{payload.get('verified_source_count', 0)}**.",
        "- Vérification schéma/fichiers uniquement : aucune ligne économique lue.",
        "",
        "## Research Lab",
        "",
        "| Fichier | Taille attendue | Taille réelle | État |",
        "|---|---:|---:|---|",
    ]
    for item in payload.get("research_lab", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('relative_path')}` | {item.get('expected_size')} | "
            f"{item.get('actual_size')} | {item.get('status')} |"
        )
    lines.extend(
        [
            "",
            "## SQLite",
            "",
            "| Base | Table | État |",
            "|---|---|---|",
        ]
    )
    for item in payload.get("sqlite", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('database')}` | `{item.get('table')}` | {item.get('status')} |"
        )
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    lines.extend(["", "## Erreurs", ""])
    lines.extend([f"- `{item}`" for item in errors] or ["- Aucune."])
    lines.extend(["", "## Avertissements", ""])
    lines.extend([f"- `{item}`" for item in warnings] or ["- Aucun."])
    lines.extend(
        [
            "",
            "> `READY` signifie uniquement que le contrat correspond encore au plan courant et que ses fichiers/schémas existent. Cela ne prouve aucun PnL ni aucun edge.",
            "",
        ]
    )
    return "\n".join(lines)


def write_contract_verification(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    payload = verify_replay_input_contract(resolved)
    json_path = resolved / CURRENT_CONTRACT_VERIFICATION
    md_path = resolved / CURRENT_CONTRACT_VERIFICATION_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_contract_verification_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


__all__ = [
    "CURRENT_CONTRACT_VERIFICATION",
    "CURRENT_CONTRACT_VERIFICATION_MD",
    "load_current_contract",
    "render_contract_verification_markdown",
    "verify_replay_input_contract",
    "write_contract_verification",
]
