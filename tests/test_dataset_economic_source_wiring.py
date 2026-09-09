from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_economic_objective_campaigns.py"


def test_full_cold_lead_lag_utilise_toutes_les_sources_manifestees() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "is_dataset_workspace(root)" in text
    assert 'load_family_source_paths(root, "lead_lag")' in text
    assert "dataset_manifest_source_count" in text
    assert "dataset_source_manifest" in text
    # Hors workspace FULL/COLD, le comportement historique doit rester disponible.
    assert "lead_lag_shadow.selectionner_sources(" in text
    assert "max_history_sources=max(0, int(lead_history_sources))" in text


def test_lead_lag_v3_est_branche_sur_tape_l2_trades_et_latence_mesuree() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "replay_lead_lag_queue_maker" in text
    assert "select_aligned_bbo_sources" in text
    assert "candidates=selected_lead_sources" in text
    assert "load_aligned_binance_trade_tape" in text
    assert "detect_rolling_shocks" in text
    assert "load_market_microstructure_event_windows" in text
    assert 'int(shock["trigger_ts_ms"])' in text
    assert "for shock in [*lead_shocks, *diagnostic_shocks]" in text
    assert 'microstructure_meta["frozen_shock_count"]' in text
    assert "load_runtime_latency_evidence(root)" in text
    assert 'lead_raw["maker_queue_candidates"]' in text
    assert 'lead_raw["maker_queue_replay"]' in text
    assert 'lead_raw["lead_lag_microstructure_history"]' in text
    assert 'lead_raw["lead_lag_source_alignment"]' in text
    assert text.index('lead_raw["maker_queue_replay"]') < text.index(
        'lead_raw["next_hypothesis_v3"]'
    )


def test_lead_lag_canonique_utilise_un_gel_maker_distinct_du_legacy_taker() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    lead_section = text[text.index("selected_lead_sources =") : text.index("cross_data =")]

    assert "maker_protocol_signature()" in lead_section
    assert "load_train_microstructure_history(" in lead_section
    assert "training_selection_evidence_sha256" in lead_section
    assert "latency_evidence_sha256" in lead_section
    assert "evaluate_frozen_maker(" in lead_section
    assert "build_lead_lag_maker_contract(" in lead_section
    assert 'lead_raw["economic_contract"] = maker_economic_receipt' in lead_section
    assert 'lead_raw["executable_campaign"] = maker_evaluation' in lead_section
    assert lead_section.index("maker_protocol_signature()") < lead_section.index(
        "find_oldest_parameter_freeze("
    )
    assert lead_section.index("freeze_train_selected_parameters(") < lead_section.index(
        "evaluate_frozen_maker("
    )
    assert "candidates=selected_lead_sources if dataset_mode else None" not in lead_section


def test_cross_venue_utilise_uniquement_le_chargeur_atomique_certifie() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "load_certified_atomic_series(root)" in text
    assert "cross_tool.collecter_carnet_series(root)" not in text
    assert '"source_mode": CERTIFIED_CROSS_SOURCE_MODE' in text


def test_campagnes_dataset_restent_paper_et_sans_exchange() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "assert_execution_disabled()" in text
    assert '"HL_ENABLE_MAINNET_EXECUTION"' in text
    assert '"HL_ENABLE_TESTNET_EXECUTION"' in text
    assert "/exchange" not in text.casefold()


def test_copy_vault_v5_est_branche_sur_les_evenements_lifecycle_causaux() -> None:
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    assert "explore_copy_vault_v5_train" in text
    assert "charger_evenements_lifecycle_avec_audit" in text
    assert 'copy_raw["next_hypothesis_v5"]' in text
    assert text.index("charger_evenements_lifecycle_avec_audit") < text.index(
        'copy_raw["next_hypothesis_v5"]'
    )
