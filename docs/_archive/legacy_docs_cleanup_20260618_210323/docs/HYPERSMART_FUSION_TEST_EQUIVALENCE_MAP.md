# Fusion test coverage map (requested -> existing/new) — 2026-06-17

Maps each test requested by the GITHUB FUSION sprint to its implementation.
Statuses: NEW (added this sprint), EXISTING (equivalent already present, not
duplicated), PARTIAL (covered but worth strengthening). SIMULATION ONLY.

| # | Requested test | Status | Implemented by |
|---|----------------|--------|----------------|
| 1 | test_start_script_preserves_6s_freshness_guard | NEW | tests/test_start_script_preserves_6s_freshness_guard.py |
| 2 | test_start_script_min_edge_bps_guard | NEW | tests/test_start_script_min_edge_bps_guard.py |
| 3 | test_github_fusion_docs_exist | NEW | tests/test_github_fusion_docs_exist.py |
| 4 | test_repo_idea_matrix_has_keep_adapt_ban_defer | NEW | tests/test_repo_idea_matrix_has_keep_adapt_ban_defer.py |
| 5 | test_no_external_code_copy_license_markers | NEW | tests/test_no_external_code_copy_license_markers.py |
| 6 | test_no_exchange_sdk_imports_or_actions | NEW | tests/test_no_exchange_sdk_imports_or_actions.py (+ test_hypersmart_no_exchange.py) |
| 7 | test_no_private_key_signature_live_toggle | NEW | tests/test_no_private_key_signature_live_toggle.py |
| 8 | test_no_polymarket_clob_or_private_key_imports | NEW | tests/test_no_polymarket_clob_or_private_key_imports.py |
| 9 | test_no_fake_chart_or_fake_position_data | NEW | tests/test_no_fake_chart_or_fake_position_data.py (+ test_dashboard_truth_audit.py) |
| 10 | test_no_profit_promise_docs | NEW | tests/test_no_profit_promise_docs.py |
| 11 | test_l2book_liquidity_score | NEW | tests/test_l2book_liquidity_score.py |
| 12 | test_agent_safe_manifest_readonly_only | NEW | tests/test_agent_safe_manifest_readonly_only.py |
| 13 | test_no_open_orders_only_paper_intent | EXISTING | tests/test_no_open_orders_only_paper_intent.py (sprint 2) |
| 14 | test_hyperliquid_user_fills_by_time_aggregate_and_truncated_window | EXISTING | tests/test_hypersmart_info_client.py |
| 15 | test_hyperliquid_rate_limit_weight_budget | EXISTING | tests/test_hypersmart_rate_limiter.py, test_hypersmart_api_limits_constants.py, test_hypersmart_ws_limits.py |
| 16 | test_hyperliquid_ws_subscription_ack_snapshot_dedupe | EXISTING | tests/test_hypersmart_ws_dedupe.py, test_realtime_recovery_engine.py, test_user_fills_live_scan.py |
| 17 | test_market_mid_source_quality_fallback | EXISTING | tests/test_hypersmart_market_signal_features_fusion.py (mid_source in market_signals/) |
| 18 | test_scanner_rest_broad_scan_to_shortlist | EXISTING | tests/test_hypersmart_copy_network_read.py, test_hypersmart_copy_mode.py |
| 19 | test_scanner_ws_shortlist_max_10_users | PARTIAL | tests/test_hypersmart_ws_limits.py (confirm WS<=10 user-specific cap) |
| 20 | test_rest_reconciler_fills_missing_ws_event | EXISTING | tests/test_realtime_recovery_engine.py |
| 21 | test_common_data_model_required_metadata | EXISTING | tests/test_hypersmart_common_data_model_fusion.py |
| 22 | test_market_signal_features_rich_export_schema | EXISTING | tests/test_hypersmart_market_signal_features_fusion.py |
| 23 | test_edge_remaining_uses_spread_fee_slippage_latency_copy_degradation | EXISTING | tests/test_edge_remaining.py |
| 24 | test_risk_engine_deny_by_default_all_failure_modes | EXISTING | tests/test_hypersmart_risk_gates.py |
| 25 | test_dashboard_stale_signal_not_paper_ready | EXISTING | tests/test_hypersmart_dashboard_readonly.py, test_dashboard_truth_audit.py |
| 26 | test_backtest_runtime_parity_same_models | EXISTING | tests/test_hypersmart_backtest_runtime_parity_fusion.py |

NEW files added this sprint: 12. EXISTING equivalents reused (no duplication): 13.
PARTIAL to strengthen next: scanner_ws_shortlist_max_10_users (assert the
WS subscription cap of 10 user-specific wallets explicitly).
