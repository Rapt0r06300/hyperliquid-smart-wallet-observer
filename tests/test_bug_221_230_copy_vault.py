from hl_observer.backtesting.copy_vault_evidence_inventory import (
    artifact_inventory_receipt,
    catalog_asset_reference_receipt,
    compressed_content_receipt,
    declared_size_receipt,
    manifest_payload_receipt,
    partial_state_repair_receipt,
    receipt_contract_version_receipt,
    release_separation_receipt,
    shard_id_hash_receipt,
    upload_manifest_order_receipt,
)


def test_bug_221_manifest_binds_payload():
    assert manifest_payload_receipt(manifest_sha256="a", payload_sha256="a", payload_present=True)["status"] == "PROVEN"
    assert manifest_payload_receipt(manifest_sha256="a", payload_sha256="b", payload_present=True)["status"] == "REJECTED"


def test_bug_222_missing_asset_is_rejected():
    row = {"exists": True, "regular_file": True, "symlink": False, "sha256": "a" * 64}
    assert artifact_inventory_receipt([row])["status"] == "PROVEN"
    assert artifact_inventory_receipt([{**row, "exists": False}])["status"] == "REJECTED"


def test_bug_223_compressed_content_is_verified():
    assert compressed_content_receipt(source_sha256="a", content_sha256="a", content_verified=True)["status"] == "PROVEN"
    assert compressed_content_receipt(source_sha256="a", content_sha256="b", content_verified=False)["status"] == "REJECTED"


def test_bug_224_manifest_publishes_after_upload():
    assert upload_manifest_order_receipt(upload_complete=True, manifest_published=True)["status"] == "PROVEN"
    assert upload_manifest_order_receipt(upload_complete=False, manifest_published=True)["status"] == "REJECTED"


def test_bug_225_releases_do_not_mix():
    assert release_separation_receipt(release_ids=["r1", "r1"])["status"] == "PROVEN"
    assert release_separation_receipt(release_ids=["r1", "r2"])["status"] == "REJECTED"


def test_bug_226_catalog_references_resolve():
    assert catalog_asset_reference_receipt(indexed_assets=["a"], available_assets=["a", "b"])["status"] == "PROVEN"
    assert catalog_asset_reference_receipt(indexed_assets=["c"], available_assets=["a", "b"])["status"] == "REJECTED"


def test_bug_227_declared_size_matches_observation():
    assert declared_size_receipt(declared_bytes=3, actual_bytes=3)["status"] == "PROVEN"
    assert declared_size_receipt(declared_bytes=3, actual_bytes=4)["status"] == "REJECTED"


def test_bug_228_shard_ids_are_collision_free():
    assert shard_id_hash_receipt(shard_ids=["a", "b"], shard_hashes=["x", "y"])["status"] == "PROVEN"
    assert shard_id_hash_receipt(shard_ids=["a", "a"], shard_hashes=["x", "y"])["status"] == "REJECTED"


def test_bug_229_receipt_uses_current_contract():
    assert receipt_contract_version_receipt(receipt_code_sha="a", contract_code_sha="a")["status"] == "PROVEN"
    assert receipt_contract_version_receipt(receipt_code_sha="a", contract_code_sha="b")["status"] == "REJECTED"


def test_bug_230_partial_state_needs_repair_before_safe():
    assert partial_state_repair_receipt(state="PARTIAL", repair_complete=True, safe_label="SAFE")["status"] == "PROVEN"
    assert partial_state_repair_receipt(state="PARTIAL", repair_complete=False, safe_label="SAFE")["status"] == "REJECTED"
