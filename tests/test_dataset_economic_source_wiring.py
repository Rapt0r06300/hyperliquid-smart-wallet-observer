from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_economic_objective_campaigns.py"


def test_canonical_runner_fails_closed_to_copy_vault_scope() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "assert_execution_disabled()" in text
    assert 'active_families != frozenset({"copy_vault"})' in text
    assert '"lead_lag", "cross_venue_dislocation_v2"' in text
    assert '"start_collection": False' in text or "start_collection=False" in text
    assert '"paper_read_only": True' in text
    assert '"real_execution": False' in text
    assert "/exchange" not in text.casefold()


def test_copy_vault_path_uses_causal_fills_and_observed_hyperliquid_books() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "copy_vault_executable.cluster_metaorders" in text
    assert "copy_vault_executable.load_observed_books" in text
    assert "copy_vault_executable.select_causal_protocol_inputs" in text
    assert "evaluate_frozen" in text
    assert "calibrate_train_only" in text
    assert "temporal_evidence" in text
    assert "lead_lag_shadow" not in text
    assert "cross_tool" not in text
    assert "load_certified_atomic_series" not in text


def test_dataset_adapter_marks_only_copy_vault_as_consumed() -> None:
    text = (ROOT / "tools" / "run_dataset_economic_campaigns.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert 'active_families=("copy_vault",)' in text
    assert "lead_consumed=()" in text
    assert "cross_consumed=()" in text
    assert '"lead_lag": "DISABLED_BY_SCOPE"' in text
    assert '"cross_venue_dislocation_v2": "DISABLED_BY_SCOPE"' in text
    assert 'load_family_source_paths(data_root, "lead_lag")' not in text
    assert 'load_family_source_paths(root, "cross_venue")' in text


def test_copy_vault_train_research_variants_are_downstream_of_causal_entries() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    source = text.index("charger_evenements_lifecycle_avec_audit")
    for version in range(5, 10):
        assert f"explore_copy_vault_v{version}_" in text
        target = text.index(f'copy_raw["next_hypothesis_v{version}"]')
        assert source < target
