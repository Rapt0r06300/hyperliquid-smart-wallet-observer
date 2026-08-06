# BUG-001..080 — Disposition & traçabilité (miroir de AUD-311..390)

BUG-001..080 est le **miroir mot pour mot** de AUD-311..390. Chaque BUG est donc satisfait par le
MÊME code — soit un module construit+testé cette session `[B]`, soit du code existant vérifié `[V]`.
Le test `tests/test_bug_layer.py` **importe et EXÉCUTE** les modules de support (47 tests verts) :
ce ne sont pas des cases cochées à vide, ils pointent vers des fonctions qui tournent.

| BUG | (=AUD) | Sujet | Adossement |
|-----|--------|-------|-----------|
| 001 | 311 | Registre BLOCKED_EXTERNAL | [B] source_governance.RegistreBlockedExternal |
| 002 | 312 | Modules sans appelant | [B] data_integrity.detecter_modules_sans_appelant · [V] audit/cablage.py |
| 003 | 313 | Faux succès collecteurs | [B] data_honesty.interdire_success_si_zero_donnee |
| 004 | 314 | except trop larges | [B] data_integrity.scanner_except_larges |
| 005 | 315 | Unifier packages legacy/canonique | [V] AUD-028/029 (runtime canonique) |
| 006 | 316 | Dérive tasklists | [B] data_integrity.detecter_derive_tasklist |
| 007 | 317 | Unifier registres collecteurs | [V] AUD-050 (reconciliation SOURCES_HARVEST/REGISTRE) |
| 008 | 318 | Liveness ≠ progression | [B] stream_reliability.liveness_vs_progression |
| 009 | 319 | last_useful_event_ts | [B] stream_reliability.last_useful_event_ts |
| 010 | 320 | READY_MULTI_VENUE & WALLETS | [B] venue_capabilities.registre_par_defaut |
| 011 | 321 | OPTIONAL/REQUIRED/DEGRADED | [B] data_mesh.DataMesh (statuts) |
| 012 | 322 | Seuils stale par stream | [B] stream_reliability.seuils_stale_par_stream |
| 013 | 323 | Dead Letter Queue | [B] stream_reliability.DeadLetterQueue |
| 014 | 324 | Migrations de schéma | [B] stream_reliability.RegistreMigrationsSchema |
| 015 | 325 | Idempotence REST+WS | [V] realtime/durable_dedup.py · copy_vault/exactly_once_source_fill.py |
| 016 | 326 | Collisions snapshots dYdX (ms) | [V] tests/dydx_v4/ |
| 017 | 327 | Decimal prix/taille/frais/PnL | [V] accounting/fixed_point_core.py |
| 018 | 328 | Batch SQLite | [V] executemany (scenario_db, trades_recorder, connectors/base) |
| 019 | 329 | Connexions SQLite sûres | [V] PRAGMA/isolation (l2_snapshot_cache, connectors/base) |
| 020 | 330 | Checkpoints WAL | [V] capture/atomic_checkpoint.py · copy_vault/epoch_local_checkpoint.py |
| 021 | 331 | Borner tables raw JSON | [V] collection/stockage_brut_borne.py |
| 022 | 332 | Backpressure | [V] copy_vault/per_vault_queue_cap.py · api_governance/request_qos.py |
| 023 | 333 | Load shedding | [V] api_governance/request_qos.py |
| 024 | 334 | Quota disque | [V] ops/quota_stockage.py |
| 025 | 335 | Coordinateur rate limits | [V] api_governance/weighted_rate_limiter.py |
| 026 | 336 | Circuit breaker par endpoint | [V] collection/circuit_breaker.py (+core/risk) |
| 027 | 337 | Tempêtes de reconnexion | [V] copy_vault/reconnect_overlap_backfill.py |
| 028 | 338 | Reconnect ≠ resync carnet | [V] copy_vault/reconnect_replay_suppression.py |
| 029 | 339 | Horloge & NTP | [V] ops/clock_integrity.py |
| 030 | 340 | Sémantique timestamps | [V] ops/clock_integrity.py |
| 031 | 341 | Symbol master point-in-time | [B] normalization_units.symbol_master_pit |
| 032 | 342 | Linéaires/inverses/multiplicateurs | [V] arbitrage/contract_multiplier_normalization.py · linear_inverse_normalization.py |
| 033 | 343 | USD/USDT/USDC & depeg | [V] arbitrage/depeg_haircut.py |
| 034 | 344 | Intervalles de funding | [V] funding/funding_times.py |
| 035 | 345 | Unités d'open interest | [B] normalization_units.normaliser_open_interest |
| 036 | 346 | Sens des liquidations | [B] normalization_units.normaliser_sens_liquidation |
| 037 | 347 | Sens agressor/taker | [V] execution/maker_taker.py |
| 038 | 348 | Modèle de frais par niveau | [V] copy_fidelity/fee_tiers.py · market_data/exchange_fee_normalizer.py |
| 039 | 349 | Méthodologies mark/index versionnées | [B] normalization_units.MethodologieMarkIndex |
| 040 | 350 | Interdire données révisées non-PiT | [B] data_honesty.rejeter_donnees_revisees_non_pit |
| 041 | 351 | Expiration des caches payants | [B] source_governance.cache_paye_expire |
| 042 | 352 | Interdire basse-latence Dune/Nansen | [B] source_governance.politique_basse_latence |
| 043 | 353 | Réduire les faux merges | [B] wallet_integrity.seuil_confiance_merge |
| 044 | 354 | Sybils & wallets miroirs | [B] wallet_integrity.detecter_sybils |
| 045 | 355 | Transferts ≠ PnL | [B] wallet_integrity.transferts_hors_pnl |
| 046 | 356 | Survivorship bias | [B] wallet_integrity.correction_survivorship |
| 047 | 357 | Wallets liquidés dans cohortes | [B] wallet_integrity.inclure_wallets_liquides |
| 048 | 358 | Copyability cross-protocole | [V] copy_vault/copyability_erosion_monitor.py |
| 049 | 359 | Crowding multi-source | [V] clusters/crowding_detector.py · signals/crowding.py |
| 050 | 360 | Filtrer spoofing/wash/flicker | [B] market_quality.filtrer_manipulation |
| 051 | 361 | Pannes corrélées de sources | [B] market_quality.pannes_correlees |
| 052 | 362 | Consensus pondéré par indépendance | [B] wallet_integrity.consensus_pondere_independance |
| 053 | 363 | Source ablation obligatoire | [B] data_mesh.ablation_sources |
| 054 | 364 | Valeur marginale nette des sources | [B] data_mesh.ablation_sources |
| 055 | 365 | Lineage ligne/événement | [B] storage_partition.lineage_ligne |
| 056 | 366 | Immutabilité Bronze | [B] medallion.bronze_immuable · storage_partition.hash_partition |
| 057 | 367 | Hasher shards & partitions | [B] storage_partition.hash_partition |
| 058 | 368 | Parité live/replay | [V] backtest/runtime_parity.py · backtesting/backtest_live_parity.py |
| 059 | 369 | Adaptateur unique live/replay | [B] data_integrity.adaptateur_unique_live_replay |
| 060 | 370 | Tests réseau hors CI déterministe | [V] tests mockés (test_dydx_rest_and_ws_mocked) |
| 061 | 371 | Golden packets officiels | [V] dataset/parser_golden_corpus.py |
| 062 | 372 | Changements silencieux d'API | [B] market_quality.detecter_changement_api |
| 063 | 373 | Pinner versions & endpoints | [B] source_governance.pin_versions_endpoints |
| 064 | 374 | Registre licences/quotas/coûts | [B] source_governance.RegistreLicences |
| 065 | 375 | Secrets = clés read-only | [B] source_governance.politique_cle_read_only |
| 066 | 376 | Revue conformité/CGU | [B] source_governance.RegistreConformite |
| 067 | 377 | Dashboard santé Data Mesh | [B] source_governance.dashboard_sante_mesh |
| 068 | 378 | SLA par source | [B] source_governance.sla_source |
| 069 | 379 | Checklist d'onboarding source | [B] source_governance.checklist_onboarding |
| 070 | 380 | Politique de retrait de source | [B] source_governance.politique_retrait |
| 071 | 381 | Collecteurs doublons | [B] data_integrity.detecter_collecteurs_doublons |
| 072 | 382 | Correspondance registre/lanceur/superviseur | [B] data_integrity.correspondance_registre_lanceur_superviseur |
| 073 | 383 | Watchdog ne masque pas | [V] feed_integrity/idle_socket_watchdog.py |
| 074 | 384 | Interdire SUCCESS si zéro donnée | [B] data_honesty.interdire_success_si_zero_donnee |
| 075 | 385 | Compteur d'événements utiles | [B] stream_reliability.compteur_evenements_utiles |
| 076 | 386 | Quarantainer les champs inconnus | [B] data_honesty.quarantaine_champs_inconnus |
| 077 | 387 | Interdire les zéros inventés | [B] data_honesty.distinguer_zero |
| 078 | 388 | Interdire carry-forward silencieux | [B] data_honesty.detecter_carry_forward_silencieux |
| 079 | 389 | Sélections aléatoires seedées | [V] samplers/pruners seedés (AUD-091) |
| 080 | 390 | Attribuer CPU/RAM/disque/réseau | [B] data_integrity.attribuer_ressources_par_source |

**Bilan : 80/80 adossés à du code réel — 50 `[B]` (construits+testés cette session) + 30 `[V]` (existants vérifiés). Preuve exécutable : `tests/test_bug_layer.py` (47 tests verts, joués contre la source réelle du device).**
