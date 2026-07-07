from __future__ import annotations

from pathlib import Path

from hl_observer.runtime.session_logs import (
    CANONICAL_LOGS_TO_SEND_DIRNAME,
    prepare_fresh_simulation_logs,
)


def test_prepare_fresh_simulation_logs_archives_old_active_files_without_deleting(tmp_path: Path) -> None:
    root = tmp_path
    log_dir = root / "logs" / CANONICAL_LOGS_TO_SEND_DIRNAME
    log_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_append_only.jsonl").write_text('{"old": true}\n', encoding="utf-8")
    (log_dir / "hypersmart_ia_history.jsonl").write_text('{"old_ai": true}\n', encoding="utf-8")
    (log_dir / "simulation_fusion_runtime_latest.json").write_text('{"old_fusion": true}', encoding="utf-8")
    (log_dir / "wallet_mirror_journal.jsonl").write_text('{"old_mirror": true}\n', encoding="utf-8")
    (log_dir / "latest_loop_result.json").write_text('{"old_loop": true}', encoding="utf-8")
    (log_dir / "latest_decision_trace.json").write_text('[{"old_trace": true}]', encoding="utf-8")
    (log_dir / "latest_loop_input_diagnostics.json").write_text('{"old_diag": true}', encoding="utf-8")
    (log_dir / "latest_loop_report.md").write_text("# old loop\n", encoding="utf-8")
    (log_dir / "qa_observation_20260608_210558.jsonl").write_text('{"old_qa": true}\n', encoding="utf-8")
    (log_dir / "SESSION_MANIFEST.json").write_text('{"old_manifest": true}', encoding="utf-8")
    (log_dir / "archive_old_decisions.jsonl").write_text("old archive", encoding="utf-8")
    (log_dir / "runtime.sqlite3").write_text("do-not-touch", encoding="utf-8")

    report = prepare_fresh_simulation_logs(root)

    assert report.log_dir == log_dir
    assert report.manifest_json.exists()
    assert report.manifest_markdown.exists()
    assert (log_dir / "simulation_decisions_append_only.jsonl").read_text(encoding="utf-8") == ""
    assert (log_dir / "runtime.sqlite3").exists()
    archived_names = {path.name for path in report.archived_files}
    assert "simulation_decisions_append_only.jsonl" in archived_names
    assert "hypersmart_ia_history.jsonl" in archived_names
    assert "simulation_fusion_runtime_latest.json" in archived_names
    assert "wallet_mirror_journal.jsonl" in archived_names
    assert "latest_loop_result.json" in archived_names
    assert "latest_decision_trace.json" in archived_names
    assert "latest_loop_input_diagnostics.json" in archived_names
    assert "latest_loop_report.md" in archived_names
    assert "qa_observation_20260608_210558.jsonl" in archived_names
    assert "SESSION_MANIFEST.json" in archived_names
    assert "archive_old_decisions.jsonl" in archived_names
    assert "runtime.sqlite3" not in archived_names
    assert (report.archive_dir / "simulation_decisions_append_only.jsonl").read_text(encoding="utf-8") == '{"old": true}\n'
    assert not (log_dir / "hypersmart_ia_history.jsonl").exists()
    assert not (log_dir / "simulation_fusion_runtime_latest.json").exists()
    assert not (log_dir / "wallet_mirror_journal.jsonl").exists()
    assert (log_dir / "latest_loop_result.json").exists()
    assert (log_dir / "latest_decision_trace.json").exists()
    assert (log_dir / "latest_loop_input_diagnostics.json").exists()
    assert (log_dir / "latest_loop_report.md").exists()
    assert not (log_dir / "qa_observation_20260608_210558.jsonl").exists()


def test_prepare_fresh_simulation_logs_migrates_legacy_mojibake_folder(tmp_path: Path) -> None:
    root = tmp_path
    legacy = root / "logs" / "logs Ã  envoyer"
    legacy.mkdir(parents=True)
    (legacy / "simulation_snapshot_latest.json").write_text('{"legacy": true}', encoding="utf-8")

    report = prepare_fresh_simulation_logs(root)

    migrated = report.archive_dir / "legacy_mojibake_logs_dir" / "simulation_snapshot_latest.json"
    assert migrated.exists()
    assert migrated.read_text(encoding="utf-8") == '{"legacy": true}'
    assert (report.log_dir / "simulation_snapshot_latest.json").exists()
