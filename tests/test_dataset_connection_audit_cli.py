from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.dataset_connection_audit import main


def _mark(root: Path) -> None:
    path = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_release_id": 371149058,
                "paper_read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )


def test_cli_connection_audit_ecrit_les_rapports_sur_workspace_valide(tmp_path: Path) -> None:
    _mark(tmp_path)
    source = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("{}\n", encoding="utf-8")

    code = main(["--root", str(tmp_path)])

    assert code == 0
    assert (tmp_path / "runtime" / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.json").is_file()
    assert (tmp_path / "runtime" / "reports" / "datasets" / "DATASET_CONNECTION_AUDIT.md").is_file()


def test_cli_connection_audit_refuse_un_dossier_sans_provenance(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path)]) == 2


def test_cli_connection_audit_refuse_un_workspace_absent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "absent")]) == 2
