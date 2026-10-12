"""Legacy SAFE demotion must preserve the exact original proof before publication."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools import enforce_safe_replay_invariant as module


def _fixture(tmp_path, monkeypatch):
    root = tmp_path
    catalog = root / "catalog"
    catalog.mkdir()
    safe = root / "datasets" / "safe" / "a.manifest.json"
    safe.parent.mkdir(parents=True)
    source = {
        "dataset_id": "a", "sha256": "a" * 64,
        "quality_status": "SAFE", "quality_reasons": ["UNVERIFIED_REPLAY"],
        "replay_compatible": False,
    }
    safe.write_text(json.dumps(source) + "\n")
    index = catalog / "DATA_INDEX.json"
    index.write_text(json.dumps({
        "schema": "alina.data_index.v2",
        "shards": [{
            "dataset_id": "a", "sha256": "a" * 64,
            "quality_status": "SAFE", "replay_compatible": False,
            "manifest_path": "datasets/safe/a.manifest.json",
        }],
    }))
    data_catalog = catalog / "DATA_CATALOG.json"
    registry = catalog / "DATA_QUALITY_REGISTRY.json"
    data_catalog.write_text("{}")
    registry.write_text("{}")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "INDEX", index)
    monkeypatch.setattr(module, "CATALOG", data_catalog)
    monkeypatch.setattr(module, "REGISTRY", registry)
    monkeypatch.setattr(module, "_publish_canonical_index",
                        lambda path, data: path.write_text(json.dumps(data)))
    return safe, index, data_catalog, registry


def test_dry_run_never_rewrites_or_retires_source(tmp_path, monkeypatch):
    safe, index, catalog, registry = _fixture(tmp_path, monkeypatch)
    original = {p: p.read_bytes() for p in (safe, index, catalog, registry)}
    result = module.migrate(dry_run=True)
    assert result["planned_demotions"] == 1
    assert result["migrated"] == 0
    assert result["read_only"] is True
    assert all(p.read_bytes() == data for p, data in original.items())
    assert not (tmp_path / "datasets" / "quarantine").exists()


def test_migration_preserves_old_safe_receipt_by_sha256(tmp_path, monkeypatch):
    safe, index, catalog, registry = _fixture(tmp_path, monkeypatch)
    original = safe.read_bytes()
    expected = hashlib.sha256(original).hexdigest()
    result = module.migrate()
    history = tmp_path / "datasets" / "quarantine" / "reclassification-history" / (expected + ".original")
    moved = tmp_path / "datasets" / "quarantine" / "a.manifest.json"
    assert result["migrated"] == 1
    assert not safe.exists()
    assert history.read_bytes() == original
    assert json.loads(moved.read_text())["quality_status"] == "PARTIAL"
    assert json.loads(index.read_text())["shards"][0]["manifest_path"] == "datasets/quarantine/a.manifest.json"
    assert json.loads(catalog.read_text())["partial_shard_count"] == 1
    assert json.loads(registry.read_text())["active_dataset"]["proof_of_pnl_allowed"] is False


def test_failed_index_publication_keeps_original_safe_evidence(tmp_path, monkeypatch):
    safe, index, _, _ = _fixture(tmp_path, monkeypatch)
    original = safe.read_bytes()
    monkeypatch.setattr(module, "_publish_canonical_index",
                        lambda *_args: (_ for _ in ()).throw(ValueError("test index limit")))
    with pytest.raises(ValueError, match="test index limit"):
        module.migrate()
    assert safe.read_bytes() == original
    assert json.loads(index.read_text())["shards"][0]["quality_status"] == "SAFE"
    assert list((tmp_path / "datasets" / "quarantine" / "reclassification-history").glob("*.original"))


def test_conflicting_quarantine_target_never_erases_old_evidence(tmp_path, monkeypatch):
    safe, index, _, _ = _fixture(tmp_path, monkeypatch)
    target = tmp_path / "datasets" / "quarantine" / "a.manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"different":"proof"}')
    before = safe.read_bytes()
    with pytest.raises(ValueError, match="DESTINATION_CONFLICT"):
        module.migrate()
    assert safe.read_bytes() == before
    assert target.read_text() == '{"different":"proof"}'
    assert json.loads(index.read_text())["shards"][0]["quality_status"] == "SAFE"


def test_mismatched_source_sha_is_rejected_before_writes(tmp_path, monkeypatch):
    safe, index, _, _ = _fixture(tmp_path, monkeypatch)
    source = json.loads(safe.read_text())
    source["sha256"] = "b" * 64
    safe.write_text(json.dumps(source))
    original = index.read_bytes()
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        module.migrate()
    assert index.read_bytes() == original
    assert safe.exists()
