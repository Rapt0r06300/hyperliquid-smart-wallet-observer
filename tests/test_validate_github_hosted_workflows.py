from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "validate_github_hosted_workflows_test",
        ROOT / "tools" / "validate_github_hosted_workflows.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_firewall_rejects_reachable_legacy_lfs_workflow_dispatch(
    tmp_path, monkeypatch
) -> None:
    workflow = tmp_path / "worker.yml"
    workflow.write_text(
        """name: worker
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: gh workflow run clone-payload-lfs-mirror.yml
""",
        encoding="utf-8",
    )
    module = _module()
    monkeypatch.setattr(sys, "argv", ["validator", "--root", str(tmp_path)])
    with pytest.raises(SystemExit, match="LEGACY_LFS_WORKFLOW_FORBIDDEN"):
        module.main()


def test_firewall_rejects_legacy_lfs_workflow_file_even_without_known_command(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "clone-payload-lfs-mirror.yml").write_text(
        "name: legacy\njobs: {}\n", encoding="utf-8"
    )
    module = _module()
    monkeypatch.setattr(sys, "argv", ["validator", "--root", str(tmp_path)])
    with pytest.raises(SystemExit, match="LEGACY_LFS_WORKFLOW_FORBIDDEN"):
        module.main()
