from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.research_lab_stream import REPORT_JSON
from hl_observer.ops.dataset_research_select import main


def _write_profile(root: Path) -> None:
    path = root / REPORT_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "hypersmart.research_lab_stream_profile.v1",
                "root": str(root),
                "files": [
                    {
                        "relative_path": "runtime/research_lab/a/episodes.jsonl",
                        "source_size": 1024,
                        "timestamp_min_ms": 1000,
                        "timestamp_max_ms": 2000,
                        "complete": True,
                        "checkpoint": "a.json",
                        "family_counts": {"copy_vault": 5},
                        "coin_counts": {"BTC": 5},
                        "metrics": {"net_pnl_usd": {"count": 5}},
                    },
                    {
                        "relative_path": "runtime/research_lab/b/working_set.jsonl",
                        "source_size": 2048,
                        "timestamp_min_ms": 3000,
                        "timestamp_max_ms": 4000,
                        "complete": True,
                        "checkpoint": "b.json",
                        "family_counts": {"lead_lag": 5},
                        "coin_counts": {"ETH": 5},
                        "metrics": {"edge_remaining_bps": {"count": 5}},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_cli_research_select_prepare_un_corpus_cible(tmp_path: Path) -> None:
    _write_profile(tmp_path)

    code = main(
        [
            "--root",
            str(tmp_path),
            "--start-ms",
            "900",
            "--end-ms",
            "2100",
            "--family",
            "copy_vault",
            "--coin",
            "BTC",
            "--metric",
            "net_pnl_usd",
        ]
    )

    assert code == 0
    current = (
        tmp_path
        / "runtime"
        / "reports"
        / "datasets"
        / "research_selections"
        / "CURRENT_RESEARCH_SELECTION.json"
    )
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["selected_file_count"] == 1
    assert payload["files"][0]["relative_path"].endswith("a/episodes.jsonl")
    assert payload["raw_events_copied"] is False


def test_cli_research_select_refuse_si_le_profil_n_existe_pas(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), "--family", "copy_vault"]) == 2


def test_cli_research_select_refuse_un_workspace_absent(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path / "absent")]) == 2
