import json

from hl_observer.research.research_context import build_research_context


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
    git_dir = tmp_path / ".git"
    (git_dir / "refs/heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    sha = "1" * 40
    (git_dir / "refs/heads/main").write_text(sha + "\n", encoding="utf-8")
    context = build_research_context(tmp_path)
    assert context["head"] == sha


def test_context_reports_semantic_candidates_filtered_before_llm(tmp_path):
    status = tmp_path / "runtime/codex_research/SEMANTIC_DISCOVERY_STATUS.json"
    status.parent.mkdir(parents=True)
    status.write_text(
        json.dumps(
            {
                "generated": 2000,
                "shortlisted": 12,
                "filtered_before_llm": 1988,
                "family": "lead_lag",
            }
        ),
        encoding="utf-8",
    )
    context = build_research_context(tmp_path, family="lead_lag")
    assert context["trial_accounting"]["semantic_candidates_filtered_before_llm"] == 1988
    assert "raw_records" not in context
    assert "raw_logs" not in context
