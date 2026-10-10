"""Fail-closed rules for the optional, disjoint GitHub catalog push recovery."""
from tools.rebase_disjoint_catalog_publication import only_campaign_checkpoints


def test_concurrent_campaign_checkpoints_can_be_rebased():
    assert only_campaign_checkpoints([
        "catalog/campaigns/market-e8.json",
        "catalog/receipts/market-e8-u0.json",
        "catalog/campaign-history/market-e8.json",
    ])
    assert only_campaign_checkpoints([])


def test_catalog_content_or_source_code_change_forces_rebuild():
    for path in (
        "catalog/DATA_INDEX.json",
        "catalog/DATA_METRICS.json",
        "catalog/QUARANTINE_AUDIT.json",
        "datasets/safe/trades.manifest.json",
        "tools/index_run_manifest.py",
        "tools/check_dataset_quality.py",
        "control/alina-phase.json",
        ".github/workflows/reconcile-v2-catalog.yml",
        "catalog/receipts-other/unexpected.json",
        "catalog/campaigns",  # never accept a directory deletion
    ):
        assert not only_campaign_checkpoints([path])
