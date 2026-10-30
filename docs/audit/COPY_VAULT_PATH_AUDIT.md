# Audit des chemins Copy-Vault

Audit déterministe, lecture seule. Une absence de reachability statique est une revue à faire, pas une preuve d'orphelin.

- Modules audités : **2256**
- Entrypoints référencés : **64**
- Modules atteignables depuis les launchers/workflows : **512**
- Cycles détectés : **10**
- Groupes de doublons AST exacts : **3**
- Suppression automatique : **0**

## Lanceurs et workflows

| Entrypoint | Canonique | Modules seeds | Scripts Python |
|---|---:|---:|---|
| `.github/workflows/advance-analysis-stage.yml` | non | 0 | `tools/advance_analysis_stage.py`, `tools/phase_gate.py`, `tools/publish_main_commit.py` |
| `.github/workflows/alina-canonical-closure-report.yml` | non | 1 | `tools/build_closure_report.py`, `tools/enrich_closure_data_exploitability.py`, `tools/generate_gate_registry.py`, `tools/publish_main_commit.py`, `tools/validate_closure_receipt.py`, `tools/validate_gate_registry.py` |
| `.github/workflows/alina-capsule-cleanup.yml` | non | 0 | `tools/prune_verified_recovery_capsule.py` |
| `.github/workflows/alina-git-code-sync-tests.yml` | non | 0 | `tools/alina_git_code_sync.py` |
| `.github/workflows/alina-operator-dispatch.yml` | non | 0 | `tools/publish_main_commit.py` |
| `.github/workflows/alina-operator-intent.yml` | non | 0 | `tools/publish_main_commit.py`, `tools/validate_operator_status.py` |
| `.github/workflows/alina-restore-safe-regression.yml` | non | 0 | `tools/restore_alina.py`, `tools/sync_complete_clone.py`, `tools/unpack_verified_safe.py`, `tools/verify_safe_corpus_partition.py` |
| `.github/workflows/analysis-stage-controller.yml` | non | 0 | `tools/advance_analysis_stage.py`, `tools/auto_advance_analysis.py`, `tools/finalize_analysis_drain.py`, `tools/publish_main_commit.py` |
| `.github/workflows/backfill-exact-trade-counts.yml` | non | 0 | `tools/backfill_exact_trade_counts.py`, `tools/build_catalog_metrics.py`, `tools/check_dataset_quality.py` |
| `.github/workflows/backfill-global-unique-trade-counts.yml` | non | 0 | `tools/backfill_exact_trade_counts.py`, `tools/backfill_global_unique_trade_counts.py`, `tools/build_catalog_metrics.py`, `tools/check_dataset_quality.py` |
| `.github/workflows/backfill-replay-compatibility.yml` | non | 0 | `tools/backfill_replay_compatibility.py`, `tools/build_catalog_metrics.py`, `tools/build_quarantine_audit.py`, `tools/build_replay_compatibility_reasons.py`, `tools/check_dataset_quality.py`, `tools/enforce_safe_replay_invariant.py`, `tools/index_run_manifest.py`, `tools/rebase_disjoint_catalog_publication.py`, `tools/replay_compatibility.py`, `tools/replay_receipt_publish.py` |
| `.github/workflows/cablage-drift-diagnostic.yml` | non | 2 | `tools/diagnose_cablage_drift.py` |
| `.github/workflows/campaign-resilience-receipt.yml` | non | 0 | `tools/publish_main_commit.py`, `tools/validate_campaign_resilience.py` |
| `.github/workflows/campaign-watchdog.yml` | non | 0 | `tools/campaign_watchdog.py`, `tools/publish_main_commit.py` |
| `.github/workflows/canonical-spec-verification.yml` | non | 1 | `tools/backfill_replay_compatibility.py`, `tools/build_closure_report.py`, `tools/build_replay_compatibility_reasons.py`, `tools/generate_gate_registry.py`, `tools/index_run_manifest.py`, `tools/manifest_policy.py`, `tools/publish_main_commit.py`, `tools/replay_compatibility.py`, `tools/validate_closure_receipt.py`, `tools/validate_event_intelligence_status.py`, `tools/validate_gate_registry.py`, `tools/validate_github_hosted_workflows.py` |
| `.github/workflows/catalog-partition-parity.yml` | non | 2 | `tools/audit_recovery_sources.py`, `tools/build_catalog_metrics.py`, `tools/build_quarantine_audit.py`, `tools/build_replay_compatibility_reasons.py`, `tools/check_dataset_quality.py`, `tools/enforce_safe_replay_invariant.py`, `tools/fetch_published_restore_inventory.py`, `tools/hydrate_recovery_assets.py`, `tools/index_run_manifest.py`, `tools/partitioned_data_index.py`, `tools/preservation_inventory.py`, `tools/probe_recovery_cache.py`, `tools/recheck_recovered_trade_reference.py`, `tools/recover_one_quarantined_shard.py`, `tools/reinspect_recovered_quarantine.py`, `tools/repair_stale_safe_classifications.py`, `tools/restore_alina.py`, `tools/sync_complete_clone.py`, `tools/verify_quarantine_recovery.py`, `tools/verify_recovery_bundle.py` |
| `.github/workflows/ci.yml` | non | 13 | `tools/ci_change_scope.py`, `tools/ci_shard.py` |
| `.github/workflows/cleanup-incomplete-v2-releases.yml` | non | 0 | `tools/audit_mixed_release_assets.py`, `tools/build_catalog_metrics.py`, `tools/build_quarantine_audit.py`, `tools/build_replay_compatibility_reasons.py`, `tools/check_dataset_quality.py`, `tools/prune_irrecoverable_dataset.py` |
| `.github/workflows/codex-discovery-v32.yml` | non | 5 | `tools/codex_research_context.py`, `tools/codex_semantic_discovery.py` |
| `.github/workflows/collect-and-publish-v2.yml` | non | 17 | `tools/check_dataset_quality.py`, `tools/collecter_bbo.py`, `tools/collecter_native_venues.py`, `tools/download_release_manifests.py`, `tools/index_run_manifest.py`, `tools/publish_dataset_v2_release.py` |
| `.github/workflows/collect-two-segment-resume-smoke.yml` | non | 1 | `tools/build_global_implementation_closure.py`, `tools/collect_resume_probe.py` |
| `.github/workflows/collector-replay-integrity-ci.yml` | non | 39 | `tools/build_dataset_v2_manifest.py`, `tools/collect_cloud_copy_vault.py`, `tools/collect_cloud_window.py`, `tools/collect_event_intelligence_v2.py`, `tools/collect_official_archive_backfill.py`, `tools/collecter_bbo.py`, `tools/collecter_native_venues.py`, `tools/collecter_userfills_vaults.py`, `tools/discover_cloud_collection_plan.py`, `tools/publish_dataset_v2_release.py` |
| `.github/workflows/control-phase.yml` | non | 0 | `tools/publish_main_commit.py`, `tools/set_phase.py` |
| `.github/workflows/copy-vault-v2-smoke.yml` | non | 10 | `tools/collect_cloud_copy_vault.py`, `tools/publish_dataset_v2_release.py` |
| `.github/workflows/coverage-parallel-probe.yml` | non | 0 | `tools/check_coverage_ratchet.py`, `tools/coverage_gap_report.py` |
| `.github/workflows/create-resumable-campaigns.yml` | non | 35 | `tools/apply_operator_controls.py`, `tools/collect_cloud_copy_vault.py`, `tools/collect_cloud_window.py`, `tools/collect_official_archive_backfill.py`, `tools/collecter_bbo.py`, `tools/collecter_native_venues.py`, `tools/discover_cloud_collection_plan.py`, `tools/freeze_copy_vault_selection.py`, `tools/freeze_market_shards.py`, `tools/import_operator_intents.py`, `tools/index_run_manifest.py`, `tools/manifest_policy.py`, `tools/phase_gate.py`, `tools/publish_main_commit.py`, `tools/refresh_pending_collect_campaign.py`, `tools/requeue_failed_analysis_campaign.py`, `tools/resolve_analysis_selection.py`, `tools/resumable_campaign.py`, `tools/set_phase.py`, `tools/supersede_copy_vault_fanout.py` |
| `.github/workflows/data-vault-ci.yml` | non | 0 | `tools/build_data_vault_snapshot.py`, `tools/data_vault_core.py`, `tools/publish_data_vault_snapshot.py`, `tools/restore_data_vault_snapshot.py`, `tools/update_data_vault_pointer.py` |
| `.github/workflows/dataset-health-receipt.yml` | non | 0 | `tools/build_copy_vault_coverage_receipt.py`, `tools/generate_health_receipt.py`, `tools/validate_campaign_resilience.py` |
| `.github/workflows/dataset-metrics-v2.yml` | non | 0 | `tools/build_catalog_metrics.py`, `tools/build_collection_metrics.py`, `tools/build_quarantine_audit.py`, `tools/build_replay_compatibility_reasons.py`, `tools/check_dataset_quality.py`, `tools/rebase_disjoint_catalog_publication.py` |
| `.github/workflows/dataset-quality-ci.yml` | non | 0 | `tools/check_dataset_quality.py`, `tools/index_run_manifest.py` |
| `.github/workflows/dataset-v2-smoke.yml` | non | 19 | `tools/collect_cloud_window.py`, `tools/publish_dataset_v2_release.py` |
| `.github/workflows/durable-restore-drill.yml` | non | 0 | `tools/restore_durable_state.py` |
| `.github/workflows/economic-scoreboard-receipt.yml` | non | 1 | `tools/export_economic_family_scoreboards.py`, `tools/publish_main_commit.py` |
| `.github/workflows/event-intelligence-ci.yml` | non | 1 | `tools/collect_event_intelligence_v2.py` |
| `.github/workflows/event-intelligence-coverage-registry.yml` | non | 0 | `tools/generate_event_intelligence_status.py`, `tools/validate_event_intelligence_status.py` |
| `.github/workflows/event-intelligence-status.yml` | non | 0 | `tools/generate_event_intelligence_status.py`, `tools/validate_event_intelligence_status.py` |
| `.github/workflows/github-hosted-runner-firewall.yml` | non | 0 | `tools/validate_github_hosted_workflows.py` |
| `.github/workflows/global-implementation-closure.yml` | non | 0 | `tools/build_analysis_frozen_coverage_receipt.py`, `tools/build_global_implementation_closure.py`, `tools/phase_gate.py`, `tools/summarize_global_closure_run.py`, `tools/verify_global_closure_phase.py` |
| `.github/workflows/hyperlab-ci.yml` | non | 1 | `tools/claude_tasks_scan.py` |
| `.github/workflows/local-l2-certification-tests.yml` | non | 12 | `tools/alina_quant_lab_console.py`, `tools/certify_local_l2.py`, `tools/copy_vault_safe_bridge.py` |
| `.github/workflows/migrate-campaign-manifests-v2.yml` | non | 0 | `tools/migrate_campaign_manifests_v2.py` |
| `.github/workflows/native-venues-github-validation.yml` | non | 20 | `tools/collect_cloud_window.py`, `tools/collecter_native_venues.py` |
| `.github/workflows/phase-request-controller.yml` | non | 0 | `tools/apply_phase_requests.py`, `tools/publish_main_commit.py`, `tools/seal_collection_cutoff.py`, `tools/set_phase.py` |
| `.github/workflows/portable-release-windows.yml` | non | 0 | `tools/wheelhouse_lock.py` |
| `.github/workflows/pre-run-001-100.yml` | non | 2 | — |
| `.github/workflows/pre-run-101-200.yml` | non | 2 | — |
| `.github/workflows/pre-run-201-300.yml` | non | 2 | — |
| `.github/workflows/pre-run-321-775.yml` | non | 5 | `tools/check_coverage_ratchet.py`, `tools/check_repo_governance.py` |
| `.github/workflows/pre-run-pnl-301-313.yml` | non | 1 | — |
| `.github/workflows/pre-run-pnl-314-320.yml` | non | 1 | — |
| `.github/workflows/promote-manifest.yml` | non | 0 | `tools/check_dataset_quality.py`, `tools/promote_manifest.py` |
| `.github/workflows/publish-restore-inventory.yml` | non | 0 | `tools/build_restore_inventory.py`, `tools/restore_alina.py` |
| `.github/workflows/quarantine-audit.yml` | non | 0 | `tools/build_catalog_metrics.py`, `tools/build_quarantine_audit.py`, `tools/check_dataset_quality.py`, `tools/index_run_manifest.py`, `tools/manifest_policy.py`, `tools/rebase_disjoint_catalog_publication.py`, `tools/repair_stale_safe_classifications.py` |
| `.github/workflows/reconcile-v2-catalog.yml` | non | 0 | `tools/build_catalog_metrics.py`, `tools/build_quarantine_audit.py`, `tools/build_replay_compatibility_reasons.py`, `tools/check_dataset_quality.py`, `tools/continuous_reconcile_backlog.py`, `tools/download_release_manifests.py`, `tools/index_run_manifest.py`, `tools/manifest_policy.py`, `tools/partitioned_data_index.py`, `tools/rebase_disjoint_catalog_publication.py`, `tools/select_reconciliation_batch.py` |
| `.github/workflows/recover-durable-publication.yml` | non | 1 | `tools/publish_dataset_v2_release.py`, `tools/recover_dataset_v2_capsules.py` |
| `.github/workflows/recovery-contract.yml` | non | 1 | `tools/publish_dataset_v2_release.py`, `tools/publish_local_recovery_snapshot.py`, `tools/recover_dataset_v2_capsules.py`, `tools/restore_alina.py`, `tools/sync_complete_clone.py`, `tools/unpack_verified_safe.py`, `tools/verify_safe_corpus_partition.py` |
| `.github/workflows/resumable-campaign-ci.yml` | non | 3 | `tools/augment_campaign_result.py`, `tools/resumable_campaign.py`, `tools/run_resumable_campaign.py` |
| `.github/workflows/resumable-campaign-controller.yml` | non | 2 | `tools/phase_gate.py`, `tools/resumable_campaign.py` |
| `.github/workflows/resumable-campaign-worker.yml` | non | 10 | `tools/augment_campaign_result.py`, `tools/discover_cloud_collection_plan.py`, `tools/persist_analysis_improvement.py`, `tools/persist_analysis_scoreboard.py`, `tools/phase_gate.py`, `tools/preserve_failed_publish_payload.py`, `tools/publish_dataset_v2_release.py`, `tools/publish_main_commit.py`, `tools/record_publication_receipt.py`, `tools/resumable_campaign.py`, `tools/run_resumable_campaign.py` |
| `.github/workflows/safe-corpus-distributed-verification.yml` | non | 0 | `tools/verify_safe_corpus_partition.py` |
| `.github/workflows/security-quality.yml` | non | 0 | `tools/check_repo_governance.py`, `tools/ci_change_scope.py` |
| `.github/workflows/source-capability-matrix.yml` | non | 17 | `tools/collecter_bbo.py`, `tools/collecter_native_venues.py`, `tools/generate_source_capabilities.py`, `tools/probe_source_capabilities.py`, `tools/validate_source_capabilities.py`, `tools/validate_source_rules.py` |
| `.github/workflows/uncompressed-size-v2.yml` | non | 0 | `tools/backfill_exact_trade_counts.py`, `tools/build_catalog_metrics.py`, `tools/measure_uncompressed_sizes.py`, `tools/merge_measured_catalog_patches.py` |
| `.github/workflows/validate-acceptance-registry.yml` | non | 0 | `tools/validate_acceptance_registry.py` |
| `.github/workflows/validate-dispatch-receipts.yml` | non | 0 | `tools/validate_dispatch_receipts.py` |
| `.github/workflows/validate-phase-receipts.yml` | non | 0 | `tools/validate_phase_receipts.py` |
| `.github/workflows/validate-publication-receipts.yml` | non | 0 | `tools/reconcile_publication_consistency.py`, `tools/validate_publication_receipts.py` |
| `ALINA_SYNC_COMPLETE.cmd` | non | 0 | `tools/sync_complete_clone.py` |
| `ALINA_SYNC_COMPLETE.sh` | non | 0 | `tools/sync_complete_clone.py` |
| `LANCER_COLLECTEURS_COPY_VAULT.cmd` | oui | 3 | `tools/watch_economic_collectors.py` |
| `LANCER_HYPERSMART.cmd` | oui | 99 | `tools/audit_moissonneur.py`, `tools/audit_report.py`, `tools/backfill_candles_vaults.py`, `tools/backfill_vault_fills.py`, `tools/collecter_allmids.py`, `tools/collecter_bbo.py`, `tools/collecter_carnet.py`, `tools/collecter_dispersion_venues.py`, `tools/collecter_lab_microstructure.py`, `tools/collecter_liquidations.py`, `tools/collecter_overshoots.py`, `tools/collecter_userfills_vaults.py`, `tools/collecter_vaults.py`, `tools/ecrire_carry_spot_inputs.py`, `tools/ecrire_copy_whitelist.py`, `tools/ecrire_marks_tous_coins.py`, `tools/fermer_carry_historique.py`, `tools/geler_prelim_copie.py`, `tools/lancer_research_parallel.py`, `tools/lanceur_tout_tester.py`, `tools/moissonner_10h.py`, `tools/pipeline_copie_reel.py`, `tools/portable_runtime.py`, `tools/rapport_quotidien.py`, `tools/reset_paper.py`, `tools/scorer_vaults.py`, `tools/sonde_confirmation_vaults.py`, `tools/verif_checkpoint_oos_shadow.py`, `tools/verifier_tout.py` |
| `LANCER_LAB_QUANT_COPY_VAULT.cmd` | oui | 6 | `tools/alina_quant_lab_console.py` |
| `POUSSER-GITHUB-FORCE.cmd` | oui | 0 | `tools/alina_git_code_sync.py` |
| `config/acceptance_criteria.yaml` | non | 5 | — |
| `config/settings.example.yaml` | non | 1 | — |
| `tools/boucle_collecteur.cmd` | non | 1 | — |
| `tools/build_full_folder_release.ps1` | non | 1 | — |
| `tools/create_portable_bundle.ps1` | non | 1 | `tools/portable_runtime.py` |
| `tools/find_locked_runtime_files.ps1` | non | 1 | — |
| `tools/hypersmart_simulation_poll_loop.ps1` | non | 2 | — |
| `tools/ia_train_loop.ps1` | non | 2 | — |
| `tools/install_portable_runtime.ps1` | non | 0 | `tools/portable_runtime.py`, `tools/wheelhouse_lock.py` |
| `tools/launchers/ANALYSER_BACKTESTS_REPLAYS.cmd` | non | 4 | — |
| `tools/launchers/ANALYSER_DONNEES_HYPERSMART.cmd` | non | 32 | `tools/run_dataset_economic_campaigns.py`, `tools/run_economic_objective_campaigns.py` |
| `tools/launchers/ANALYSE_HISTORIQUE_COMPLETE.cmd` | non | 1 | — |
| `tools/launchers/BACKUP_LOCAL_ALINA.cmd` | non | 0 | `tools/publish_local_recovery_snapshot.py` |
| `tools/launchers/CREER_ARCHIVE_PORTABLE.cmd` | non | 3 | — |
| `tools/launchers/DIAGNOSTIC_LANCEUR.cmd` | non | 1 | `tools/diagnostic_lanceur.py` |
| `tools/launchers/LANCER-CODEX-RESEARCH.cmd` | non | 21 | `tools/codex_research_context.py`, `tools/codex_semantic_discovery.py`, `tools/collecter_bbo.py`, `tools/run_dataset_economic_campaigns.py` |
| `tools/launchers/LANCER-RECHERCHE-14H.cmd` | non | 2 | `tools/collecter_lab_ctx.py`, `tools/collecter_lab_microstructure.py`, `tools/lancer_research_parallel.py`, `tools/recherche_14h.py` |
| `tools/launchers/LANCER-RECHERCHE-18H.cmd` | non | 2 | `tools/collecter_lab_ctx.py`, `tools/collecter_lab_microstructure.py`, `tools/recherche_18h.py` |
| `tools/launchers/LANCER-RECHERCHE-CONTINUE-ADMIN.cmd` | non | 1 | `tools/recherche_continue.py` |
| `tools/launchers/LANCER-RECHERCHE-CONTINUE.cmd` | non | 1 | `tools/recherche_continue.py` |
| `tools/launchers/LANCER_HYPERLAB.cmd` | non | 1 | — |
| `tools/launchers/LANCER_LABO.cmd` | non | 2 | `tools/collecter_lab_microstructure.py`, `tools/lancer_research_parallel.py`, `tools/verifier_lab_30min.py` |
| `tools/launchers/LANCER_LABO_180GO.cmd` | non | 4 | — |
| `tools/launchers/LANCER_MICRO.cmd` | non | 2 | `tools/collecter_lab_microstructure.py` |
| `tools/launchers/LANCER_OBJECTIF_4USD.cmd` | non | 26 | `tools/run_economic_objective_campaigns.py` |
| `tools/launchers/LANCER_REPLAY_176GO.cmd` | non | 2 | — |
| `tools/launchers/PREPARER_DONNEES_HYPERSMART.cmd` | non | 2 | — |
| `tools/launchers/PREPARER_EXPERIENCE_FULL_COLD.cmd` | non | 4 | — |
| `tools/launchers/RECETTE-LANCEUR.cmd` | non | 2 | — |
| `tools/launchers/RECETTE-WINDOWS.cmd` | non | 1 | `tools/recette_windows_smoke.py`, `tools/recherche_continue.py` |
| `tools/launchers/RESTORE_ALINA.cmd` | non | 0 | `tools/restore_alina.py` |
| `tools/launchers/RESTORE_ALINA.sh` | non | 0 | `tools/restore_alina.py` |
| `tools/launchers/VERIFIER_LAB_AUTONOME_ALINA.cmd` | non | 2 | `tools/alina_autonomous_lab.py` |
| `tools/launchers/VERIFIER_REPARER_L2_LOCAL.cmd` | non | 0 | `tools/certify_local_l2.py` |
| `tools/portable_env.cmd` | non | 0 | `tools/portable_runtime.py` |
| `tools/preparer_python_portable.cmd` | non | 0 | `tools/portable_runtime.py` |
| `tools/push_github_safe.ps1` | non | 0 | `tools/alina_git_code_sync.py` |
| `tools/run_pipeline.cmd` | non | 4 | `tools/analysis/_mechanism_scan.py`, `tools/analysis/_predictor_experiment.py`, `tools/analysis/_seg_analysis.py` |
| `tools/smoke_full_folder_installer.ps1` | non | 1 | — |
| `tools/start_hypersmart_simulation.ps1` | non | 4 | `tools/construire_calibration_edge.py`, `tools/measure_funding_gate.py`, `tools/resource_policy.py` |

## Classification

| Module | Classe | Justification |
|---|---|---|
| `hl_observer` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.__main__` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.accounting` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.accounting.fixed_point_core` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.accounting.overflow_boundary` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.accounting.position_adjusted_events` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.agent.dead_zones` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent.dead_zones_hypersmart` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent.fitness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent.improvement_loop` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent.sealed_verifier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent_tools.jsonl_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent_tools.manifest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent_tools.mcp_readonly` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.agent_tools.readonly_inspectors` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.agent_tools.schemas` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.alerts.coverage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.coverage_completeness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.coverage_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.durability` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.alerts.freshness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.local_alerts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.read_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.replacement_parity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.spine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.alerts.validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.analysis` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.analysis.closing_classifier` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.analysis.closing_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.copy_delay_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.entry_edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.exit_edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.followability` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.methodology_profiler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.negative_pnl_auditor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.opening_classifier` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.analysis.opening_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.opening_outcome` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.opening_patterns` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.opening_profitability` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.pnl_attribution` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.profit_patterns` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.trade_lifecycle` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.trader_playbook` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.v19_repo_matrix` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.analysis.wallet_style` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.api_governance` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.api_governance.per_venue_connection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.api_governance.reconciliation_throttle` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.api_governance.request_qos` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.api_governance.reserved_api_quota` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.api_governance.weighted_rate_limiter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.adverse_level_stress` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.asset_equivalence_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.basis_funding_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.churn_accounting` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.common_hedge_quantum` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.connector_reliability_premium` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.contract_equivalence_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.contract_multiplier_normalization` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.conversion_ttl` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.cross_source_comparator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.arbitrage.cross_venue_capacity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.cross_venue_contract` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.arbitrage.cross_venue_funding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.cross_venue_quote_skew` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.cross_venue_quotes_simultaneous` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.cross_venue_roundtrip` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.cross_venue_state_machine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.depeg_haircut` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.depth_reservation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.direction_imbalance_cap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.double_budget_reservation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.dual_health_barrier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.dual_venue_hedge_sim` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.emergency_residual_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.episode_close_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.episode_idempotency` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.executable_legs` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.arbitrage.execution_journal` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.failure_specific_retry` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.failure_taxonomy` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.fee_snapshot` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.fee_token_normalization` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.filled_quantity_hedge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.funding_adjusted_edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.gap_risk_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.hedge_reserve` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.hyperliquid_cex_spread_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.leg_idempotency` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.leg_sequencing_empirical` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.linear_inverse_normalization` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.liquidity_ownership` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.marginal_edge_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.market_order_price_protection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.max_acceptable_hedge_residual` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.minimum_notional_preflight` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.multi_venue_execution` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.arbitrage.nbbo_synthetique` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.numeraire_commun` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.opportunity_fingerprint` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.opportunity_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.opportunity_ranker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.optimal_notional_search` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.orderbook_depth_pricer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.orderbook_snapshot` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.orphan_inventory_state` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.pair_cooldown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.partial_asymmetry_precheck` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.path_cost_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.path_fee_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.per_leg_shortfall` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.persistent_unfinished_episodes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.pnl_decomposition` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.pre_submit_edge_recheck` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.profit_hysteresis` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.profit_ladder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.profitability_envelope` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.proportional_residual_hedge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.rate_oracle_fail_closed` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.read_before_retry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.repricing_tolerance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.residual_only_retry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.residual_timeout` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.resulting_price_ladder` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.rounding_residual_forecast` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.snapshot_invalidation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.spread_formula` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.stablecoin_conversion` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.state_machine_one_filled_one_rejected` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.symbol_normalizer` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.tick_lot_preflight` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.arbitrage.triangular_graph` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.triangular_measure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.triangular_opportunity_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.arbitrage.ws_price_discrepancy_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.artifacts` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.artifacts.extractor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.audit.cablage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.audit.couverture` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.audit.dette_cablage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.audit.mini_run_check` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.audit.pnl_convergence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.audit.pre_run_001_100` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.audit.pre_run_101_200` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.audit.simulation_realism_audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.autoscan` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.ab_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.book_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.cost_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.data_bus` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.entry_event_recorder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.execution_realism` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.experiment_runner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.ledger_replay_v9` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.materialized_cache` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.monte_carlo` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.multi_wallet_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.no_lookahead_guard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtest.optimize` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.pnl_from_logs` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.pnl_metrics_ext` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.replay_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.report_charts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.runner_contract` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.runtime_parity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtest.selectivity_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.trade_tick_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtest.walk_forward` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.ab_flag_replay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.anti_lookahead_pipeline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.anti_overfit_gate` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.arb_backtest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.backtest_live_parity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.boucle_objectif_replay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.carry_backtest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.carry_historical_backtest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.carry_scan_recorder` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.cointegration_measure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.copy_vault_book_loader` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_causal_selection` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_evidence` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_executable` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_execution_math` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_generalization` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_hypothesis_registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_instrument_metadata` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_local_lab` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_protocol` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_universe_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v21_frozen` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v4_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v5_lifecycle_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v6_balanced_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v7_exit_flow_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v8_entry_efficiency_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_v9_online_leader_quality_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_vnext_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.copy_vault_vnext_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.cost_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.cross_validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.cross_venue_certified` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.cross_venue_v3_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.cross_venue_v4_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.cross_venue_v5_experiment` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.cross_venue_v5_persistence_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.cross_venue_v6_coverage_union_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.economic_hypotheses_v3` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.economic_vnext_pack` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.edge_predictor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.execution_delay_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.execution_extras` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.execution_models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.execution_passive_agressive` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.execution_sim` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.experiment` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.experiment_harness` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.fade_liquidation_backtest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.fast_exact_comparison` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.features` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.fee_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.grid_market_maker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.honest_metrics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.hyperopt_local` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.infra_primitives` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.integrity_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.intrabar` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.labeling` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_bbo_repricing_train` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_book_confirmation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_causal_autopsy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_causal_diagnostic` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_causal_diagnostics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_causal_gap_compat` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_certified_backtest` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_certified_clock` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_evidence` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_maker_queue_train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_maker_timing_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_microstructure_confirmation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_multiasset_ranges` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_multiasset_scoring` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_multiasset_tape` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_multiasset_train` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_multitape` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_queue_analysis` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_queue_costs` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_queue_replay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_reference_residual` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_reference_residual_grid` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.lead_lag_shadow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_shadow_economics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_shadow_metrics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_shadow_temporal` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_source_alignment` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lead_lag_streaming_train` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lead_lag_taker_timing_train` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.liquidation_cascade` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.liquidation_edge_measure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.liquidation_net` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.liquidation_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lookahead_analysis` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.lookahead_differential` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.lookahead_guard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.maker_fill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.maker_rebate_decision` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.market_making_flow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.market_metrics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.market_signals` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.mean_reversion` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.mechanism_zoo` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.microstructure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.microstructure_extras` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.missed_fill_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.ml_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.ml_extras` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.mlops_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.monte_carlo` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.native_cross_venue_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.order_split_benefit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.overfit_selection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.pareto_front` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.partial_fill_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.perf_metrics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.perf_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.portfolio_risk` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.post_liquidation_direction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.promotion_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.purged_split` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.quality_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.quant_methods` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.queue_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.quoting_inside_spread` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.recherche_adaptative_stricte` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.recherche_arbitrage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.recherche_carry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.recherche_parallele` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.recherche_scenario` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.recursive_analysis` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.backtesting.recursive_bias_probe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.regime_detection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.regime_label` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.regime_models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.regime_wiring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.replay_doctor` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.replay_engine` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.replay_science` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.reporting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.reporting_extras` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.residual_alpha` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.risk_sizing` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.robust_selection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.robustesse_selection` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.robustness` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.robustness_protocol` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.runtime_guards` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.safety_defaults` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.safety_tools` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.scenario_db` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.scenario_grid` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.scenario_search` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.signal_processing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.slippage_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.sniper_horizon_curve` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.strategies_extra` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.stress_testing` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.survival_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.tombstones_backtesting` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.train_statistics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.validation_extras` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.validation_gates` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.validation_methods` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.backtesting.vault_replication` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.vectorized` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.backtesting.wallet_following_simulator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.calibration.brier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.confidence_buckets` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.emos` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.ledger_calibration_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.ledger_pnl_calibration` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.model_market` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.shadow_promote` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.calibration.shadow_runner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.capture.atomic_checkpoint` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.bounded_critical_queue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.critical_overflow_fail_closed` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.dependency_api_version_manifest` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.research_stream_shedding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.write_ahead_raw_journal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.capture.writer_lag_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.cli` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.cli_pkg_DISABLED` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.cli_pkg_DISABLED.tui_status` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.clitools` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.clitools.tui_status` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.clusters` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.clusters.cluster_signal_score` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.clusters.crowding_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.clusters.wallet_clusterer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.arbitrum_deposits` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.archive_s3` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.backoff` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_clock_sync` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_depth_book` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_depth_live` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_depth_orchestrator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_funding_history` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.binance_market_context` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.bitget_market_data` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.bybit_market_data` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.candle_backfill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.circuit_breaker` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.coin_universe` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.collect_all` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.collecte_fiable` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.collector` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.concurrent_fetch` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.copy_vault_checkpoint_tail` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.depth_capacity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.feed_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.funding_backfill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.gate_market_data` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.hf_recorder_multiplex` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.html_scraper` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.hyperliquid_clock_sync` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.hyperliquid_funding_history` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.l2_snapshot_cache` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.l4_capture` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.lead_lag_causal_checkpoints` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.market_capture_tiers` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.microstructure_recorder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.native_funding_history` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.native_market_tape` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.native_venue_coordinator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.native_venue_market` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.node_fills_backfill` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.okx_market_data` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.partitioned_tick_dataset` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.proxy_config` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.proxy_health` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.proxy_pool` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.public_fetcher` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.rate_limiter` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.research_recorder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.run_collect_all` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.shard_writer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.source_liveness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.stockage_brut_borne` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.subscription_universe` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.tick_dataset` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.trade_reconciliation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.trades_recorder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.twap_collector` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.userfills_live` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.vault_fills_backfill` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.vault_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.verrou_instance` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.collection.weight_budgeter` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.collection.window_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.collection.ws_first_plan` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.config` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.config.cross_venue_instruments` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.config.defaults` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.config.frais_venues` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.config.loader` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.config.local_rule_store` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.config.settings` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.connectors` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.connectors.base` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.connector_base` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.hyperliquid_readonly` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.market_data_connector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.paper_execution_connector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.public_research` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.read_only_market_connector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.connectors.standard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.control_plane` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.control_plane.campaign_adapters` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.control_plane.dispatch_receipt` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.control_plane.gate_registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.control_plane.module_pnl_proof` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.control_plane.phase_cli` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.control_plane.phase_controller` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.control_plane.phase_state` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.control_plane.resumable_campaign` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.control_plane.typed_events` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copy_fidelity.balance_replication` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.exec_cost_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.exec_cost_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.exec_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.fee_tiers` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.slippage_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_fidelity.tracking_error` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copy_mode.cooldown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.copy_latency_profiler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.copy_session_controller` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.multi_wallet_copy_session` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.reentry_cooldown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.wallet_mirror_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_mode.wallet_subscription_planner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.action_dependent_slippage_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.ambiguous_action_deny` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.attribution_after_netting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copy_vault.authoritative_close_direction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.auto_rebootstrap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.backlog_suspension` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.burst_sizing_snapshot` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.capture_leader_margin_mode` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.close_only_degradation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copy_vault.close_priority_queue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.coherent_snapshot_open` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.coin_concentration_ceiling` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.coin_metadata_per_fill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.collateral_change_rebaseline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.copy_intent_version_ref` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.copy_minimum_economic_size` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.copy_mode_by_source_execution` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.copyability_erosion_monitor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.copyability_kill_switch` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.cross_coin_atomicity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.delta_copy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.deposit_withdrawal_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.drift_ledger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.drop_stale_open_add` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.dual_sizing_cap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.dual_source_verification` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.epoch_local_checkpoint` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.equity_ratio_replication` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copy_vault.exactly_once_source_fill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.existing_position_conflict_rule` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.exposure_ratio_replication` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.fee_drag_ratio` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.fill_batching_window` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.flat_boundary_invariant` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.flip_as_two_operations` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.hard_multiplier_ceiling` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.hard_reduce_only_invariant` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.holding_time_compatibility` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.late_start_protection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_available_margin_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_execution_efficiency` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_leverage_ceiling` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_operational_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_price_quality_attribution` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_state_ttl` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.leader_state_versioning` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.liquidation_distance_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.max_concurrent_positions` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.max_state_skew` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.metadata_change_rebootstrap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.monotonic_state_rule` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.multi_vault_intent_netting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copy_vault.normalized_leverage_drift` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.order_level_fill_aggregation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.orphan_copy_sweeper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.parallel_state_read` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.partial_close_ratio` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.per_coin_serialization` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.per_vault_queue_cap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.per_vault_replication_shortfall` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.per_vault_sla` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.position_epoch_id` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.position_gap_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.position_state_hash` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.post_fill_source_confirmation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.post_rounding_notional_check` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.processing_queue_latency` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.reconnect_overlap_backfill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.reconnect_replay_suppression` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.replication_price_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.scale_in_reconstruction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.scale_out_reconstruction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.session_rebootstrap_markers` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.size_to_visible_liquidity_ratio` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.source_execution_style_profile` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.source_maker_taker_classifier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.source_state_contradiction_penalty` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.startup_position_bootstrap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.stream_cursor_persistence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.sync_confidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.target_exposure_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.turnover_penalty` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.vault_concentration_ceiling` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.vault_heartbeat` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_vault.ws_rest_disagreement_quarantine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.copy_conflict_resolver` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.copy_latency_profiler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.copy_session_controller` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.leader_markout` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copy_wallet.marks_source` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copy_wallet.mirror_candidate` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copy_wallet.multi_trader_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.proportional_sizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.slippage_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.structural_wallet_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.wallet_consensus` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.wallet_journal` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copy_wallet.wallet_mirror_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.wallet_rank_decay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copy_wallet.wallet_tier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.circuit_breaker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.consensus_leader_selector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.kelly_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.leader_pnl_tracker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.leader_proportional_sizing` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copying.leaderboard_autoselect` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copying.pipeline_integrator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.realtime_magic_score` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.copying.reports` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.runtime_v9_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.signal_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.simulation_pipeline` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.copying.v9_paper_pipeline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.viral_bot_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.copying.whale_consensus_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.core.causal_time` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.core.circuit_breaker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core.config` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core.error_handler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core.logging_config` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core.main` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.core.retry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.core.state_manager` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard.arbitrage_panel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard.copy_control_panel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard.copy_wallet_panel` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard.funding_panel` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard.loss_attribution_panel` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard.refactor_fusion_panel` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard.risk_flags_panel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard_truth` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dashboard_truth.dashboard_truth_audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard_truth.fake_data_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dashboard_truth.metric_provenance` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.data_contract` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.data_contract.adapter_conformance_suite` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.data_contract.expectations` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_contract.field_level_source_authority` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_contract.fixed_point_serialization_contract` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_contract.historical_live_schema_parity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_contract.schema_drift_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_contract.timestamp_unit_validator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.data_contract.unified_event` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_quality` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.data_quality.gate_v5` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_quality.guards` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.data_sources.acquisition_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources.base_provider` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.data_sources.fresh_data_plan` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources.historical_backfill_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources.market_backfill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources.official_archive_backfill` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.data_sources.provider_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.data_sources.warehouse_coverage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.dataset.canonical_dataset_version` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.channel_coverage_matrix` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.chunk_checksum` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.first_last_timestamp_coverage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.gap_heatmap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.parser_golden_corpus` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.raw_canonical_reproducibility` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.dataset.same_timestamp_retention` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.decision_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.decision_engine.local_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.decision_engine.noyau_unique` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.economics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.economics.assumptions` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.economics.copy_vault_metrics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.economics.families` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.economics.hardcode_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.economics.hyperliquid_fees` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.economics.numeric` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.economics.proof_binding` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.advanced_costs` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.bias_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.carry_edge_source` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.edge.copy_degradation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.cost_validation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.edge_calculator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.edge.edge_net_v12` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.edge_remaining` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.edge_source` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.edge.empirical_edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.exit_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.fair_value` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.fee_drag` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.maker_fee_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.margin_of_safety` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.measured_edge_table` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.edge.regime_volume` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.edge.signal_decay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.edge.tier_cost_budget` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.event_intelligence.archive` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.candidates` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.dataset_v2` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.direct_sources` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.economic_pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.event_price_discovery` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.external_event` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.features` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.event_intelligence.health` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.idea_coverage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.integration_registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.live_status` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.macro` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.event_intelligence.market_context` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.event_intelligence.market_features` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.module_bridges` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.outcomes` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.protocol` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.provenance` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.regimes` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.runtime_pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.scoreboard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.sequences` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.source_catalog` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.event_intelligence.worldmonitor` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.evidence` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.evidence.context_compaction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.evidence.decision_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.evidence.exit_evidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.evidence.no_trade_evidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exec_reconciliation.amend_vs_fill_race` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.balance_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.cancel_vs_fill_race` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.client_order_id_codec` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.continuous_position_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.cross_channel_fill_dedup` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.delta_fill_canonical` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.filled_quantity_lot_invariant` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.ghost_order_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.gtd_expiry_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.intent_vs_venue_id` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.missing_local_order_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.modify_after_partial` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.monotonic_order_state_version` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.overfill_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.parent_child_lineage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.stable_same_timestamp_ordering` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.unknown_execution_code_quarantine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.working_order_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exec_reconciliation.zombie_order_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.execution.anti_gaming` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution.freshness_cut` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution.live_executor_disabled` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution.maker_taker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.canonical_order_candidate` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.execution_core.capital_priority` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.central_budget_checker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.child_attribution_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.close_type_taxonomy` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.execution_core.controller_executor_separation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.cross_module_self_trade_prevention` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.execution_core.economic_invariant_suite` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.execution_core.economic_priority_allocator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.execution_core.enveloppe_capital_unique` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.execution_model_calibration` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.executor_lifecycle` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.execution_core.flip_aware_incremental_accounting` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.global_intent_netting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.execution_core.leg_coordination_fastpath` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.loss_burst_lock` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.persistent_position_hold` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.pluggable_fill_model_contract` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.portfolio_before_events` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.restart_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.safe_read_retry` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.execution_core.same_direction_intent_aggregation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.side_specific_degradation_lock` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.strategy_removal_purge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.strategy_stop_cancel_all` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.trading_intensity_warmup` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.virtual_subaccounts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.volatility_warmup` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.volume_share_slippage_stress` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.execution_core.warmup_barrier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exits` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exits.exit_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exits.exit_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exits.exit_policy_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exits.leader_exit_monitor` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exits.partial_take_profit` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exits.time_stop` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exits.trailing_stop` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.campagne_registre` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.carry_deux_jambes` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.cohort_paper_bridge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.cohortes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.copy_edge_forward` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.copy_edge_oos` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.cross_venue_conditions` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.cross_venue_events` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.execution_paper` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.exploratoire` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.historical_holdout` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.invariants` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.learning_memory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.liquidation_sentinels` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.metaorder_l2_tape` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.metaorder_shadow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.metaorder_toxicite` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.moteur_paper` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.oi_premium_crowding` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.promotion_candidats` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.rapid_alpha_shadow` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.rapport_raw` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.raw_shadow_variantes` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.reconciliation_paper` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.registre_essais` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.roi_estimateur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.runner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.experimental.selecteur_audit` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.experimental.signaux` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.experimental.vault_scoring` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.explorer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_dom_extractor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_importer` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.explorer.explorer_models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_network_probe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_parser` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_rate_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_revalidation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.explorer.explorer_source` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.explorer.explorer_transaction_tape` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.explorer.explorer_validation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.exports` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exports.csv_logging` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.exports.decision_csv_logger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.absorption` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.accumulate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.avwap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.basis` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.direction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.eat_flow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.ema_median_smoother` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.feature_drift` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.feature_multitimeframe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.feature_normalize` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.feature_store` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.feature_vector_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.funding` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.features.funding_aware` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.market` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.features.microstructure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.mid_stability` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.midpoint_jump_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.obi_delta` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.orderbook_imbalance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.quality_mode` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.rsi_overheat` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.scan_features` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.scan_features_schema` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.vol_sigma` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.features.volatility` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.feed_integrity.book_checksum` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.causal_snapshot_delta_persist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.clear_and_reseed` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.connection_sharding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.crossed_book_quarantine` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.feed_integrity.hot_subscribe_unsubscribe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.idle_socket_watchdog` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.invalid_size_quarantine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.late_message_window` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.missing_update_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.periodic_book_resnapshot` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.raw_message_journal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.raw_playback_harness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.receipt_timestamp` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.separate_recorder_process` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.sequence_validation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.subscription_ack_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.subscription_chunking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.feed_integrity.top_depth_coherence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.fees` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.fees.fee_tier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.fees.hyperliquid_fees` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.fees_model` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.fees_model.account_specific_fees` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.fees_model.fee_cache_invalidation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.fees_model.fee_recompute_reconciled` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.following.binance_anticipation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.following.copy_delay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.entity_consensus` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.following.fills_dedup` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.following.fills_sources` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.following.follow_decision_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.follow_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.follow_signal_builder` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.following.follow_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.leader_behavior` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.leader_scoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.leaderboard_follow_shortlist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.paper_follow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.position_follower` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.following.scoring_robuste` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.following.wallet_reconstruction` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.following.wallet_scoring_shortlist` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.freshness` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.freshness.freshness_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.freshness.horloges` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.freshness.signal_decay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.allocation_moteurs` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.apr_rotation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.arb_cout_all_in` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.arb_dislocation_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.arb_executable` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.arb_maker_study` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.base_convergence` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_allocation_nette` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_anti_churn` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_benchmark_gate` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_economie_position` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_entry_gates` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.carry_liquidation_risk` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_marge_dynamique` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_optimizer` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_ouverture_gates` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_paper_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.carry_portfolio` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.carry_position_lifecycle` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_positions_store` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_qualite_cross_venue` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_renfort` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.carry_rotation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.carry_timing_reglement` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.cross_venue_carry_judge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.cross_venue_carry_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.cross_venue_funding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.cross_venue_position` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.delta_neutral_carry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_arb_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_carry_economics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_cross_venue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_edge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_history_window` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_hors_plancher` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_microstructure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_opportunity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_persistence` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_poller` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_prediction` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_previsionnel` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_rate_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_runtime_cache` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_spread_perp_perp` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.funding_times` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.funding_zscore` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.snapshot_capture` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.funding.spike_detector` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.funding.spot_yield` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.gateway` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.gateway.local_source_gateway` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.gating` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.gating.filter_pipeline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperlab.__main__` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.calibration` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.collectors` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.cross_venue_exec` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.data_mesh_catalog` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.data_plane` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.dlq` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.lanes` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.leakage` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.live_ready` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.master` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.medallion_store` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.moteur_paper_unique` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.normalization` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.replay_parite` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.report` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.session` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperlab.strategies` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperlab.validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.hyperliquid.endpoints` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid.info_readonly` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperliquid.pagination_completeness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.hyperliquid.rate_limits` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid.rate_weights` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid.rest_info_client` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid.schemas` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.hyperliquid.ws_client` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.instrument_identity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.integration` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.integration.board_admission` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.deferred_features` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.funding_arb_optimizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.grinder_board_selector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.grinder_detectors` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.ia_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.leader_pipeline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.opportunity_board_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.ops_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.risk_quality_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.integration.scale_perf_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ledger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ledger.evidence` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.local_index` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.local_index.index_benchmark` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.local_index.index_config` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.local_index.query_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.local_index.wallet_index` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.candidate_factory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.dashboard_payload` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.decision_trace` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.loops.engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.input_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.memory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.loops.models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.mainnet_readonly_observer` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.mainnet_readonly_observer.observer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.market.calendar_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.classification` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.execution_constraints` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.fill_intensity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.flow_toxicity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.funding_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.hip3_markets` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.hlp_vault` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.liquidation_map` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market.liquidation_recorder` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market.mapping_unit` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market.market_impact` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.multi_venue_funding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.oracle_lag` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.spot_depth` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.universe_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market.venue_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market_data` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.market_data.exchange_fee_normalizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market_data.live_l2_service` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market_data.market_matcher` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.market_making` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.market_making.market_making_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market_signals` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.market_signals.market_cache` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.market_truth` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market_truth.executable_replay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market_truth.pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market_truth.truth_chain` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.market_truth.validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.markets.ccxt_universe` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.coin_metrics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.dex_discovery` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.liquidity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.market_discovery_ranking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.market_selector` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.realtime_liquidity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.scan_breadth` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.scanner` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.spread` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.universal_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.universe` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.markets.venues` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.markets.venues.bybit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.venues.models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.venues.multi_venue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.venues.okx` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.markets.venues.symbols` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.mega_cablage` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.mega_cablage.__main__` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.mega_cablage.copy_stage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.cross_venue_paper_stage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.cross_venue_stage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.mega_cablage.event_admission` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.feed_adapter` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.fill_ledger_stage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.lead_lag_stage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.mega_cablage.netting_routing_stage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.replay_driver` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.risk_stage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.mega_cablage.runner` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.metagraph` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.metagraph.metagraph_export` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.dataset` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.features` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.inference` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.ledger_extract` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.memory_store` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.model_panel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.promotion_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.refused_shadow_extract` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.sample_recorder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.shadow_analyst` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ml.train` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.train_cli` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ml.training_readiness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.modeling.linear_baseline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.modeling.model_refit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.modeling.probability_calibration` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.modeling.ridge_regression` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.models.common` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.monitoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.monitoring.monitor_output` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.net` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.net.doh_resolver` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.normalization` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.normalization.fill_aggregation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.normalization.fill_inference` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.normalization.fills` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.normalization.instrument_identity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.normalization.l2_book` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.normalization.market_events` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.normalization.normalize` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.normalization.positions` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.normalization.reconcile` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.opportunities` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.opportunities.fresh_opportunity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.analyser_session` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.archive_portable` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.autonomous_completion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.autonomous_research_brain` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.autonomous_research_guard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.autonomous_research_job` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.autonomous_research_job_router` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.autonomous_research_status` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.bounded_collection` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.budget_ram` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.campagne_alpha5` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.canonical_775_guard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.canonical_paper_intent_chain` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.clock_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.collecteur_registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.collector_lease` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.collector_runner` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.continuous_vault` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.critere_arret` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.daily_economic_certification` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.dataset_bridge` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_catalog` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_connection_audit` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_experiment_contract` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_experiment_contract_verify` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_experiment_plan` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_research_inventory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.dataset_research_runner` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_research_select` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.dataset_result_export` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.dataset_sqlite_inventory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.dataset_sqlite_research` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.dataset_workspace` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.decision_firehose` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.diagnostic_pnl` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.document_authority` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.echec_silencieux` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.economic_revalidation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.edge_decay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.entrypoint_topology` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.episode_capacity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.equity_canonique` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.expected_gain_ranking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.family_economic_job` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.final_economic_certification` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.full_folder_release` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.global_observer_pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.historical_analysis_suite` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.improvement_verdict` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.inventaire_release` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_alpha` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_audit` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_dashboard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_eta` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_flux` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_inventaire` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_metriques` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.lab_rapport` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lab_recherche` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.launcher_robustness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.lead_lag_causal_gap_diagnostic` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.lead_lag_evidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.lecons_du_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.loop_readiness` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.market_truth_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.marks_univers` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.moniteur_sante` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.operator_alerts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.paper_canonique` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.paper_pipeline_e2e` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.pnl_experiment_queue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.pnl_improvement_lab` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.port_owner` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.portable_audit_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.portable_clone` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.portable_clone_inventory` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.portable_release` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.portable_smoke` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.portable_transfer_proof` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_full_rehearsal` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_copy_321_395` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_cross_venue_466_545` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_final_546_775` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_guard_001_100` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_guard_101_200` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_guard_321_775` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.pre_run_lead_lag_396_465` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.preflight_lanceur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.premier_lancement` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.preuve_de_vie` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.producer_consumer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.quota_stockage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.rafraichisseur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.rapport_simple` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.recette_lanceur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.recommendation_tracking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.refusal_summary` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.registre_pids` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.release_artifacts` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.release_ready` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ops.runtime_contract` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.runtime_governance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.scope_flag_inventory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.self_hosted_control` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.self_hosted_return` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.session_catalog` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.session_harvest` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.session_verify` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.state_backup` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.strategie_candidat` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.strategy_monitoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.superviseur_collecteurs` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.supply_chain` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.tableau_sante_collecteurs` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.task_graph_contract` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ops.v2_dataset_bridge` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.validation_portable` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ops.verrou_lanceur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.optimization` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.optimization.anti_overfit_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.best_config_selector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.closed_ledger_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.config_optimizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.grid_search` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.hypothesis_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.out_of_sample_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.pnl_sweep` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.profit_optimizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.profit_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.random_search` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.strategy_tournament` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.threshold_optimizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.optimization.walk_forward_validator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.ambiguous_submit_recovery` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.amend_in_place` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.auto_market_exit_on_stop` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.batch_cancel_invalid_spread` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.cancel_confirmation_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.cancel_pending_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.dead_man_switch` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.deferred_cancel_unknown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.dust_accumulator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.dust_inventory_ledger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.expiry_releases_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.filled_order_delay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.fok_symmetric_arb` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.gtd_maker_expiry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.halt_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.hanging_order_distance_cancel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.hanging_order_tracker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.instrument_status_stream` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.ioc_hedge_leg` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.marketable_limit_mode` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.post_only_invariant` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.price_collar_source_hierarchy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.quantity_reduction_amend` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.sweep_protection_collar` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.order_lifecycle.time_in_force_matrix` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.order_lifecycle.ws_execution_path` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.order_lifecycle.ws_fill_recovery` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.paper.latency_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper.paper_executor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper.partial_fill_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper.pessimistic_fill_model` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.paper.rejection_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.auto_unstuck` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.barrier_calibration` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.can_buy_amount_simulator` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.paper_trading.canonical_execution` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.cross_venue_execution` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.delta_neutral_position` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.exec_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.execution_truth` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.fill_outcomes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.funding_payment_tracker` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.funding_settlement` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.fusion_paper_engine_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.hedge_reconciliation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.paper_trading.journal` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.latency_truth` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.paper_trading.liquidity_consumption` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.liquidity_route_simulator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.max_chase_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.mirror_paper_executor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.order_types` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.paper_connector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.paper_engine` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.position_tracking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.sl_tp` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.sltp_runtime` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.take_profit_stop_loss_local` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.trailing_stop_local` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.paper_trading.v26_exit_pipeline` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.paper_trading.vol_adjusted_barriers` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.patterns` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.patterns.pattern_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.perf` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.perf.hot_path_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.perf.latency_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.perf.latency_tracker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.pipeline` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.pipeline.v12_decision_pipeline` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.portabilite` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.position_lifecycle` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.position_lifecycle.reconstructor` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.product_benchmark` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.product_benchmark.feature_matrix` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.quoting.aggregate_market_ready_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.asymmetric_level_structures` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.batch_submit_maker_layers` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.fill_inside_spread_semantics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.hard_price_ceiling_floor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.l1_queue_position_tracker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.max_order_age` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.moving_price_bands` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.order_refresh_tolerance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.ping_pong_suppression` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.queue_value_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.target_price_for_quantity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.quoting.transaction_costs_in_target` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.clock_offset` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.data_quality_gap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.durable_dedup` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.event_identity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.realtime.feed_quality` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.realtime.feed_quality_primitives` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.realtime.feed_quality_reader` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.fresh_window_recommender` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.freshness_audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.freshness_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.global_rest_budget` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.realtime.global_ws_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.latency_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.low_latency_event_queue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.metrics_endpoint` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.multi_source_price_stream` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.raw_spool` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.realtime_health` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.recovery_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.source_health` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.realtime.tick_quality_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.ws_resilience` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime.ws_subscription_audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime_monitor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime_monitor.hot_watch_rotation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.realtime_monitor.ws_supervisor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.refactor_fusion` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.refactor_fusion.runner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.release` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.release.clean_archive` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.release.closeout` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.release.prompt_coverage` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.release.quality_gates` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.release.release_readiness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.replay` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.replay.data_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.reports` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.reports.daily_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.reports.latency_benchmark_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.reports.paper_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.abnormal_regime` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.acceptance` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.alpha_decay` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.alpha_factory` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.alpha_inputs` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.auto_discovery` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.basis_vs_latency` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.book_resiliency` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.canari` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.capacity_curve` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.capital_efficiency` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.cascade_warning` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.cex_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.clock_regimes` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.cost_model` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.cost_rigor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.cross_asset_leadlag` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.daily_report` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.data_honesty` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.data_integrity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.data_mesh` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.decision_explainer` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.deconfliction` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.deflated_sharpe` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.differentiel` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.domaines` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.drift_detector` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.empirical_law_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.empirical_memory` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.entity_resolution` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.execution_maker` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.exit_factory` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.experiment_design` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.experiment_infra` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.experiment_protocol` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.explain_cli` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.external_evidence_governance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.factory_families` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.factory_h24` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.fault_injection` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.feature_cache` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.feature_increment` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.fee_regime` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.forward_frozen` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.frontiere` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.github_dossier` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.github_graph` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.github_scan_plan` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.github_signals` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.hf_recorder` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.hidden_vs_twap` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.hl_binance_leadlag` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.hypothesis_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.idee` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.jsonl_stream` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.jugement_plus` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.leader_review_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.lecture_profonde` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.ledger_search` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.lineage` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.liquidation_flow` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.liquidity_consumption` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.local_llm_explainer` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.lois_mesurees` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.maker_tape_experience` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.maker_toxicity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.manual_research_classifier` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.manual_research_importer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.market_quality` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.medallion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.meta_gate` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.metaorder_hazard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.mine_de_code` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.mlofi` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.moissonneur_sujets` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.moteur` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.multi_venue` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.nonlinear_challenger` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.normalization_units` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.ofi_microprice` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.ollama_advisor` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.ollama_client` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.ollama_preflight` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.ollama_signal_rater` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.ollama_status` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.onchain_metrics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.order_intent` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.parallel_factory` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.portfolio` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.pre_run_201_220` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.pre_run_221_260` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.pre_run_261_300` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.price_discovery` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.process_memory` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.purged_cv` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.qa_rigor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.queue_model` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.rag_evidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.recette_economique` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.registre_hypotheses` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.rejeu_population` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.release_reproductibilite` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.replay_consistency` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.reproducibility` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.research_backlog` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.research_context` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.research_governance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.research_toolkit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.run_factory` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.runtime_loop` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.scan_resilience` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.scenario_rigor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.search_space` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.semantic_discovery` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.semantique` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.sizing` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.source_governance` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.sources` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.sources_plus` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.spread_transition` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.storage_partition` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.stream_reliability` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.symbol_master` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.trigger_map` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.universal_micro` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.validation_gates` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.validation_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.validation_stats` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.venue_capabilities` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.venue_readiness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.wallet_binance_anticipation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.wallet_copy_edge` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.wallet_fingerprint` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.wallet_info_ratio` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.wallet_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research.wallet_population` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research.wallet_thesis` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research.web_ouvert` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research_parallel` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research_parallel.execution` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.execution_honnete` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.isolation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.plugins` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.research_parallel.plugins._commun` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.plugins.lab_data` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research_parallel.plugins.vague1` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.research_parallel.registre` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.superviseur` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.research_parallel.validation` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.abnormal_spread_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.adaptive_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.adaptive_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.advanced_risk_manager` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.allocator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.atr_trailing_stop` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.breach_alerts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.budget_turnover` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.capital_allocation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.carry_risk_gates` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.circuit_breaker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.concentration_risk_detector` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.correlated_exposure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.directional_exposure` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.drawdown_scaling` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.drift_detection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.duplicate_order_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.engine_risk_budget` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.entry_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.equity_hard_stop_loss` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.exec_gates` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.gates` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.graded_halt` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.interrupteurs` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.kelly_leader_book` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.kelly_sizer` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.kelly_sizing` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.kill_switch` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.latency_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.liquidity_cliff_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.liquidity_guard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.loss_halts` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.margin_reserve` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.marginal_risk` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.market_manipulation_flags` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.max_hold_exit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.microstructure_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.order_rejection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.partial_fill_pair_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.portfolio_correlation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.portfolio_drawdown_kill_switch` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.portfolio_risk` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.portfolio_risk_limits` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.position_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.price_divergence_exit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.proportional_paper_sizer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.protections_v26` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.reconciliation_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.regime_guard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.risk_context` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.risk_engine` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.risk_engine_v3` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.risk_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.risk_gate_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.risk_panel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.safety_gates_mm` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.scale_out` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.session_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.session_pnl_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.side_lock` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.sizing_v2` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.slippage_guard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.slippage_guard_v2` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.slippage_model` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.stale_data_guard` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.stress_test` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.suspicious_liquidity_detector` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.tiered_copy_sizing` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk.tombstones` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.trade_budget` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk.trade_circuit_breaker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.trade_floor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk.var_cvar` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk_gates` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.risk_gates.account_equity_max_drawdown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk_gates.front_end_risk_pack` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk_gates.low_profit_module_lock` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk_gates.missing_mark_price_blocker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.risk_gates.quote_quantity_pretrade` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.risk_gates.reduce_only_close_check` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.routing.hedge_fallback_prevalidation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.hedge_route_warm_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.primary_secondary_hedge_route` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.route_graph` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.routing.route_regret_ledger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.route_score_shortfall_p95` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.route_score_timeout_p99` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.route_switching_cost` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.routing.shadow_route_comparator` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.runtime_mode` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.scanner.decision_cadence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.fresh_scan_strategy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.missed_opportunity_logger` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.opportunity_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.priority_queue` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.rate_limit_semaphore` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.scan_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.scanner_models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.scheduler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.throughput_planner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scanner.wallet_priority` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.leader_quality_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.leader_realized_history` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.live_wallet_scoring_loop` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.scoring_calibration_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.shortlist_quality_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.shortlist_rank` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.smart_money_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.smart_money_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.wallet_labels` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.scoring.wallet_score_v2` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.screeners` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.screeners.presets` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.security` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.security.dependances` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.security.fake_data_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.security.mainnet_guard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.security.safety_audit` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.security.secrets` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.security.secure_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.security.untrusted_projection` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.address_role_diagnostic` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.advanced_entry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.all_signals_zero_alert` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.cluster_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.consensus_window` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.copy_conflict_resolver` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.copy_decision` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.cross_sectional_momentum` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.crowding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.deb_ensemble` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.decision_contract` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.decision_funnel` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.decisions` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.depth_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.depth_spread_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.distilled_opportunity_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.edge_score` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.eligibility` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.entry_gate_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.entry_gate_v2` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.entry_microstructure_shadow` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.entry_quality_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.entry_supply_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.fill_admission` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.funding_reversal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.funding_window` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.gate_profile` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.gate_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.leader_delta` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.signals.lifecycle_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.liquidation_map` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.liquidation_signal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.maker_band` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.market_quality_score` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.signals.microprice_toxicity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.microstructure` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.microstructure_signals` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.multi_confirmation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.no_trade_taxonomy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.obi_signal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.oi_delta` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.opportunity_ranker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.oracle_mark_premium` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.orthogonalize` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.porte_copy_whitelist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.position_delta_detector` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.signals.pyramiding` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.ready_strategies_diagnostic` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.regime_confidence` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.regime_router` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.second_source_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.session_conditioning` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.session_filter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.shadow_wiring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.signal_builder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.signal_scoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.signal_taxonomy` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.signals.sla_premiere_position` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.source_reconcile` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.spike_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.twap_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.unified_opportunity_board` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.v26_entry_vetos` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.signals.vol_regime_signal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.warmup_guard` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.whale_fill_signal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.signals.whale_primary_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.accounting_truth` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.action_loss_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.adaptive_paper_sizing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.capital_accounting` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.coin_loss_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.copy_campaign_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.copy_cost_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.cost_breakdown` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.cost_components` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.cost_drag_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.cost_latency_contract` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.counterfactual_trade_replay` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.cross_venue_depth_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.decision_replay_analyzer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.diagnostic_reports` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.economic_campaign_provenance` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_campaigns` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_collection_plan` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_family_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.economic_family_scoreboard` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_freeze_registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_identity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.economic_objective` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.economic_proof_audit` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.economic_proof_controls` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.economic_proof_identity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.edge_distribution_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.exploratory_vs_validated_pnl` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.fee_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.freshness_gates` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.funding_payment_tracker` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.independent_breakdown` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.latency_components` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.lead_lag_campaign_adapter` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.lead_lag_execution_primitives` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.lead_lag_l2_history` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.lead_lag_measured_replay` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.ledger_integrity` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.liquidatable_marks` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.live_filters` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.log_metrics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.logs_analyzer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.loss_attribution` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.modes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.orderbook_execution_simulator` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.paper_event` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.paper_ledger` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.pnl_attribution` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.pnl_ledger_audit` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.pnl_reconciliation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.position_matching_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.profitability_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.readiness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.reconciliation_5_vues` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.refusal_breakdown` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.root_cause` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.root_cause_from_logs` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.scoreboard_feeder` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.scoreboard_metrics` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.scoreboard_producer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.scoreboard_promotion` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.scoreboard_runtime_metrics` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.simulation.session_memory` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.slippage_model` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.stale_signal_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.timing_distribution_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.tuning_report` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.simulation.vnext_promotion_protocol` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.simulation.wallet_loss_diagnostics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.skills` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.skills.optional_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.sources` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.sources.bulk_history` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.sources.clock` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.sources.collection_recorder` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.sources.models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.sources.registry` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.sources.shared_recorder` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.database` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.event_log` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.storage.models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.raw_store` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.raw_store_sqlite` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.storage.repositories` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.run_context` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.storage.runtime_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.storage.v12_sqlite_store` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.active_scope` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.strategies.carry_ranking` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.carry_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.carry_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.controller` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.dip_hedge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.engine_economics` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.engine_pnl` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.strategies.external_github_bridge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.external_simulation_bus` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.fusion_runtime` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.github_distillation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.grid_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.lead_lag_paper` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.library` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.strategies.models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.paper_registry` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.reference` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.strategies.strategy_catalog` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.strategies.strategy_data_dependencies` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.strategies.strategy_mode` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.strategies.strategy_readiness` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.strategies.v14_profiles` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.testing` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testing.lookahead_detector` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testing.mutation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testing.property_based` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.testnet.adapters` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.commands` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.dashboard_payload` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.executor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.journal` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.models` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.portfolio_tracker` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.testnet.readiness_gate` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.safety` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.testnet_executor_locked` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.testnet_order_builder` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.testnet_reconciliation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.testnet.testnet_safety_gates` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.action_catalog` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ui.alert_projection_router` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.app` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.authoritative_snapshot` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.charts` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ui.charts.extended_series` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.charts.series` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.cohorte_ledger_reader` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.courbe_equity` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ui.dashboard_v2` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.dydx_routes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.economic_writer` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ui.event_bus` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.full_refresh_fallback` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.fusion_persistent_adapter` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ui.fusion_status_provider` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.local_commands` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.persistent_state` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.quiet_logging` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.read_only_status_router` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.refusal_live` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.routes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.safe_actions` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.safety_gates_truth` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.schemas` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ui.simulation_log_export` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.sse_events` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.stale_policy` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.state` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.ui.status_delta` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.status_routes` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.v12_extended_panels` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.v12_panels` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.v12_status_provider` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.ui.wallet_mirror_panel` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.ui.wallet_panels` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.universe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.universe.blacklist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.universe.coin_universe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.universe.dynamic_whitelist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.utils` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.utils.logging` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.utils.math` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.utils.time` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.validation.baselines` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.validation.bootstrap` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.validation.no_trade_analyzer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.validation.refusal_cost` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.validation.shadow_arms` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.validation.testnet_tournament` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.venues` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.venues._canon` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.venues.binance` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.bitget` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.bybit` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.coinbase` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.defillama` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.deribit` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.drift` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.dune` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.gate` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.glassnode` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.gmx` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.htx` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.hyperliquid` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.kraken` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.nansen` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.okx` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.venues.registre_venues` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.wallet_universe` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.wallet_universe.wallet_universe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.activity_summary` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.api_budget` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.auto_watchlist` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.backfill` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.degradation` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.delta_utils` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.wallets.discovery` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.discovery_filters` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.discovery_scoring` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.discovery_sources` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.leader_hotness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_browser` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_dom_extractor` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_full_address_extractor` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.wallets.leaderboard_import` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_importer` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_models` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.leaderboard_network_probe` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_parser` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_robustness` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_source` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.leaderboard_validation` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.multi_source_merge` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.per_coin_scoring` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.position_delta_engine` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.position_rebuilder` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.profiler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.public_trades_live` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.quality_score` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.scan_limits` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.scan_progress` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.scan_queue` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.scan_scheduler` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.scoring` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.skill_vs_luck` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.snapshot_engine` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.snapshot_service` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.wallets.tiered_scanner` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.top500_bootstrap` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.top_wallet_export` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.top_wallet_ranker` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.wallets.toxicity` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.user_fills_live` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.user_fills_multiplex` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hl_observer.wallets.wallet_coin_profile` | `runtime_active` | atteignable depuis au moins un launcher/workflow analysé |
| `hl_observer.watchlists` | `unreached_requires_review` | non atteint par les seeds statiques; imports dynamiques/plug-ins doivent encore être vérifiés |
| `hl_observer.watchlists.smart_money_watchlist` | `test_only_or_support` | référencé par des tests mais non prouvé comme chemin runtime |
| `hyper_smart_observer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.agent_tools` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.agent_tools.readonly_manifest` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.agent_tools.schemas` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.app` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.app.config` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.app.logging_config` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.app.main` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.app.safety` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.api_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.archive_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.bounded_walk` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.db_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.route_scanner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.safety_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.secret_scanner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.source_scanner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.ui_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.audit.websocket_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.backtest_report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.delta_replay` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.event_replay` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.execution_delay_model` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.fee_model` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.multi_wallet_simulator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.replay_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.runtime_parity` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.slippage_model` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.backtesting.wallet_following_simulator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.consensus` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.consensus.position_consensus` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.consensus.wallet_cluster_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.candidate_importer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.consensus` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.copy_loop` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.copy_models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.copy_run_evidence` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.copy_signal_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.delta_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.edge` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.leaderboard_selector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.no_trade_report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.preflight` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.reports` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.repository` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.signal_candidate` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.sizing` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.copy_mode.snapshot_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dashboard` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dashboard.cli` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dashboard.exporter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.base_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.historical_archive_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.local_cache_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.manual_import_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.official_info_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.official_ws_provider` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.data_sources.provider_registry` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.adaptive_exits` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.adaptive_risk` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.backtest` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.build_whale_file` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.cli` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.cluster_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.cluster_whale_weight_patch` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.config` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.consensus` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.cosmos_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.dashboard_adapter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.data_truth` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.decision_intelligence_v2` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.decision_log` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.decision_orchestrator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.decision_tuning` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.edge_calculator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.edge_freshness_patch` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.fast_scan_integration` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.fast_scan_whale_patch` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.fast_scanner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.fill_simulator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.flux_live` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.fresh_signal_patch` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.full_node_stream` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.indexer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.integration_sanity` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.intelligence_director` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.leader_quality` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.leaderboard` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.leaderboard_import` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.leaderboard_import_patch` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.lifecycle` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.live_observer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.log_diagnostics` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.market_flow` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.market_regime` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.mega_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.metrics` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.missed_opportunity_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.no_trade` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.normalizer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.notional_bridge` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.opportunity_calibration` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.opportunity_recall` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.paper` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.paper_fill` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.paper_profile_memory` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.real_flow_calibration` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.rest_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.risk_policy` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.runtime_guards` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.safety` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.scoring` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.selection` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.signal_enhancer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.signal_latency_report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.signal_provenance_guard` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.signal_quality` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.signals` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.simulation_truth` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.static_contract_audit` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.storage` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.stream_consensus` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.tremor_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.tremor_quality_adapter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.tuned_decision` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.wallet_discovery` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.wallet_harvester` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.wallet_pool_ranker` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.whale_ranker` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.whale_replay` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.whale_watchlist` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.wide_scan_pool` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.ws_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.dydx_v4.ws_probe` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.execution` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.execution.execution_guard` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.execution.order_builder` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.execution.testnet_executor` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer.explorer_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer.explorer_discovery` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer.explorer_models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer.explorer_normalization` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.explorer_observer.explorer_rate_limiter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.api_health` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.info_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.normalization` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.payloads` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.rate_limiter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.testnet_exchange_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.validation` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.hyperliquid_client.websocket_client` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.intelligence` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.intelligence.anti_luck_filters` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.intelligence.feedback_loop` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.intelligence.wallet_intelligence` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.intelligence.wallet_ranker` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.ledger` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.ledger.decision_ledger` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.local_index` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.local_index.index_benchmark` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.local_index.index_config` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.local_index.query_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.local_index.wallet_index` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals.exporter` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals.market_signal_features` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals.mid_stability` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals.orderbook_features` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.market_signals.volatility` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.models.common_data_model` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.opportunities` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.opportunities.opportunity_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.exit_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.fees` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.latency` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.paper_intent` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.portfolio` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.reporting` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.simulator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.slippage` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.paper_trading.spread` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.anomaly_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.coin_patterns` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.pattern_detector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.pnl_patterns` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.position_patterns` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.repeatability` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.patterns.timing_patterns` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.pipeline` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.pipeline.source_health` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.action_classifier` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.lifecycle_builder` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.lifecycle_models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.lifecycle_quality` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.lifecycle_summary` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.position_lifecycle.position_reconstructor` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.dedupe` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.event_router` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.freshness_guard` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.heartbeat` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.hot_watch_rotation` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.reconnect` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.stream_models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.subscriptions` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.watchlist_manager` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.websocket_manager` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.realtime_monitor.ws_supervisor` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.risk_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.risk_engine.gates` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.risk_engine.limits` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.risk_engine.refusal_reasons` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.risk_engine.risk_state` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scale` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scale.chunked_ingestion` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scale.dataset_profiler` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scale.incremental_aggregator` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scale.scale_benchmark` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scanner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scanner.missed_opportunity_logger` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.behavior_score` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.confidence` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.drawdown` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.equity_curve` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.pattern_score` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.pnl` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.pnl_quality` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.ranking_report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.risk_metrics` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.sample_quality` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.smart_wallet_ranking` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.wallet_score` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.scoring.winrate` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.signal_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.signal_engine.signal_builder` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.signal_engine.signal_filters` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.signal_engine.signal_state` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.diagnostic_log` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.replay_simulation` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.scenario_runner` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.simulation_costs` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.simulation_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.simulation_models` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.simulation_report` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.simulation_risk` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.virtual_portfolio` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.simulation.virtual_position` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.database` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.fills_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.paper_trades_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.positions_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.risk_events_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.scores_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.signals_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.storage.repositories.wallet_repo` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.candidate_sources` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.collector` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.discovery_engine` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.shortlist` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.wallet_enrichment` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.wallet_graph` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.wallet_importer` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_discovery.wallet_labels` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_universe` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |
| `hyper_smart_observer.wallet_universe.wallet_universe` | `compatibility_legacy` | surface legacy explicitement autorisée par AGENTS.md |

## Cycles d'import

- `hl_observer.backtesting`
- `hl_observer.analysis.opening_patterns` → `hl_observer.analysis.profit_patterns`
- `hl_observer.backtesting.copy_vault_causal_selection` → `hl_observer.backtesting.copy_vault_executable`
- `hl_observer.collection.l2_snapshot_cache` → `hl_observer.signals.v26_entry_vetos`
- `hl_observer.decision_engine` → `hl_observer.decision_engine.local_engine`
- `hl_observer.experimental.copy_edge_forward` → `hl_observer.experimental.signaux`
- `hl_observer.experimental.exploratoire` → `hl_observer.experimental.runner`
- `hl_observer.ops.archive_portable` → `hl_observer.ops.inventaire_release`
- `hl_observer.research.decision_explainer` → `hl_observer.research.leader_review_ledger`
- `hl_observer.ui` → `hl_observer.ui.app`
