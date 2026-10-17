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


def test_noncanonical_report_writers_allow_disjoint_fast_forward():
    assert only_campaign_checkpoints([
        "docs/alina-closure-report.json",
        "docs/canonical-spec-verification.json",
        "catalog/CAMPAIGN_RESILIENCE_RECEIPT.json",
        "catalog/DATASET_HEALTH_RECEIPT.json",
    ])


def test_other_docs_and_quality_sources_are_never_allowed():
    for path in ("docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md",
                 "catalog/REPLAY_COMPAT_PATCH.json",
                 "catalog/REPLAY_COMPATIBILITY_REASONS.json",
                 "catalog/data-index-parts/part-000001.json",
                 "catalog/UNCOMPRESSED_SIZE_PATCH.json",
                 "docs/not-listed.json"):
        assert not only_campaign_checkpoints([path])


def test_allowed_report_overlap_still_blocks_rebase(monkeypatch):
    import subprocess
    import tools.rebase_disjoint_catalog_publication as module

    def fake_git(*args, **kwargs):
        if args[:2] == ("status", "--porcelain"):
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ("rev-parse", "HEAD^"):
            return subprocess.CompletedProcess(args, 0, b"a" * 40 + b"\n", b"")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ("diff", "--name-only"):
            return subprocess.CompletedProcess(
                args, 0, b"docs/alina-closure-report.json\x00", b"",
            )
        raise AssertionError(f"unexpected command {args}")

    # main() is a CLI entrypoint: isolate argparse from pytest -q arguments.
    monkeypatch.setattr(module.sys, "argv", ["rebase_disjoint_catalog_publication.py"])
    monkeypatch.setattr(module, "git", fake_git)
    assert module.main() == 3
