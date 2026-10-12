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
    assert archive == tmp_path / "catalog" / "reclassification-history" / f"{digest}.json"
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
