from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.source_discovery import (
    FAMILY_SOURCE_MANIFEST,
    DATASET_PROVENANCE,
    source_manifest_summary,
    write_family_source_manifest,
)

REPORT_JSON = Path("runtime") / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.json"
REPORT_MD = Path("runtime") / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.md"

KNOWN_CONSUMERS: dict[str, str] = {
    "copy_vault": "economic_multi_source:copy_view",
    "lead_lag": "lead_lag_shadow:explicit_sources",
    "cross_venue": "economic_multi_source:cross_loader",
    "market_ticks": "dataset_research_runner:market_truth_replay",
    "replay": "dataset_research_runner:replay_stack",
    "logs": "dataset_research_runner:historical_log_stack",
    "sqlite": "sqlite_profiler+sqlite_research_source",
    "research_lab": "research_lab_stream",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _evidence_state(root: Path, group: str, count: int) -> dict[str, Any]:
    reports = root / "runtime" / "reports" / "datasets"
    if count <= 0:
        return {
            "state": "NO_SOURCE_IN_WORKSPACE",
            "evidence_paths": [],
            "message": "Aucune source de ce type dans ce workspace; rien n'est inventé.",
        }

    if group in {"copy_vault", "lead_lag", "cross_venue"}:
        coverage_path = reports / "SOURCE_CONSUMPTION_COVERAGE.json"
        coverage = _read_json(coverage_path)
        if coverage:
            families = coverage.get("families") if isinstance(coverage.get("families"), Mapping) else {}
            family = families.get(group) if isinstance(families, Mapping) else None
            status = family.get("status") if isinstance(family, Mapping) else None
            return {
                "state": "RUN_EVIDENCE_READY" if status in {"FULL", "PARTIAL"} else "RUN_EVIDENCE_PRESENT",
                "coverage_status": status,
                "evidence_paths": [str(coverage_path)],
            }
        return {
            "state": "WIRED_AWAITING_ECONOMIC_REPLAY",
            "evidence_paths": [],
            "message": "Le consumer existe mais aucun rapport de consommation n'a encore été produit dans ce workspace.",
        }

    if group == "sqlite":
        inventory = reports / "SQLITE_INVENTORY.json"
        catalog = reports / "SQLITE_RESEARCH_CATALOG.json"
        inventory_payload = _read_json(inventory)
        catalog_payload = _read_json(catalog)
        paths = [str(path) for path in (inventory, catalog) if path.is_file()]
        if inventory_payload and catalog_payload:
            return {
                "state": "RUN_EVIDENCE_READY",
                "evidence_paths": paths,
                "readable_database_count": inventory_payload.get("readable_database_count"),
                "research_table_count": len(catalog_payload.get("table_sources", {}) or {}),
            }
        return {
            "state": "WIRED_AWAITING_SQLITE_SCAN",
            "evidence_paths": paths,
        }

    if group == "research_lab":
        profile_path = reports / "RESEARCH_LAB_STREAM_PROFILE.json"
        profile = _read_json(profile_path)
        if profile:
            return {
                "state": "RUN_EVIDENCE_READY",
                "evidence_paths": [str(profile_path)],
                "scanned_gib": profile.get("scanned_gib"),
                "complete_file_count": profile.get("complete_file_count"),
                "partial_file_count": profile.get("partial_file_count"),
            }
        return {
            "state": "WIRED_AWAITING_STREAM_SCAN",
            "evidence_paths": [],
        }

    # These are consumed by canonical historical stages. Their detailed results live
    # in the per-run report under the code/project root, not inside every data workspace.
    return {
        "state": "WIRED_TO_HISTORICAL_STAGE",
        "evidence_paths": [],
        "message": "La source est reliée à une étape canonique du dataset_research_runner.",
    }


def build_connection_audit(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    provenance_path = resolved / DATASET_PROVENANCE
    provenance = _read_json(provenance_path)
    manifest_path = write_family_source_manifest(resolved)
    summary = source_manifest_summary(resolved)

    groups: dict[str, Any] = {}
    unhandled: list[str] = []
    pending_evidence: list[str] = []
    available_groups: list[str] = []
    for group, raw in summary.items():
        count = int(raw.get("file_count") or 0) if isinstance(raw, Mapping) else 0
        bytes_value = int(raw.get("bytes") or 0) if isinstance(raw, Mapping) else 0
        consumer = KNOWN_CONSUMERS.get(group)
        if count > 0:
            available_groups.append(group)
            if not consumer:
                unhandled.append(group)
        evidence = _evidence_state(resolved, group, count)
        state = str(evidence.get("state") or "UNKNOWN")
        if count > 0 and state.startswith("WIRED_AWAITING"):
            pending_evidence.append(group)
        groups[group] = {
            "file_count": count,
            "bytes": bytes_value,
            "consumer": consumer,
            "consumer_known": bool(consumer),
            **evidence,
        }

    provenance_ok = bool(
        provenance
        and int(provenance.get("source_release_id") or 0) == 371149058
        and provenance.get("real_execution") is not True
    )
    all_available_handled = not unhandled
    wiring_status = (
        "CONNECTED"
        if provenance_ok and all_available_handled
        else "PARTIAL"
        if provenance_ok
        else "NO_PROVENANCE"
    )
    evidence_status = "COMPLETE_FOR_AVAILABLE_SOURCES" if not pending_evidence else "PENDING_RUNS"
    return {
        "schema": "hypersmart.dataset_connection_audit.v1",
        "root": str(resolved),
        "source_release_id": provenance.get("source_release_id") if provenance else None,
        "provenance_path": str(provenance_path),
        "provenance_ok": provenance_ok,
        "source_manifest": str(manifest_path),
        "available_groups": available_groups,
        "unhandled_groups": unhandled,
        "pending_run_evidence_groups": pending_evidence,
        "wiring_status": wiring_status,
        "run_evidence_status": evidence_status,
        "all_available_groups_have_consumer": all_available_handled,
        "paper_read_only": True,
        "real_execution": False,
        "groups": groups,
    }


def render_connection_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Audit de raccordement de la bibliothèque FULL/COLD",
        "",
        f"- Raccordement : **{payload.get('wiring_status')}**",
        f"- Preuves d'exécution : **{payload.get('run_evidence_status')}**",
        f"- Provenance Release 371149058 : **{'OK' if payload.get('provenance_ok') else 'NON'}**",
        f"- Groupes présents sans consumer connu : **{len(payload.get('unhandled_groups') or [])}**",
        f"- Groupes branchés mais encore sans rapport d'exécution : **{len(payload.get('pending_run_evidence_groups') or [])}**",
        "- Mode : **paper/read-only**, aucune exécution réelle.",
        "",
        "| Groupe | Fichiers | Consumer | État preuve |",
        "|---|---:|---|---|",
    ]
    groups = payload.get("groups")
    if isinstance(groups, Mapping):
        for name, raw in groups.items():
            if not isinstance(raw, Mapping):
                continue
            lines.append(
                f"| {name} | {raw.get('file_count', 0)} | `{raw.get('consumer') or '-'}` | {raw.get('state')} |"
            )
    pending = payload.get("pending_run_evidence_groups") or []
    if pending:
        lines.extend(
            [
                "",
                "## Raccords qui attendent encore un run réel",
                "",
                *[f"- `{name}`" for name in pending],
            ]
        )
    unhandled = payload.get("unhandled_groups") or []
    if unhandled:
        lines.extend(
            [
                "",
                "## Sources présentes sans consumer connu",
                "",
                *[f"- `{name}`" for name in unhandled],
            ]
        )
    lines.extend(
        [
            "",
            "> `CONNECTED` signifie que chaque type de source présent possède un chemin de consommation explicite. Cela ne signifie pas qu'un edge est rentable ni qu'un replay a déjà validé un PnL positif.",
            "",
        ]
    )
    return "\n".join(lines)


def write_connection_audit(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    payload = build_connection_audit(resolved)
    json_path = resolved / REPORT_JSON
    md_path = resolved / REPORT_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_connection_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


__all__ = [
    "KNOWN_CONSUMERS",
    "REPORT_JSON",
    "REPORT_MD",
    "build_connection_audit",
    "render_connection_markdown",
    "write_connection_audit",
]
