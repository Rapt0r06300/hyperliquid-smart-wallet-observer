import json
from pathlib import Path

from tools.partitioned_data_index import read_index

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "catalog/DATA_QUALITY_REGISTRY.json").read_text())
CAT = json.loads((ROOT / "catalog/DATA_CATALOG.json").read_text())
# Every consumer must reconstruct and SHA-verify the complete partitioned
# catalog; a root without inline shards must never be mistaken for NO_DATA.
INDEX = read_index(ROOT / "catalog/DATA_INDEX.json")


def test_safe_only_validation():
    assert REG["validation_allowed_statuses"] == ["SAFE"]


def test_active_status_matches_index():
    shards = INDEX.get("shards") or []
    expected = (
        "SAFE"
        if any(row["quality_status"] == "SAFE" for row in shards)
        else ("PARTIAL" if shards else "NO_DATA")
    )
    assert INDEX["active_data_status"] == expected
    assert REG["active_dataset"]["status"] == expected
    assert REG["active_dataset"]["validation_allowed"] is (expected == "SAFE")
    # SAFE means replay/validation data quality only. It must never be promoted
    # into profitability proof without a separate costed OOS/forward result.
    assert REG["active_dataset"]["proof_of_pnl_allowed"] is False


def test_every_status_counter_is_index_bound():
    from collections import Counter

    counts = Counter(row["quality_status"] for row in INDEX.get("shards") or [])
    assert set(counts).issubset({"SAFE", "PARTIAL", "REJECT", "STALE"})
    assert sum(counts.values()) == CAT["indexed_shard_count"]
    assert REG["active_dataset"]["indexed_shards"] == CAT["indexed_shard_count"]
    for status, catalog_key, registry_key in (
        ("SAFE", "safe_shard_count", "safe_count"),
        ("PARTIAL", "partial_shard_count", "partial_count"),
        ("REJECT", "reject_shard_count", "reject_count"),
        ("STALE", "stale_shard_count", "stale_count"),
    ):
        assert counts[status] == CAT[catalog_key]
        assert counts[status] == REG["active_dataset"][registry_key]


def test_empty_repository_is_no_data():
    if not (INDEX.get("shards") or []):
        assert INDEX["active_data_status"] == "NO_DATA"


def test_no_legacy_import():
    assert REG["policy"]["legacy_import_allowed"] is False
    assert CAT["legacy_sources"]["enabled"] is False
    assert CAT["legacy_sources"]["automatic_import"] is False


def test_public_repo_safety():
    assert REG["policy"]["public_data_only"] is True
    assert REG["policy"]["secrets_forbidden"] is True


def test_no_pc_runner():
    assert REG["policy"]["self_hosted_forbidden"] is True
    assert REG["policy"]["user_pc_forbidden"] is True


def test_every_indexed_manifest_exists_and_matches_status():
    for row in INDEX.get("shards") or []:
        path = ROOT / row["manifest_path"]
        assert path.is_file()
        manifest = json.loads(path.read_text())
        assert manifest["dataset_id"] == row["dataset_id"]
        assert manifest["quality_status"] == row["quality_status"]
        assert manifest["validation_allowed"] is (row["quality_status"] == "SAFE")


def test_dataset_quality_ci_budget_covers_full_catalog_validation():
    """The large read-only catalog scan must not hit a 10-minute runner cap."""
    workflow = (ROOT / ".github/workflows/dataset-quality-ci.yml").read_text(encoding="utf-8")
    job = workflow.split("  quality:\n", 1)[1].split("    steps:\n", 1)[0]
    timeout = next(int(line.split(":", 1)[1].strip()) for line in job.splitlines()
                   if line.strip().startswith("timeout-minutes:"))
    assert timeout >= 30
