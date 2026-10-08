from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_legacy_long_collectors_are_manual_only():
    for name in (
        "collect-market-data-v2.yml",
        "collect-copy-vault-v2.yml",
        "collect-official-archives-v2.yml",
        "collect-event-intelligence-v2.yml",
    ):
        text = _workflow(name)
        header = text.split("permissions:", 1)[0]
        assert "schedule:" not in header
        assert "workflow_dispatch" in header
        assert "self-hosted" not in text


def test_resumable_creator_is_continuous_hosted_and_frozen():
    text = _workflow("create-resumable-campaigns.yml")
    assert "schedule:" in text
    assert "cron: \'2 * * * *\'" in text
    assert "group: resumable-campaign-creation-hourly" in text
    assert "cancel-in-progress: true" in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text
    assert '"duration_s":3500' in text
    assert '"coins":"BTC,ETH,SOL,XRP,DOGE,BNB,AVAX,LINK,SUI,ADA,TRX,TON,WIF,ARB,OP,APT"' not in text
    assert '"universe_mode":"native_discovery_full"' in text
    assert '"require_all_native_venues":True' in text
    assert "TARGET_MARKET_SHARDS=16" in text
    assert "freeze_market_shards.py" in text
    assert "catalog/market_collection_plans" in text
    assert 'MARKET_PLAN_DIR="catalog/market_collection_plans/e$PHASE_EPOCH/$BUCKET"' in text
    assert "MARKET_FULL_PLAN" in text
    assert "MARKET_SHARD_INDEX" in text
    assert "universe_digest" in text
    assert "plan_sha256" in text
    assert "MARKET_SHARD_INDEX" in text
    assert "market-shards.tsv" in text
    assert "market-e$PHASE_EPOCH-$MARKET_SHARD-$BUCKET-v7" in text
    assert "market-hourly-sharded-frozen-universe-v7" in text
    assert "market_shard_count" in text
    assert "market_shard_index" in text
    assert "src/hl_observer/collection/depth_capacity.py" in text
    assert "src/hl_observer/collection/binance_depth_live.py" in text
    assert "market_collection" in text
    assert "copy_vault_collection" in text
    assert "freeze_copy_vault_selection.py" in text
    assert "COPY_COUNT" in text
    assert "ACTIVE_COPY_CAMPAIGNS" in text
    assert "active Copy-Vault lane still running" in text
    assert "supersede_copy_vault_fanout.py" in text
    assert "--legacy-version=-v7" in text
    assert "--preserve-running" in text
    assert '"max_vaults":int(sys.argv[1])' in text
    assert '"max_ws_vaults":10' in text
    assert '"vault_shard_count":1' in text
    assert '"vault_shard_index":0' in text
    assert '"copy_vault_mode":"two_speed_broad_rest_priority_ws"' in text
    assert "copy-vault-e$PHASE_EPOCH-broad-$BUCKET-v8" in text
    assert "copy-vault-two-speed-broad-rest-priority-ws-v8" in text
    assert "selection_file" in text
    assert "selection_sha256" in text
    assert "catalog/copy_vault_selections" in text
    assert 'COPY_SELECTION="catalog/copy_vault_selections/e$PHASE_EPOCH/$BUCKET.json"' in text
    assert "official_archive_collection" in text
    assert "event_intelligence_collection" in text
    for kind in ("replay", "backtest", "oos", "forward_paper", "module_pnl_proof", "scoreboard"):
        assert f"make_campaign {kind}" in text
    assert 'ANALYSIS_ID="analysis-e$PHASE_EPOCH"' in text
    assert "ref: main" in text
    assert "--cursor-json" in text
    assert "archives-binance-btc-" in text
    assert "archives-bybit-btc-" in text
    assert "REPLAY_START_MS" in text
    assert "ECON_START_MS" in text
    assert '"max_shards":0' in text
    assert "gh workflow run resumable-campaign-controller.yml" not in text
    assert "uses: ./.github/workflows/resumable-campaign-controller.yml" in text
    assert "actions: write" in text


def test_resumable_creator_encodes_copy_vault_cursor_as_valid_json():
    text = _workflow("create-resumable-campaigns.yml")
    assert "COPY_CURSOR=" in text
    assert "json.dumps" in text
    assert '"$COPY_CURSOR"' in text
    assert '{"duration_s":3500' in text
    assert '"max_ws_vaults":10' in text
    assert '"copy_vault_mode":"two_speed_broad_rest_priority_ws"' in text


def test_controller_worker_are_bounded_hosted_and_collect_relayed():
    controller = _workflow("resumable-campaign-controller.yml")
    worker = _workflow("resumable-campaign-worker.yml")
    assert "cron: '*/5 * * * *'" in controller
    assert "push:" in controller
    assert "resumable-campaign-controller.yml" in controller
    assert "timeout-minutes: 10" in controller
    assert "timeout-minutes: 345" in worker
    assert "cancel-in-progress: false" in controller
    assert "group: resumable-campaign-controller-${{ github.event_name == 'push' && github.sha || 'v5' }}" in controller
    assert "cancel-in-progress: false" in worker
    assert "self-hosted" not in controller + worker
    assert "uses: ./.github/workflows/resumable-campaign-worker.yml" in controller
    assert "copy_work:" in controller
    assert "other_work:" in controller
    assert "max-parallel: 1" in controller
    assert "max-parallel: 16" in controller
    assert "selected[:128]" in controller
    assert 'list-due catalog/campaigns             | head -n 128' not in controller
    assert 'all-due.txt' in controller
    assert 'GITHUB_EVENT_PATH' in controller
    assert 'canary-market-*.json' in controller
    assert 'changed_canaries' in controller
    assert 'selected = [campaign_id for campaign_id in due if campaign_id in changed_canaries]' in controller
    assert 'canary_ids = [campaign_id for campaign_id in due if campaign_id.startswith("canary-market-")]' in controller
    assert 'selected = canary_ids + [campaign_id for campaign_id in due if campaign_id not in canary_ids]' in controller
    assert "copy_matrix" in controller
    assert "other_matrix" in controller
    assert "active_copy=False" in controller
    assert "active_other=0" in controller
    assert "other_capacity=max(0,16-active_other)" in controller
    assert "fromJSON(needs.select.outputs.copy_matrix)" in controller
    assert "fromJSON(needs.select.outputs.other_matrix)" in controller
    assert "relay_collect:" in controller
    assert "gh workflow run resumable-campaign-controller.yml" in controller
    assert "ref: ${{ steps.pin.outputs.sha }}" in worker
    assert "Claim durable campaign lease" in worker
    assert "Persist collection data or analysis evidence" in worker
    assert 'ENV_RECEIPT="$WORKSPACE/runtime/reports/analysis_stages/scoreboard.json"' in worker
    assert 'LEGACY_ENV_RECEIPT="$WORKSPACE/runtime/reports/economic_campaigns/analysis_stages/scoreboard.json"' in worker
    assert "Publish final campaign checkpoint" in worker
    assert "publish_dataset_v2_release.py" in worker
    assert "verify_lease" in worker
    assert "workflow_call:" in worker
    assert "Checkout Alina repository" in controller
    assert "Refresh Alina main before pin" in worker
    assert "alina-smartflow-datasets-v2" not in controller
    assert "alina-smartflow-datasets-v2" not in worker
    assert 'os.path.abspath(str(part["selection_file"]))' in worker
    assert 'part.setdefault("duration_s",3500)' in worker
    assert 'part.setdefault("max_ws_vaults",10)' in worker
    assert 'part.setdefault("vault_shard_count",1)' in worker
    assert 'part.setdefault("vault_shard_index",0)' in worker
    assert "COPY_VAULT_SWEEP_DURATION_CAP_S=300" not in worker
    assert 'part["duration_s"] = min' not in worker
    assert 'part.setdefault("market_shard_count",1)' in worker
    assert 'part.setdefault("market_shard_index",0)' in worker
    assert "MARKET_SHARD_COUNT" in worker
    assert "MARKET_SHARD_INDEX" in worker
    assert "sha256_coin_mod" in worker
    assert "MARKET_PLAN_FILE" in worker
    assert "MARKET_PLAN_SHA" in worker
    assert "using frozen market shard plan" in worker
    assert "full_selected_coin_count" in worker
    assert "actions: write" in worker
    assert "needs.select.outputs.phase == 'COLLECT'" in controller
    assert "needs.select.outputs.phase == 'COLLECT'" in controller


def test_metrics_refresh_is_scheduled_and_serialized():
    text = _workflow("dataset-metrics-v2.yml")
    assert "schedule:" in text
    assert "group: dataset-v2-control-plane-index" in text
    assert "cancel-in-progress: false" in text
    assert "tools/build_catalog_metrics.py" in text
    assert "catalog/TRADE_COUNT_PATCH.json" in text
    assert "catalog/TRADE_UNIQUE_COUNT_PATCH.json" in text


def test_reconcile_covers_all_production_release_families_and_pins_actions():
    text = _workflow("reconcile-v2-catalog.yml")
    assert "event-intelligence-v2-" in text
    assert "data-v2-" in text
    assert "--attempts 1" in text
    assert "--poll-seconds 0" in text
    assert "dataset-health-receipt.yml" in text
    assert "actions/checkout@v4" not in text
    assert "actions/setup-python@v5" not in text
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in text
    assert "Download only new production V2 run manifests" in text
    assert "known={" in text


def test_resumable_worker_preserves_frozen_cursor_and_retry_policy():
    worker = _workflow("resumable-campaign-worker.yml")
    assert 'part=dict(m.get("cursor") or {})' in worker
    assert 'part.setdefault("duration_s",3500)' in worker
    assert 'part.setdefault("max_vaults",10)' in worker
    assert "TEMPORARY_EXTERNAL" in worker
    assert "failure=True" in worker


def test_resumable_creator_and_controller_track_current_main_for_new_work():
    creator = _workflow("create-resumable-campaigns.yml")
    controller = _workflow("resumable-campaign-controller.yml")
    assert "ref: main" in creator
    assert "ref: main" in controller
    assert "777d329176ded9e9262c33a9411adc99c55caa02" not in creator + controller


def test_single_repo_exact_count_backfill_is_scheduled_hosted():
    backfill = _workflow("backfill-exact-trade-counts.yml")
    assert not (ROOT / ".github" / "workflows" / "main-dataset-v2-bridge-smoke.yml").exists()
    assert "schedule:" in backfill
    assert "push:" in backfill
    assert "backfill-exact-trade-counts.yml" in backfill
    assert "backfill_exact_trade_counts.py" in backfill
    assert 'default: "2000"' in backfill
    assert 'inputs.limit || \'2000\'' in backfill
    assert "runs-on: ubuntu-latest" in backfill
    assert "self-hosted" not in backfill

def test_single_repo_collect_and_analysis_chain_never_targets_legacy_dataset_repo():
    legacy = "Rapt0r06300/alina-smartflow-datasets-v2"
    canonical = "Rapt0r06300/hyperliquid-smart-wallet-observer"
    active_paths = (
        ".github/workflows/create-resumable-campaigns.yml",
        ".github/workflows/resumable-campaign-controller.yml",
        ".github/workflows/resumable-campaign-worker.yml",
        ".github/workflows/analysis-stage-controller.yml",
        ".github/workflows/advance-analysis-stage.yml",
        "tools/resumable_campaign.py",
        "src/hl_observer/datasets/v2_pipeline.py",
        "src/hl_observer/datasets/v2_repository.py",
        "src/hl_observer/ops/v2_dataset_bridge.py",
    )
    for relative in active_paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert legacy not in text, relative

    creator = _workflow("create-resumable-campaigns.yml")
    for kind in ("replay", "backtest", "oos", "forward_paper", "module_pnl_proof", "scoreboard"):
        assert kind in creator

    pipeline = (ROOT / "src/hl_observer/datasets/v2_pipeline.py").read_text(encoding="utf-8")
    repository = (ROOT / "src/hl_observer/datasets/v2_repository.py").read_text(encoding="utf-8")
    campaign_cli = (ROOT / "tools/resumable_campaign.py").read_text(encoding="utf-8")
    assert f'V2_REPOSITORY = "{canonical}"' in pipeline
    assert f'DEFAULT_REPOSITORY = "{canonical}"' in repository
    assert canonical in campaign_cli


def test_all_active_data_defaults_target_main_repository_only():
    canonical = "Rapt0r06300/hyperliquid-smart-wallet-observer"
    legacy_repositories = (
        "Rapt0r06300/alina-smartflow-datasets-v2",
        "Rapt0r06300/hypersmart-datasets",
    )
    active_defaults = (
        "src/hl_observer/ops/autonomous_research_job.py",
        "tools/publish_data_vault_snapshot.py",
    )
    for relative in active_defaults:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert canonical in text, relative
        for legacy in legacy_repositories:
            assert legacy not in text, relative


def test_live_collectors_enable_deterministic_publication_compaction():
    for relative in (
        "tools/collecter_native_venues.py",
        "tools/collecter_bbo.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "compact_target_bytes=64 * 1024 * 1024" in text, relative


def test_old_pinned_collectors_use_current_main_control_plane_for_leases():
    worker = _workflow("resumable-campaign-worker.yml")
    assert 'PYTHONPATH=src python tools/resumable_campaign.py validate "$M"' in worker
    assert 'PYTHONPATH=src python tools/resumable_campaign.py start "$M"' in worker
    assert 'PYTHONPATH=alina/src python alina/tools/run_resumable_campaign.py' in worker
    assert 'PYTHONPATH=alina/src python alina/tools/resumable_campaign.py' not in worker


def test_campaign_watchdog_recomputes_on_concurrent_receipt_writers():
    text = _workflow("campaign-watchdog.yml")
    assert "git fetch origin main" in text
    assert "git reset --hard origin/main" in text
    assert "python tools/campaign_watchdog.py --dispatch" in text
    assert "for attempt in 1 2 3 4 5" in text

def test_resumable_creator_structure_and_exact_analysis_selection_are_not_corrupted():
    text = _workflow("create-resumable-campaigns.yml")
    assert text.count("\n  launch:\n") == 1
    assert text.count("make_campaign() {") == 1
    assert text.count("Commit campaign manifests") == 1
    assert text.count("tools/import_operator_intents.py") == 1
    assert "tools/resolve_analysis_selection.py" in text
    assert "DATASET_SELECTION_ID=" in text
    assert "--source-collection-epoch \"$SOURCE_COLLECTION_EPOCH\"" in text
    assert "grep -Eq '^[0-9a-f]{64}$'" in text
    assert '--dataset-selection-id "$DATASET_SELECTION_ID"' in text
    assert "{64}          " not in text

def test_analyze_phase_never_prepares_collection_inputs():
    text = _workflow("create-resumable-campaigns.yml")
    collect_start = text.index('if [ "$PHASE" = "COLLECT" ]; then')
    analyze_start = text.index('if [ "$PHASE" = "ANALYZE" ]; then', collect_start + 1)
    collect_block = text[collect_start:analyze_start]
    assert "market_collection" in collect_block
    assert "freeze_copy_vault_selection.py" in collect_block
    assert "copy_vault_collection" in collect_block
    assert "event_intelligence_collection" in collect_block
    assert "official_archive_collection" in collect_block
    analyze_block = text[analyze_start:]
    assert "freeze_copy_vault_selection.py" not in analyze_block
    assert "official_archive_collection" not in analyze_block


def test_single_repo_phase_control_propagates_generated_request_id():
    text = _workflow("alina-phase-control.yml")
    legacy = "Rapt0r06300/alina-smartflow-datasets-v2"
    canonical = "Rapt0r06300/hyperliquid-smart-wallet-observer"
    assert legacy not in text
    assert canonical in text
    assert 'echo "request_id=$REQUEST_ID" >> "$GITHUB_OUTPUT"' in text
    assert text.count('REQUEST_ID: ${{ steps.request.outputs.request_id }}') >= 2
    assert 'gh workflow run control-phase.yml' in text
    assert '--repo "$GITHUB_REPOSITORY"' in text
    assert '-f request_id="$REQUEST_ID"' in text
