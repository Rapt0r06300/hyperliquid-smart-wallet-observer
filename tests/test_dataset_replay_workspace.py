from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.datasets.github_release_bridge import DatasetBridgeError
from hl_observer.datasets.replay_workspace import prepare_replay_workspace


def _make_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "pipeline_copie_reel.py").write_text("X = 1\n", encoding="utf-8")
    (tools / "backtest_dislocation_2jambes.py").write_text("Y = 2\n", encoding="utf-8")
    return root


def test_workspace_refuse_si_aucune_donnee_reconstruite(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    with pytest.raises(DatasetBridgeError, match="Aucune donnée reconstruite"):
        prepare_replay_workspace(root)


def test_workspace_copie_seulement_les_petits_outils(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    workspace = root / "data" / "hypersmart_datasets" / "materialized"
    (workspace / "runtime" / "data").mkdir(parents=True)
    (workspace / "runtime" / "data" / "bbo_tape.jsonl").write_text("{}\n", encoding="utf-8")

    report = prepare_replay_workspace(root)
    assert report["status"] == "READY"
    assert report["paper_only"] is True
    assert report["real_execution"] is False
    assert (workspace / "tools" / "pipeline_copie_reel.py").is_file()
    assert (workspace / "tools" / "backtest_dislocation_2jambes.py").is_file()

    saved = json.loads(
        (workspace / "runtime" / "reports" / "datasets" / "ESPACE_REPLAY.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["mainnet_execution"] is False
    assert saved["testnet_execution"] is False
