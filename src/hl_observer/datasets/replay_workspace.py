from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from hl_observer.datasets.dataset_untrusted_guard import assert_workspace_safe
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

    # The public contract reports a missing/unprepared FULL/COLD workspace as a
    # dataset bridge error. Do this before the untrusted-content scan so callers
    # get the actionable reconstruction message instead of a lower-level guard
    # exception when there is simply nothing to inspect yet.
    runtime_data = workspace / "runtime" / "data"
    if not workspace.is_dir() or not runtime_data.is_dir():
        raise DatasetBridgeError(
            "Aucune donnée reconstruite dans l'espace FULL/COLD. "
            "Prépare d'abord le lot économique avec dataset_bridge."
        )

    # FULL/COLD is untrusted input. Once a workspace exists, reject symlinks/
    # reparse points and any script/executable supplied by the dataset before
    # executing a project tool. On a resumed workspace, only our two previously
    # copied tools are allowed, and only when their SHA-256 still matches the
    # current project source.
    trusted_tools: dict[str, str] = {}
    for name in REQUIRED_TOOL_FILES:
        source = project_root / "tools" / name
        if source.is_file():
            trusted_tools[f"tools/{name}"] = hashlib.sha256(source.read_bytes()).hexdigest()
    untrusted_guard = assert_workspace_safe(workspace, trusted_file_sha256=trusted_tools)

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
        "schema": "hypersmart.dataset_replay_workspace.v2",
        "project_root": str(project_root),
        "workspace_root": str(workspace),
        "runtime_data": str(runtime_data),
        "copied_tools": copied_tools,
        "untrusted_dataset_guard": untrusted_guard,
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