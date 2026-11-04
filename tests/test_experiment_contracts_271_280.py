from hl_observer.backtesting.copy_vault_experiment_controls import (
    delayed_data_falsification_receipt,
    disjoint_oos_after_tuning_receipt,
    hotpath_untouched_experiment_receipt,
    launcher_cost_ablation_link_receipt,
    launcher_version_freeze_receipt,
    net_improvement_freeze_receipt,
    neutral_benchmark_receipt,
    no_revenue_promise_receipt,
    selective_vs_all_copy_receipt,
    target_not_terminal_receipt,
)


def test_lch271_freezes_measured_net_improvement() -> None:
    row = {"freeze_id": "f1", "baseline_sha256": "b", "challenger_sha256": "c", "frozen": True, "net_improvement_bps": 1.2}
    assert net_improvement_freeze_receipt([row])["status"] == "PROVEN"
    row["net_improvement_bps"] = 0
    assert net_improvement_freeze_receipt([row])["status"] == "UNMEASURABLE"


def test_lch272_target_is_not_terminal() -> None:
    row = {"target_usd": 5.0, "target_is_terminal": False, "continuation_policy": "CONTINUE_RESEARCH"}
    assert target_not_terminal_receipt([row])["status"] == "PROVEN"
    row["target_is_terminal"] = True
    assert target_not_terminal_receipt([row])["status"] == "REJECTED"


def test_lch273_experiment_does_not_mutate_hot_path() -> None:
    row = {"hot_path_mutated": False, "lane": "RESEARCH_ONLY", "live_hot_path_sha256": "live", "experiment_sha256": "exp"}
    assert hotpath_untouched_experiment_receipt([row])["status"] == "PROVEN"
    row["hot_path_mutated"] = True
    assert hotpath_untouched_experiment_receipt([row])["status"] == "REJECTED"


def test_lch274_suggestion_cites_cost_ablation() -> None:
    row = {"suggestion_id": "s1", "cost_ablation_ref": "ablation:1", "costs_included": True}
    assert launcher_cost_ablation_link_receipt([row])["status"] == "PROVEN"
    assert launcher_cost_ablation_link_receipt([{"suggestion_id": "s1"}])["status"] == "UNMEASURABLE"


def test_lch275_compares_selective_and_all_variants() -> None:
    rows = [{"variant": "SELECTIVE", "corpus_manifest_sha256": "m", "costs_included": True, "net_result": 1}, {"variant": "ALL", "corpus_manifest_sha256": "m", "costs_included": True, "net_result": 0}]
    assert selective_vs_all_copy_receipt(rows)["status"] == "PROVEN"
    assert selective_vs_all_copy_receipt(rows[:1])["status"] == "UNMEASURABLE"


def test_lch276_oos_starts_after_tuning() -> None:
    row = {"tuning_end_ms": 10, "oos_start_ms": 20, "overlap": False, "oos_manifest_sha256": "m"}
    assert disjoint_oos_after_tuning_receipt([row])["status"] == "PROVEN"
    row["overlap"] = True
    assert disjoint_oos_after_tuning_receipt([row])["status"] == "REJECTED"


def test_lch277_launcher_version_is_frozen() -> None:
    row = {"launcher_version": "v1", "code_sha256": "c", "config_sha256": "cfg", "freeze_id": "f", "frozen": True}
    assert launcher_version_freeze_receipt([row])["status"] == "PROVEN"
    row["frozen"] = False
    assert launcher_version_freeze_receipt([row])["status"] == "UNMEASURABLE"


def test_lch278_delayed_data_falsifies_advantage() -> None:
    row = {"delay_ms": 200, "max_delay_ms": 100, "advantage_valid": False}
    assert delayed_data_falsification_receipt([row])["status"] == "PROVEN"
    row["advantage_valid"] = True
    assert delayed_data_falsification_receipt([row])["status"] == "REJECTED"


def test_lch279_strategy_beats_matched_neutral() -> None:
    row = {"strategy_net": 2, "neutral_net": 1, "same_corpus": True, "same_costs": True}
    assert neutral_benchmark_receipt([row])["status"] == "PROVEN"
    row["strategy_net"] = 0
    assert neutral_benchmark_receipt([row])["status"] == "REJECTED"


def test_lch280_launcher_makes_no_revenue_promise() -> None:
    row = {"claim_status": "NO_PROMISE", "text": "paper-only observation; no outcome is guaranteed"}
    assert no_revenue_promise_receipt([row])["status"] == "REJECTED"
    row["text"] = "paper-only observation; results require review"
    assert no_revenue_promise_receipt([row])["status"] == "PROVEN"
