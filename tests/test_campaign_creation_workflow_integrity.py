from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "create-resumable-campaigns.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_campaign_creation_workflow_has_single_canonical_structure() -> None:
    text = _text()
    assert text.count("\njobs:\n") == 1
    assert text.count("\n  launch:\n") == 1
    assert text.count("make_campaign() {") == 1
    assert text.count("PHASE_ARGS+=(--operator-request-id") == 1


def test_analysis_selection_identity_is_exact_sha256_binding() -> None:
    text = _text()
    assert "tools/resolve_analysis_selection.py" in text
    assert '--source-collection-epoch "$SOURCE_COLLECTION_EPOCH"' in text
    assert '--collection-cutoff-at-utc "$COLLECTION_CUTOFF"' in text
    assert 'grep -Eq \'^[0-9a-f]{64}$\'' in text
    assert '--dataset-selection-id "$DATASET_SELECTION_ID"' in text
    assert '--dataset-selection-id "phase-' not in text


def test_workflow_has_no_post_launch_duplicated_campaign_body() -> None:
    text = _text()
    launch = text.index("\n  launch:\n")
    tail = text[launch:]
    assert "make_campaign() {" not in tail
    assert "PHASE_ARGS+=(--source-collection-epoch" not in tail


def test_collect_campaigns_refresh_stale_code_pins_safely() -> None:
    text = _text()
    assert "tools/refresh_pending_collect_campaign.py" in text
    assert 'if [ -f "$P" ] && [ "$PHASE" = "COLLECT" ]; then' in text
    assert '--expected-phase-epoch "$PHASE_EPOCH"' in text
    assert text.count("refresh_pending_collect_campaign.py") >= 2


def test_controller_does_not_serialize_fresh_market_behind_copy_fanout() -> None:
    controller = (ROOT / ".github" / "workflows" / "resumable-campaign-controller.yml").read_text(encoding="utf-8")
    assert "group: resumable-campaign-controller-${{ github.event_name == 'push' && github.sha || 'v5' }}" in controller
    assert "copy_ids=copy_ids[:1]" in controller
    assert "active_other=0" in controller
    # A leftover RUNNING lease from e6 must not starve e8 runners.
    assert 'or int(row.get("phase_epoch") or 0)!=phase_epoch' in controller
    assert 'or int(row.get("phase_epoch") or 0)>phase_epoch' not in controller
    assert "other_capacity=max(0,16-active_other)" in controller
    assert "reserved_canary=bounded_canaries[:1]" in controller
    assert "other_ids=reserved_canary+ordinary_ids" in controller
    assert "relay_collect:" in controller
    assert "uses: ./.github/workflows/resumable-campaign-worker.yml" in controller
    assert "needs.select.outputs.phase == 'COLLECT'" in controller


def test_collect_market_shards_scale_without_repartitioning_live_bucket() -> None:
    text = _text()
    assert "TARGET_MARKET_SHARDS=16" in text
    assert 'if [ -f "$MARKET_SHARD_INDEX" ]; then' in text
    assert 'preserving frozen current-bucket market_shard_count=$MARKET_SHARDS' in text
    assert '--shard-count "$MARKET_SHARDS"' in text


def test_collect_campaign_identity_and_frozen_inputs_are_epoch_scoped() -> None:
    text = _text()
    assert 'MARKET_PLAN_DIR="catalog/market_collection_plans/e$PHASE_EPOCH/$BUCKET"' in text
    assert '"market-e$PHASE_EPOCH-$MARKET_SHARD-$BUCKET-v7"' in text
    assert 'COPY_SELECTION="catalog/copy_vault_selections/e$PHASE_EPOCH/$BUCKET.json"' in text
    assert '"copy-vault-e$PHASE_EPOCH-broad-$BUCKET-v8"' in text
    assert '"copy-vault-two-speed-broad-rest-priority-ws-v8"' in text
    assert '"max_ws_vaults":10' in text
    assert '"vault_shard_count":1' in text
    assert '"vault_shard_index":0' in text
    assert '"event-e$PHASE_EPOCH-$BUCKET-v5"' in text
    assert '"archives-binance-btc-e$PHASE_EPOCH-$DAY-v4"' in text
    assert '"archives-bybit-btc-e$PHASE_EPOCH-$DAY-v4"' in text
    assert 'row.get("creation_phase")=="COLLECT"' in text
    assert 'int(row.get("phase_epoch") or 0)==epoch' in text



def test_archive_backfill_is_not_starved_by_unbounded_live_market_backlog():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    controller = (root / ".github/workflows/resumable-campaign-controller.yml").read_text()
    creator = (root / ".github/workflows/create-resumable-campaigns.yml").read_text()
    assert "archive_due=[" in controller
    assert "if priority == 2" in controller
    assert "other_ids=[archive_first]+" in controller
    assert "other_capacity=max(0,16-active_other)" in controller
    assert "ordinary_ids=ordinary_ids[:max(0,other_capacity-len(reserved_canary))]" in controller
    assert "if [ \"$((10#$HOUR))\" -ge 6 ]; then" in creator
    assert '"archives-binance-btc-e$PHASE_EPOCH-$DAY-v4"' in creator
    assert '"archives-bybit-btc-e$PHASE_EPOCH-$DAY-v4"' in creator
    assert "--preserve-running" in creator
