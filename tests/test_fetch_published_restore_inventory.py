"""Published restore-inventory resolver is bounded and SHA-verified."""
from __future__ import annotations

import hashlib
import pytest
from tools import fetch_published_restore_inventory as subject


def _release(payload: bytes, *, digest: str | None = None):
    return [{
        "tag_name": "alina-restore-inventory-fixture",
        "assets": [{
            "id": 42, "name": subject.ASSET, "state": "uploaded",
            "size": len(payload),
            "digest": "sha256:" + (digest or hashlib.sha256(payload).hexdigest()),
            "browser_download_url": (
                f"https://github.com/{subject.REPO}/releases/download/"
                "alina-restore-inventory-fixture/RESTORE_INVENTORY.json.gz"),
        }],
    }]


def test_fetch_one_metadata_page_and_download_verified_asset(monkeypatch, tmp_path):
    payload = b"verified-gz-fixture"
    queries = []
    monkeypatch.setattr(subject, "_json", lambda url, **kw:
                        (queries.append(url) or _release(payload)))
    def download(url, path, **kwargs):
        path.write_bytes(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(subject, "_download_to_path", download)
    output = tmp_path / subject.ASSET
    result = subject.obtain_verified_inventory(output, token="test")
    assert result["status"] == "PUBLISHED_INVENTORY_ASSET_SHA256_VERIFIED_NOT_RESTORED"
    assert result["raw_market_payloads_downloaded"] == 0
    assert output.read_bytes() == payload
    assert len(queries) == 1
    reused = subject.obtain_verified_inventory(output)
    assert reused["cache_reused_verified"] is True


def test_fetch_blocks_digest_mismatch_and_preserves_cache(monkeypatch, tmp_path):
    payload = b"correct"
    monkeypatch.setattr(subject, "_json", lambda *_a, **_kw: _release(payload))
    monkeypatch.setattr(subject, "_download_to_path",
                        lambda url, path, **kwargs: (path.write_bytes(b"wrong") or 5, "0" * 64))
    output = tmp_path / subject.ASSET
    with pytest.raises(ValueError, match="DOWNLOAD_DIGEST_MISMATCH"):
        subject.obtain_verified_inventory(output)
    assert not output.exists()
    output.write_bytes(b"untouched")
    with pytest.raises(ValueError, match="CACHE_DIGEST_CONFLICT"):
        subject.obtain_verified_inventory(output)
    assert output.read_bytes() == b"untouched"


def test_fetch_refuses_unknown_digest_or_source_url(monkeypatch):
    release = _release(b"payload")
    release[0]["assets"][0]["digest"] = "unknown"
    monkeypatch.setattr(subject, "_json", lambda *_a, **_kw: release)
    with pytest.raises(ValueError, match="NOT_VERIFIABLE"):
        subject.latest_inventory_asset()
    release[0]["assets"][0]["digest"] = "sha256:" + ("a" * 64)
    release[0]["assets"][0]["browser_download_url"] = "https://other.example/archive"
    with pytest.raises(ValueError, match="NOT_VERIFIABLE"):
        subject.latest_inventory_asset()


def test_inventory_lookup_is_bounded_without_unverified_fallback(monkeypatch):
    monkeypatch.setattr(subject, "_json", lambda *_a, **_kw: [{}] * 100)
    with pytest.raises(ValueError, match="NOT_FOUND"):
        subject.latest_inventory_asset(max_pages=2)
    with pytest.raises(ValueError, match="INVALID_PAGE_BOUND"):
        subject.latest_inventory_asset(max_pages=11)
