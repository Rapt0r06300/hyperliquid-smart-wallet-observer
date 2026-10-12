"""Fail-closed preservation of original quarantine manifests during SAFE repair."""
from __future__ import annotations

import hashlib

import pytest

from tools.repair_stale_safe_classifications import _archive_prior_manifest


def test_archives_identical_original_bytes_without_overwriting(tmp_path):
    source = tmp_path / "datasets" / "quarantine" / "x.manifest.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{"quality_status":"PARTIAL","evidence":"original"}\\n')
    archive, digest = _archive_prior_manifest(tmp_path, source)
    assert archive == tmp_path / "datasets" / "quarantine" / "reclassification-history" / f"{digest}.original"
    assert archive.read_bytes() == source.read_bytes()
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert _archive_prior_manifest(tmp_path, source) == (archive, digest)
    assert source.exists()


def test_refuses_clashing_or_modified_historical_evidence(tmp_path):
    source = tmp_path / "datasets" / "quarantine" / "x.manifest.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"untouched")
    archive, _ = _archive_prior_manifest(tmp_path, source)
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="DIGEST_CONFLICT"):
        _archive_prior_manifest(tmp_path, source)
    assert source.read_bytes() == b"untouched"


def test_refuses_source_outside_repo(tmp_path):
    base = tmp_path / "repo"
    base.mkdir()
    outside = tmp_path / "not-repo"
    outside.write_bytes(b"data")
    with pytest.raises(ValueError, match="UNSAFE_OR_MISSING_SOURCE"):
        _archive_prior_manifest(base, outside)



def test_dry_run_reclassification_preserves_original_manifest_and_catalog(tmp_path, monkeypatch):
    import json
    from tools import repair_stale_safe_classifications as repair_module

    index_file = tmp_path / "catalog" / "DATA_INDEX.json"
    index_file.parent.mkdir()
    manifest_path = tmp_path / "datasets" / "quarantine" / "a.manifest.json"
    manifest_path.parent.mkdir(parents=True)
    sha = "a" * 64
    manifest_path.write_text(json.dumps({
        "dataset_id": "a", "quality_status": "PARTIAL",
        "sha256": sha, "record_count": 4,
    }))
    index_file.write_text(json.dumps({
        "schema": "alina.data_index.v2",
        "shards": [{"dataset_id": "a", "sha256": sha,
                    "quality_status": "PARTIAL",
                    "manifest_path": "datasets/quarantine/a.manifest.json",
                    "record_count": 4}],
    }))
    registry_file = tmp_path / "catalog" / "DATA_QUALITY_REGISTRY.json"
    catalog_file = tmp_path / "catalog" / "DATA_CATALOG.json"
    registry_file.write_text("{}")
    catalog_file.write_text("{}")
    originals = {p: p.read_bytes() for p in (
        index_file, manifest_path, registry_file, catalog_file,
    )}
    monkeypatch.setattr(repair_module, "_normalize_manifest", dict)
    monkeypatch.setattr(repair_module, "_compact_index_row", dict)
    monkeypatch.setattr(repair_module, "classify_manifest", lambda _: ("SAFE", []))
    monkeypatch.setattr(repair_module, "_valid_release_locator", lambda _: True)
    result = repair_module.repair(tmp_path, dry_run=True)
    assert result["status"] == "DRY_RUN_NOT_RECLASSIFIED"
    assert result["candidate_count"] == 1
    assert result["candidate_record_count"] == 4
    assert result["quarantine_unchanged"] is True
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert not (tmp_path / "datasets" / "safe").exists()
    assert not (tmp_path / "datasets" / "quarantine" / "reclassification-history").exists()



def test_quarantine_publisher_stages_exact_original_before_commit():
    from pathlib import Path
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "quarantine-audit.yml"
    ).read_text(encoding="utf-8")
    assert "git add -A -- datasets/quarantine" in workflow
    assert "RECLASSIFICATION_ARCHIVE_NOT_STAGED" in workflow
    assert "RECLASSIFICATION_ARCHIVE_NOT_STAGED" in workflow
    assert workflow.index("git add -A -- datasets/quarantine") < workflow.index(
        'git commit -m "fix(dataset): repair stale classifications with provenance"'
    )


def test_reclassification_prevents_loss_of_indexed_shards():
    from tools.repair_stale_safe_classifications import _assert_shard_identity_preserved
    prior = [{"dataset_id": "a", "sha256": "a" * 64, "quality_status": "SAFE"},
             {"dataset_id": "b", "sha256": "b" * 64, "quality_status": "PARTIAL"}]
    good = [dict(prior[1], quality_status="SAFE"), dict(prior[0])]
    _assert_shard_identity_preserved(prior, good)
    with pytest.raises(ValueError, match="LOST_OR_ADDED_SHARD"):
        _assert_shard_identity_preserved(prior, good[:1])
    with pytest.raises(ValueError, match="CHANGED_SHARD_SHA"):
        _assert_shard_identity_preserved(prior, [dict(good[0], sha256="c" * 64), good[1]])
    with pytest.raises(ValueError, match="DUPLICATE_OR_MISSING_SHARD"):
        _assert_shard_identity_preserved(prior, [good[0], good[0]])
    with pytest.raises(ValueError, match="DEMOTED_SAFE_SHARD"):
        _assert_shard_identity_preserved(prior, [good[0], dict(good[1], quality_status="PARTIAL")])
