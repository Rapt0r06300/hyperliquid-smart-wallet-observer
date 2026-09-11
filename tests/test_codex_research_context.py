import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hl_observer.research.process_memory import ProcessMemoryValidationError
from hl_observer.research.research_context import build_research_context

ROOT = Path(__file__).resolve().parents[1]


def _memory_record(record_id: str, provenance: str) -> dict:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "family": "lead_lag",
        "mechanism_signature": "test-mechanism",
        "context": ["normal"],
        "change_motif": "test",
        "outcome": "FAILURE",
        "evidence_count": 8,
        "confidence": 0.95,
        "failure_reason": "test failure",
        "success_evidence": None,
        "provenance": provenance,
        "certifying": False,
        "retest_condition": "new evidence",
    }


def _install_head(root: Path, sha: str) -> None:
    git_dir = root / ".git"
    (git_dir / "refs/heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs/heads/main").write_text(sha + "\n", encoding="utf-8")


def test_context_auto_selects_underworked_family_and_stays_compact(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    memory = tmp_path / "memory.jsonl"
    memory.write_text("", encoding="utf-8")
    context = build_research_context(
        tmp_path,
        family=None,
        ledger_path=ledger,
        process_memory_path=memory,
    )
    assert context["family"] in {
        "copy_vault",
        "lead_lag",
        "cross_venue_dislocation_v2",
    }
    assert context["head"] == "UNKNOWN"
    assert context["next_actions"]
    assert len(json.dumps(context, separators=(",", ":"))) < 6000
    assert context["network_io"] is False
    assert context["quota_policy"]["resume_source"] == "compact_context_only"
    assert context["quota_policy"]["full_history_scan"] is False
    assert context["quota_policy"]["raw_log_scan"] is False


def test_context_reads_exact_head_without_shelling_out(tmp_path):
    sha = "1" * 40
    _install_head(tmp_path, sha)
    context = build_research_context(tmp_path)
    assert context["head"] == sha


def test_context_reads_exact_head_from_linked_worktree_common_dir(tmp_path):
    worktree_git_dir = tmp_path / "git-meta/worktrees/codex"
    common_git_dir = tmp_path / "git-meta"
    worktree_git_dir.mkdir(parents=True)
    (common_git_dir / "refs/heads").mkdir(parents=True)
    (tmp_path / ".git").write_text(
        "gitdir: git-meta/worktrees/codex\n", encoding="utf-8"
    )
    (worktree_git_dir / "HEAD").write_text(
        "ref: refs/heads/codex-discovery-v32\n", encoding="utf-8"
    )
    (worktree_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    sha = "2" * 40
    (common_git_dir / "refs/heads/codex-discovery-v32").write_text(
        sha + "\n", encoding="utf-8"
    )

    context = build_research_context(tmp_path)

    assert context["head"] == sha


def test_context_reports_only_fresh_valid_canonical_runtime_data_bbo_surface(tmp_path):
    bbo = tmp_path / "runtime/data/bbo_synchro.jsonl"
    bbo.parent.mkdir(parents=True)
    bbo.write_text("{}\n", encoding="utf-8")

    context = build_research_context(tmp_path)

    assert "runtime/data/bbo_synchro.jsonl" in context["data_surface_hints"]

    bbo.write_text("not-json\n", encoding="utf-8")
    malformed = build_research_context(tmp_path)
    assert "runtime/data/bbo_synchro.jsonl" not in malformed["data_surface_hints"]

    bbo.write_text("{}\n", encoding="utf-8")
    stale = time.time() - 3600
    os.utime(bbo, (stale, stale))
    stale_context = build_research_context(tmp_path)
    assert "runtime/data/bbo_synchro.jsonl" not in stale_context["data_surface_hints"]


def test_context_reports_semantic_candidates_filtered_before_llm_for_exact_head(tmp_path):
    sha = "3" * 40
    _install_head(tmp_path, sha)
    status = tmp_path / "runtime/codex_research/SEMANTIC_DISCOVERY_STATUS.json"
    status.parent.mkdir(parents=True)
    status.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "head": sha,
                "families": {
                    "lead_lag": {
                        "family": "lead_lag",
                        "generated": 2000,
                        "shortlisted": 12,
                        "filtered_before_llm": 1988,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    context = build_research_context(tmp_path, family="lead_lag")
    assert context["trial_accounting"]["semantic_candidates_filtered_before_llm"] == 1988
    assert context["semantic_discovery"]["available"] is True
    assert "raw_records" not in context
    assert "raw_logs" not in context


def test_context_rejects_semantic_status_from_another_head(tmp_path):
    _install_head(tmp_path, "4" * 40)
    status = tmp_path / "runtime/codex_research/SEMANTIC_DISCOVERY_STATUS.json"
    status.parent.mkdir(parents=True)
    status.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "head": "5" * 40,
                "families": {
                    "lead_lag": {
                        "family": "lead_lag",
                        "generated": 2000,
                        "shortlisted": 12,
                        "filtered_before_llm": 1988,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    context = build_research_context(tmp_path, family="lead_lag")

    assert context["semantic_discovery"]["available"] is False
    assert context["trial_accounting"]["semantic_candidates_filtered_before_llm"] == 0


def test_context_rejects_duplicate_ids_across_historical_and_runtime_memory(tmp_path):
    historical = tmp_path / "docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl"
    historical.parent.mkdir(parents=True)
    historical.write_text(
        json.dumps(_memory_record("PM-DUP", "historical")) + "\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime-memory.jsonl"
    runtime.write_text(
        json.dumps(_memory_record("PM-DUP", "runtime")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProcessMemoryValidationError, match="duplicate record_id PM-DUP"):
        build_research_context(
            tmp_path,
            family="lead_lag",
            process_memory_path=runtime,
        )


def test_context_cli_runs_from_clean_isolated_interpreter():
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "tools/codex_research_context.py"), "--auto"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["network_io"] is False
    assert payload["quota_policy"]["resume_source"] == "compact_context_only"
