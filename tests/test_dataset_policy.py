import json
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path

from tools.partitioned_data_index import iter_index_rows

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "catalog/DATA_QUALITY_REGISTRY.json").read_text())
CAT = json.loads((ROOT / "catalog/DATA_CATALOG.json").read_text())
INDEX_PATH = ROOT / "catalog/DATA_INDEX.json"
INDEX_ROOT = json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _index_rows():
    """Stream the complete verified index without retaining 1.85M rows."""
    return iter_index_rows(INDEX_PATH)


def _validate_manifest(row):
    path = ROOT / row["manifest_path"]
    assert path.is_file()
    manifest = json.loads(path.read_bytes())
    assert manifest["dataset_id"] == row["dataset_id"]
    assert manifest["quality_status"] == row["quality_status"]
    assert manifest["validation_allowed"] is (row["quality_status"] == "SAFE")


def test_safe_only_validation():
    assert REG["validation_allowed_statuses"] == ["SAFE"]


def test_active_status_matches_index():
    shard_count = INDEX_ROOT.get("shard_count")
    expected = (
        "SAFE"
        if INDEX_ROOT["active_data_status"] == "SAFE"
        else ("PARTIAL" if shard_count else "NO_DATA")
    )
    assert INDEX_ROOT["active_data_status"] == expected
    assert REG["active_dataset"]["status"] == expected
    assert REG["active_dataset"]["validation_allowed"] is (expected == "SAFE")
    # SAFE means replay/validation data quality only. It must never be promoted
    # into profitability proof without a separate costed OOS/forward result.
    assert REG["active_dataset"]["proof_of_pnl_allowed"] is False


def test_every_status_counter_is_index_bound():
    from collections import Counter

    counts = Counter(row["quality_status"] for row in _index_rows())
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
    if not INDEX_ROOT.get("shard_count"):
        assert INDEX_ROOT["active_data_status"] == "NO_DATA"


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
    rows = _index_rows()
    with ThreadPoolExecutor(max_workers=64) as pool:
        while batch := list(islice(rows, 8192)):
            for _ in pool.map(_validate_manifest, batch):
                pass


def test_dataset_quality_ci_budget_covers_full_catalog_validation():
    """The large read-only catalog scan must not hit a 10-minute runner cap."""
    workflow = (ROOT / ".github/workflows/dataset-quality-ci.yml").read_text(encoding="utf-8")
    job = workflow.split("  quality:\n", 1)[1].split("    steps:\n", 1)[0]
    timeout = next(int(line.split(":", 1)[1].strip()) for line in job.splitlines()
                   if line.strip().startswith("timeout-minutes:"))
    assert timeout >= 30
