from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.dataset_research_runner import (
    build_dataset_stage_plan,
    run_dataset_suite,
)
from hl_observer.ops.historical_analysis_suite import StageResult


def test_plan_branche_code_principal_sqlite_research_lab_et_donnees_du_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    data = tmp_path / "dataset"
    output = project / "runtime" / "reports" / "datasets" / "test"
    plan = build_dataset_stage_plan(project, data, output, full=True)
    commands = "\n".join(" ".join(stage.command) for stage in plan)
    keys = {stage.key for stage in plan}
    quality = next(stage for stage in plan if stage.key == "replay_data_quality")
    market = next(stage for stage in plan if stage.key == "market_truth_replay")
    sqlite_inventory = next(stage for stage in plan if stage.key == "sqlite_inventory")
    sqlite_catalog = next(stage for stage in plan if stage.key == "sqlite_research_catalog")
    research_probe = next(stage for stage in plan if stage.key == "research_lab_probe")
    research_full = next(stage for stage in plan if stage.key == "research_lab_full_stream")

    assert str(project / "tools" / "qualite_donnees_replay.py") in quality.command
    assert str(data) in quality.command
    assert str(data) in market.command
    assert str(data) in sqlite_inventory.command
    assert str(data) in sqlite_catalog.command
    assert str(data) in research_probe.command
    assert str(data) in research_full.command
    assert "hl_observer.ops.dataset_sqlite_inventory" in sqlite_inventory.command
    assert "hl_observer.ops.dataset_sqlite_research" in sqlite_catalog.command
    assert "hl_observer.ops.dataset_research_inventory" in research_probe.command
    assert "--max-gib-per-file" in research_probe.command
    assert "--max-gib-per-file" not in research_full.command
    assert "--network-read" not in commands
    assert "/exchange" not in commands
    assert {"walk_forward", "anti_overfit", "research_lab_full_stream"}.issubset(keys)


def test_plan_standard_fait_une_sonde_research_sans_lancer_le_scan_integral(tmp_path: Path) -> None:
    plan = build_dataset_stage_plan(
        tmp_path / "project",
        tmp_path / "dataset",
        tmp_path / "out",
        full=False,
    )
    keys = {stage.key for stage in plan}
    assert "sqlite_inventory" in keys
    assert "sqlite_research_catalog" in keys
    assert "research_lab_probe" in keys
    assert "research_lab_full_stream" not in keys
    assert "walk_forward" not in keys
    assert "anti_overfit" not in keys


def test_runner_ecrit_provenance_et_nouvelles_sources_avec_un_faux_executeur(tmp_path: Path) -> None:
    project = tmp_path / "project"
    data = tmp_path / "dataset"
    marker = data / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"source_release_id": 371149058}), encoding="utf-8")
    bbo = data / "runtime" / "data" / "bbo_tape.jsonl"
    bbo.parent.mkdir(parents=True, exist_ok=True)
    bbo.write_text("{}\n", encoding="utf-8")
    sqlite = data / "data" / "hl_observer.sqlite3"
    sqlite.parent.mkdir(parents=True, exist_ok=True)
    sqlite.write_bytes(b"sqlite-placeholder")
    research = data / "runtime" / "research_lab" / "continuous" / "run-a" / "historique" / "episodes.jsonl"
    research.parent.mkdir(parents=True, exist_ok=True)
    research.write_text("{}\n", encoding="utf-8")

    def fake(stage, *, root, output_dir):
        log = output_dir / f"{stage.key}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("ok\n", encoding="utf-8")
        return StageResult(
            key=stage.key,
            title=stage.title,
            status="PASSED",
            return_code=0,
            duration_seconds=0.01,
            log_path=str(log),
            message="ok",
            command=stage.command,
        )

    code, report, results = run_dataset_suite(
        project,
        data,
        suite="research-lab-full",
        stage_runner=fake,
    )
    assert code == 0
    assert len(results) == 16
    assert report.is_file()
    latest_json = (
        project
        / "runtime"
        / "reports"
        / "datasets"
        / "historical"
        / "research-lab-full"
        / "report_dataset_latest.json"
    )
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["dataset_suite"] == "research-lab-full"
    assert payload["source_release_id"] == 371149058
    assert payload["local_data_only"] is True
    assert payload["network_used"] is False
    assert payload["real_execution"] is False
    assert payload["dataset_source_summary"]["lead_lag"]["file_count"] == 1
    assert payload["dataset_source_summary"]["sqlite"]["file_count"] == 1
    assert payload["dataset_source_summary"]["research_lab"]["file_count"] == 1
    assert payload["sqlite_inventory"] is None
    assert payload["sqlite_research_catalog"] is None
    assert payload["research_lab_stream_profile"] is None
