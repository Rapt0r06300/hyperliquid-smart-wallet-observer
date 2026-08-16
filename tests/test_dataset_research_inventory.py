from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.dataset_research_inventory import main


def _write_research(root: Path, rows: int = 5) -> Path:
    path = root / "runtime" / "research_lab" / "continuous" / "run-a" / "historique" / "episodes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps({"ts_ms": 1_780_000_000_000 + index, "family": "copy_vault", "net_pnl_usd": index})
            for index in range(rows)
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_cli_research_inventory_scanne_et_ecrit_les_rapports(tmp_path: Path) -> None:
    _write_research(tmp_path, rows=5)

    code = main(
        [
            "--root",
            str(tmp_path),
            "--heartbeat-seconds",
            "999",
            "--sample-every",
            "1",
        ]
    )

    assert code == 0
    json_path = tmp_path / "runtime" / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.json"
    md_path = tmp_path / "runtime" / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.md"
    assert json_path.is_file()
    assert md_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["complete_file_count"] == 1
    assert payload["lines"] == 5


def test_cli_research_inventory_peut_faire_un_scan_borne_et_reprenable(tmp_path: Path) -> None:
    _write_research(tmp_path, rows=10)

    code = main(
        [
            "--root",
            str(tmp_path),
            "--max-lines-per-file",
            "3",
            "--heartbeat-seconds",
            "999",
        ]
    )
    assert code == 0
    profile_path = tmp_path / "runtime" / "reports" / "datasets" / "RESEARCH_LAB_STREAM_PROFILE.json"
    first = json.loads(profile_path.read_text(encoding="utf-8"))
    assert first["partial_file_count"] == 1
    assert first["lines"] == 3

    code2 = main(["--root", str(tmp_path), "--heartbeat-seconds", "999"])
    assert code2 == 0
    second = json.loads(profile_path.read_text(encoding="utf-8"))
    assert second["complete_file_count"] == 1
    assert second["lines"] == 10


def test_cli_research_inventory_refuse_un_workspace_absent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "absent")]) == 2
