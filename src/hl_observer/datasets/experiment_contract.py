from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.experiment_plan import CURRENT_EXPERIMENT_PLAN

CONTRACT_DIR = Path("runtime") / "reports" / "datasets" / "experiment_contracts"
CURRENT_REPLAY_INPUT_CONTRACT = CONTRACT_DIR / "CURRENT_REPLAY_INPUT_CONTRACT.json"
CURRENT_REPLAY_INPUT_CONTRACT_MD = CONTRACT_DIR / "CURRENT_REPLAY_INPUT_CONTRACT.md"


def load_current_experiment_plan(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).resolve()
    path = resolved / CURRENT_EXPERIMENT_PLAN
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            "Plan d'expérience absent. Lance d'abord dataset_experiment_plan."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Plan d'expérience illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Plan d'expérience invalide.")
    if raw.get("status") != "READY":
        raise ValueError(
            f"Plan d'expérience non prêt: {raw.get('status')}. Aucun contrat exécutable n'est produit."
        )
    return raw


def _research_sources(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    research = plan.get("research_lab")
    if not isinstance(research, Mapping):
        return []
    result: list[dict[str, Any]] = []
    raw_files = research.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    for raw in files:
        if not isinstance(raw, Mapping):
            continue
        relative = str(raw.get("relative_path") or "").strip()
        if not relative:
            continue
        result.append(
            {
                "relative_path": relative,
                "timestamp_min_ms": raw.get("timestamp_min_ms"),
                "timestamp_max_ms": raw.get("timestamp_max_ms"),
                "complete": raw.get("complete") is True,
                "selection_uncertain": raw.get("selection_uncertain") is True,
            }
        )
    return sorted(result, key=lambda item: item["relative_path"].casefold())


def _sqlite_sources(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    sqlite = plan.get("sqlite")
    if not isinstance(sqlite, Mapping):
        return []
    result: list[dict[str, Any]] = []
    raw_selected = sqlite.get("selected")
    selected = raw_selected if isinstance(raw_selected, list) else []
    for raw in selected:
        if not isinstance(raw, Mapping):
            continue
        database = str(raw.get("database") or "").strip()
        table = str(raw.get("table") or "").strip()
        if not database or not table:
            continue
        filters = raw.get("filters") if isinstance(raw.get("filters"), Mapping) else {}
        result.append(
            {
                "database": database,
                "table": table,
                "safe_columns": [str(item) for item in (raw.get("safe_columns") or [])],
                "filters": {
                    "start_ms": filters.get("start_ms"),
                    "end_ms": filters.get("end_ms"),
                    "coin": filters.get("coin"),
                    "wallet": filters.get("wallet"),
                    "family": filters.get("family"),
                },
                "family_mode": raw.get("family_mode"),
                "read_only": True,
            }
        )
    return sorted(
        result,
        key=lambda item: (item["database"].casefold(), item["table"].casefold()),
    )


def build_replay_input_contract(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("status") != "READY":
        raise ValueError("Un contrat de replay exige un plan d'expérience READY")
    research = _research_sources(plan)
    sqlite = _sqlite_sources(plan)
    criteria = dict(plan.get("criteria") or {}) if isinstance(plan.get("criteria"), Mapping) else {}
    provenance = dict(plan.get("provenance") or {}) if isinstance(plan.get("provenance"), Mapping) else {}
    material = {
        "experiment_digest": plan.get("experiment_digest"),
        "criteria": criteria,
        "source_release_id": provenance.get("source_release_id"),
        "source_suite": provenance.get("suite"),
        "research": research,
        "sqlite": [
            {
                "database": item["database"],
                "table": item["table"],
                "filters": item["filters"],
                "family_mode": item["family_mode"],
            }
            for item in sqlite
        ],
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "hypersmart.replay_input_contract.v1",
        "contract_digest": digest,
        "experiment_digest": plan.get("experiment_digest"),
        "criteria": criteria,
        "provenance": {
            "status": provenance.get("status"),
            "source_release_id": provenance.get("source_release_id"),
            "source_repository": provenance.get("source_repository"),
            "suite": provenance.get("suite"),
            "selection_digest": provenance.get("selection_digest"),
        },
        "research_lab_sources": research,
        "sqlite_sources": sqlite,
        "research_source_count": len(research),
        "sqlite_source_count": len(sqlite),
        "source_count": len(research) + len(sqlite),
        "read_only": True,
        "network_used": False,
        "raw_data_embedded": False,
        "real_execution": False,
        "sql_strings_embedded": False,
    }


def render_contract_markdown(contract: Mapping[str, Any]) -> str:
    lines = [
        "# Contrat d'entrée du replay ciblé",
        "",
        f"- Contrat : `{contract.get('contract_digest')}`",
        f"- Expérience : `{contract.get('experiment_digest')}`",
        f"- Sources Research Lab : **{contract.get('research_source_count', 0)}**",
        f"- Sources SQLite : **{contract.get('sqlite_source_count', 0)}**",
        "- Contrat local/read-only : aucune ligne brute, aucune requête SQL libre, aucun réseau.",
        "",
        "## Research Lab",
        "",
        "| Fichier | Début | Fin | Complet | Incertain |",
        "|---|---:|---:|---|---|",
    ]
    for item in contract.get("research_lab_sources", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"| `{item.get('relative_path')}` | {item.get('timestamp_min_ms')} | "
            f"{item.get('timestamp_max_ms')} | {item.get('complete')} | {item.get('selection_uncertain')} |"
        )
    lines.extend(
        [
            "",
            "## SQLite",
            "",
            "| Base | Table | Filtres | Mode famille |",
            "|---|---|---|---|",
        ]
    )
    for item in contract.get("sqlite_sources", []):
        if not isinstance(item, Mapping):
            continue
        filters = item.get("filters") if isinstance(item.get("filters"), Mapping) else {}
        compact_filters = ", ".join(
            f"{key}={value}"
            for key, value in filters.items()
            if value is not None and value != ""
        ) or "aucun"
        lines.append(
            f"| `{item.get('database')}` | `{item.get('table')}` | `{compact_filters}` | `{item.get('family_mode')}` |"
        )
    lines.extend(
        [
            "",
            "> Ce contrat décrit les entrées autorisées d'un replay futur. Il ne lance rien et ne constitue pas une preuve de rentabilité.",
            "",
        ]
    )
    return "\n".join(lines)


def write_replay_input_contract(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    plan = load_current_experiment_plan(resolved)
    contract = build_replay_input_contract(plan)
    directory = resolved / CONTRACT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    digest = str(contract["contract_digest"])
    json_path = directory / f"contract_{digest[:16]}.json"
    md_path = directory / f"contract_{digest[:16]}.md"
    json_text = json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_contract_markdown(contract)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    (resolved / CURRENT_REPLAY_INPUT_CONTRACT).write_text(json_text, encoding="utf-8")
    (resolved / CURRENT_REPLAY_INPUT_CONTRACT_MD).write_text(markdown, encoding="utf-8")
    return json_path, md_path, contract


__all__ = [
    "CONTRACT_DIR",
    "CURRENT_REPLAY_INPUT_CONTRACT",
    "CURRENT_REPLAY_INPUT_CONTRACT_MD",
    "build_replay_input_contract",
    "load_current_experiment_plan",
    "render_contract_markdown",
    "write_replay_input_contract",
]
