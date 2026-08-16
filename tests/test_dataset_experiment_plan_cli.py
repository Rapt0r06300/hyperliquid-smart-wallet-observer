from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.research_lab_stream import REPORT_JSON
from hl_observer.ops.dataset_experiment_plan import main


def _profile_only_workspace(root: Path) -> None:
    provenance = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(
        json.dumps({"source_release_id": 371149058, "suite": "research-lab-full", "selection_digest": "b" * 64}),
        encoding="utf-8",
    )
    report = root / REPORT_JSON
    report.write_text(
        json.dumps(
            {
                "schema": "hypersmart.research_lab_stream_profile.v2",
                "root": str(root),
                "files": [
                    {
                        "relative_path": "runtime/research_lab/a.jsonl",
                        "source_size": 10,
                        "timestamp_min_ms": 1000,
                        "timestamp_max_ms": 2000,
                        "complete": True,
                        "family_counts": {"lead_lag": 5},
                        "coin_counts": {"BTC": 5},
                        "metrics": {"net_pnl_usd": {"count": 5}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_cli_plan_experience_ecrit_les_rapports_sans_reseau(tmp_path: Path) -> None:
    _profile_only_workspace(tmp_path)

    code = main(
        [
            "--root",
            str(tmp_path),
            "--start-ms",
            "900",
            "--end-ms",
            "2100",
            "--family",
            "lead_lag",
            "--coin",
            "BTC",
            "--metric",
            "net_pnl_usd",
        ]
    )

    assert code == 0
    current = tmp_path / "runtime" / "reports" / "datasets" / "experiment_plans" / "CURRENT_EXPERIMENT_PLAN.json"
    assert current.is_file()
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["status"] == "READY"
    assert payload["research_lab"]["selected_file_count"] == 1
    assert payload["network_used"] is False
    assert payload["raw_data_copied"] is False


def test_cli_plan_experience_retourne_3_si_aucune_source_ne_correspond(tmp_path: Path) -> None:
    _profile_only_workspace(tmp_path)

    code = main(
        [
            "--root",
            str(tmp_path),
            "--family",
            "cross_venue_dislocation",
            "--coin",
            "ETH",
            "--metric",
            "net_pnl_usd",
        ]
    )

    assert code == 3


def test_cli_plan_experience_retourne_2_si_workspace_absent(tmp_path: Path) -> None:
    code = main(["--root", str(tmp_path / "absent")])
    assert code == 2
