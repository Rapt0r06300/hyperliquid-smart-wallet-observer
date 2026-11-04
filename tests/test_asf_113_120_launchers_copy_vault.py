from __future__ import annotations

from pathlib import Path

import pytest

from tools.launcher_safety import audit_launcher_file, launcher_safety_receipt


ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = [
    ROOT / "LANCER_COLLECTEURS_COPY_VAULT.cmd",
    ROOT / "LANCER_LAB_QUANT_COPY_VAULT.cmd",
    ROOT / "LANCER_HYPERSMART.cmd",
    ROOT / "POUSSER-GITHUB-FORCE.cmd",
    ROOT / "ALINA_SYNC_COMPLETE.cmd",
]


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(113, 121)])
def test_launcher_inventory_is_read_only_and_fail_closed(task_id: str) -> None:
    del task_id
    receipt = launcher_safety_receipt(LAUNCHERS)
    assert receipt["status"] == "PROVEN"
    assert receipt["paper_read_only"] is True
    assert receipt["real_execution"] is False
    assert receipt["mutation"] is False
    assert receipt["launcher_count"] == 5
    assert receipt["fail_closed"] is False


@pytest.mark.parametrize(
    "text",
    [
        "@echo off\ngit push --force origin main\nexit /b 0\n",
        "@echo off\ngit reset --hard HEAD\nexit /b 0\n",
        "@echo off\ngit clean -fd\nexit /b 0\n",
        "@echo off\nREM missing safety markers\n",
    ],
)
def test_launcher_audit_rejects_destructive_or_incomplete_text(tmp_path: Path, text: str) -> None:
    path = tmp_path / "LANCER_HYPERSMART.cmd"
    path.write_text(text, encoding="utf-8")
    result = audit_launcher_file(path)
    assert result["status"] == "REJECTED"

