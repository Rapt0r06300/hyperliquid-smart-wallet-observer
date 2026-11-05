from __future__ import annotations

import json
from pathlib import Path

from hl_observer.agent_tools.efficiency.context_bundle import ContextRequest, compile_context
from hl_observer.agent_tools.efficiency.experience_memory import ExperienceRecord, ExperienceStore
from hl_observer.agent_tools.efficiency.loop_guard import LoopGuard, should_rerun_test
from hl_observer.agent_tools.efficiency.model_routing import ExecutionTier, route_task
from hl_observer.agent_tools.efficiency.output_compactor import compact_output
from hl_observer.agent_tools.efficiency.parallel_reads import read_many
from hl_observer.agent_tools.efficiency.prompt_cache import build_stable_prefix
from hl_observer.agent_tools.efficiency.repo_index import build_incremental_index, load_index
from hl_observer.agent_tools.efficiency.telemetry import EfficiencyReceipt, estimate_tokens
from hl_observer.agent_tools.efficiency.test_impact import select_impacted_tests


def test_incremental_index_is_hashable_and_skips_data(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "src" / "module.py").write_text("import os\nclass Worker: pass\n", encoding="utf-8")
    (tmp_path / "data" / "safe.json").write_text("{\"safe\": true}", encoding="utf-8")
    index_path = tmp_path / "runtime" / "index.json"
    first = build_incremental_index(tmp_path, index_path=index_path)
    second = build_incremental_index(tmp_path, index_path=index_path)
    assert "src/module.py" in first.records
    assert "data/safe.json" not in first.records
    assert first.fingerprint == second.fingerprint
    assert load_index(index_path).fingerprint == first.fingerprint
    assert first.records["src/module.py"].symbols == ("Worker",)


def test_context_bundle_respects_budget_and_marks_changed_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    path = tmp_path / "src" / "module.py"
    path.write_text("class Worker:\n    pass\n" * 30, encoding="utf-8")
    index = build_incremental_index(tmp_path)
    bundle = compile_context(tmp_path, index, ContextRequest("fix Worker", ("src/module.py",), max_chars=40))
    assert bundle.files[0].path == "src/module.py"
    assert bundle.files[0].reason == "changed"
    assert bundle.estimated_chars <= 40


def test_stable_prefix_and_parallel_reads_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    prefix = build_stable_prefix(model_family="fast", policy_text="paper only", repository_fingerprint="abc", tool_manifest=("read", "read"))
    assert prefix.text.count("read") == 1
    results = read_many(tmp_path, ["a.txt", "../outside.txt"], max_workers=2)
    by_path = {result.path: result for result in results}
    assert by_path["a.txt"].content == "a"
    assert by_path["../outside.txt"].error == "PATH_OUTSIDE_ROOT"


def test_compactor_retains_failure_evidence() -> None:
    text = "\n".join([f"noise-{i}" for i in range(100)] + ["ERROR: root cause"] + [f"tail-{i}" for i in range(100)])
    result = compact_output(text, max_chars=300, max_lines=20)
    assert result.truncated is True
    assert "ERROR: root cause" in result.compacted
    assert len(result.original_sha256) == 64
    assert result.omitted_line_ranges


def test_test_impact_is_conservative(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_module.py").write_text("from src.module import VALUE\n", encoding="utf-8")
    impacted = select_impacted_tests(tmp_path, ["src/module.py"])
    assert impacted.full_suite_required is False
    assert impacted.impacted_tests == ("tests/test_module.py",)
    config = select_impacted_tests(tmp_path, ["pyproject.toml"])
    assert config.full_suite_required is True
    assert config.impacted_tests == ("tests/test_module.py",)
    absolute = select_impacted_tests(tmp_path, [tmp_path / "src" / "module.py"])
    assert absolute.impacted_tests == ("tests/test_module.py",)


def test_routing_loop_guard_and_test_rerun_policy() -> None:
    assert route_task("rename one local variable", ["src/a.py"]).tier is ExecutionTier.FAST
    assert route_task("audit security and migration", ["src/a.py"]).tier is ExecutionTier.DEEP
    guard = LoopGuard(max_steps=4, max_identical_actions=2)
    assert guard.observe("same", success=False).continue_running is True
    assert guard.observe("same", success=False).reason == "REPEATED_ACTION_WITHOUT_PROGRESS"
    assert should_rerun_test("test_a", source_fingerprint="new", previous_fingerprint="old", previous_status="PASS") is True
    assert should_rerun_test("test_a", source_fingerprint="same", previous_fingerprint="same", previous_status="PASS") is False


def test_experience_memory_reuses_only_matching_records(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path / "experience.jsonl")
    store.append(ExperienceRecord("pytest import failure", "fixed", ("inspect import",), ("src/a.py",), "hash"))
    store.append(ExperienceRecord("unrelated deployment", "deferred"))
    matches = store.retrieve("pytest import failure", top_k=1)
    assert len(matches) == 1
    assert matches[0].outcome == "fixed"


def test_efficiency_receipt_is_deterministic_and_honest() -> None:
    receipt = EfficiencyReceipt(task_id="t1")
    receipt.record_context(input_chars=100, cached=True)
    receipt.output_chars = 20
    payload = receipt.finalize()
    assert payload["input_tokens_estimate"] == estimate_tokens(100)
    assert payload["cached_prefix_hits"] == 1
    assert payload["paper_read_only"] is True
    assert payload["real_execution"] is False
    assert len(payload["receipt_sha256"]) == 64
    json.dumps(payload, sort_keys=True)
