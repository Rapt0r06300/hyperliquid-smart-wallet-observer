from __future__ import annotations

import json
import shutil
from pathlib import Path

from hl_observer.datasets.github_release_bridge import DatasetBridgeError

REQUIRED_TOOL_FILES = (
    "pipeline_copie_reel.py",
    "backtest_dislocation_2jambes.py",
)


def default_materialized_root(project_root: Path) -> Path:
    return project_root / "data" / "hypersmart_datasets" / "materialized"


def prepare_replay_workspace(
    project_root: Path,
    *,
    materialized_root: Path | None = None,
) -> dict[str, object]:
    project_root = project_root.resolve()
    workspace = (materialized_root or default_materialized_root(project_root)).resolve()
    runtime_data = workspace / "runtime" / "data"
    if not runtime_data.is_dir():
        raise DatasetBridgeError(
            "Aucune donnée reconstruite dans l'espace FULL/COLD. "
            "Prépare d'abord le lot économique avec dataset_bridge."
        )

    workspace_tools = workspace / "tools"
    workspace_tools.mkdir(parents=True, exist_ok=True)
    copied_tools: list[str] = []
    for name in REQUIRED_TOOL_FILES:
        source = project_root / "tools" / name
        if not source.is_file():
            raise DatasetBridgeError(f"Outil du projet introuvable: {source}")
        destination = workspace_tools / name
        shutil.copy2(source, destination)
        copied_tools.append(str(destination))

    report_dir = workspace / "runtime" / "reports" / "datasets"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "hypersmart.dataset_replay_workspace.v1",
        "project_root": str(project_root),
        "workspace_root": str(workspace),
        "runtime_data": str(runtime_data),
        "copied_tools": copied_tools,
        "paper_only": True,
        "real_execution": False,
        "mainnet_execution": False,
        "testnet_execution": False,
        "status": "READY",
    }
    report_path = report_dir / "ESPACE_REPLAY.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**report, "report_path": str(report_path)}
