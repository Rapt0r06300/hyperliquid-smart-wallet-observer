from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.datasets.v2_repository import (
    DatasetV2Error,
    SafeShard,
    select_safe_shards,
)


def _safe_row(**overrides):
    row = {
        "dataset_id": "x",
        "family": "l2Book",
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 100,
        "end_ts_ms": 200,
        "sha256": "a" * 64,
        "bytes": 123,
        "event_count": 10,
        "quality_status": "SAFE",
        "replay_compatible": True,
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "v2-test",
        "release_asset": "x.jsonl.gz",
        "manifest_path": "datasets/safe/x.manifest.json",
    }
    row.update(overrides)
    return row


def test_selector_only_exposes_safe_rows() -> None:
    index = {
        "schema": "alina.data_index.v2",
        "shards": [
            _safe_row(),
            _safe_row(dataset_id="partial", quality_status="PARTIAL"),
            _safe_row(dataset_id="wrong-symbol", symbol="ETHUSDT"),
        ],
    }
    rows = select_safe_shards(index, symbols=["BTCUSDT"])
    assert [row.dataset_id for row in rows] == ["x"]


def test_safe_row_requires_exact_release_locator() -> None:
    with pytest.raises(DatasetV2Error):
        SafeShard.from_index_row(_safe_row(release_tag=""))


def test_foreign_release_repository_is_refused() -> None:
    with pytest.raises(DatasetV2Error):
        SafeShard.from_index_row(
            _safe_row(release_repository="someone/another-dataset")
        )


def test_time_window_requires_full_immutable_shard_containment() -> None:
    index = {
        "shards": [
            _safe_row(dataset_id="old", start_ts_ms=0, end_ts_ms=99),
            _safe_row(dataset_id="left-overlap", start_ts_ms=100, end_ts_ms=200),
            _safe_row(dataset_id="contained", start_ts_ms=150, end_ts_ms=250),
            _safe_row(dataset_id="right-overlap", start_ts_ms=201, end_ts_ms=300),
        ]
    }
    rows = select_safe_shards(index, start_ts_ms=150, end_ts_ms=250)
    assert [row.dataset_id for row in rows] == ["contained"]


def test_selector_refuses_safe_without_replay_compatibility() -> None:
    index={"shards":[_safe_row(dataset_id="no-replay", replay_compatible=False)]}
    assert select_safe_shards(index) == []



def test_safe_packed_release_shard_materializes_inner_verified_payload(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile
    from hl_observer.datasets.v2_repository import download_safe_shard

    payload = b"immutable-gzip-data"
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("inner.jsonl.gz", payload)
    packed = archive_bytes.getvalue()
    row = _safe_row(
        release_asset="inner.jsonl.gz",
        release_storage="zip_entry",
        release_container_asset="packed-shards-0000.zip",
        release_member="inner.jsonl.gz",
        release_remote_size=len(packed),
        release_remote_digest="sha256:" + hashlib.sha256(packed).hexdigest(),
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    shard = SafeShard.from_index_row(row)

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield packed

    def fake_get(url, **_kwargs):
        assert url.endswith("/packed-shards-0000.zip")
        return Response()

    monkeypatch.setattr("hl_observer.datasets.v2_repository.requests.get", fake_get)
    result = download_safe_shard(shard, tmp_path / "inner.jsonl.gz")
    assert result.read_bytes() == payload
    assert not (tmp_path / "inner.jsonl.gz.archive.part").exists()


def test_packed_release_rejects_wrong_outer_archive_digest(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile
    from hl_observer.datasets.v2_repository import download_safe_shard
    payload = b"valid-inner"
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr("inner.jsonl.gz", payload)
    archive_bytes = raw.getvalue()
    shard = SafeShard.from_index_row(_safe_row(
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        release_asset="inner.jsonl.gz",
        release_storage="zip_entry",
        release_container_asset="packed-shards-0000.zip",
        release_member="inner.jsonl.gz",
        release_remote_size=len(archive_bytes),
        release_remote_digest="sha256:" + "0" * 64,
    ))
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield archive_bytes
    monkeypatch.setattr("hl_observer.datasets.v2_repository.requests.get", lambda *_a, **_kw: Response())
    with pytest.raises(DatasetV2Error, match="ZIP size/SHA"):
        download_safe_shard(shard, tmp_path / "inner.jsonl.gz")
    assert not (tmp_path / "inner.jsonl.gz").exists()


def test_packed_release_rejects_untrusted_member_locator():
    with pytest.raises(DatasetV2Error, match="packed SAFE"):
        SafeShard.from_index_row(_safe_row(
            release_storage="zip_entry", release_asset="../escape.jsonl.gz",
            release_member="../escape.jsonl.gz",
            release_container_asset="packed.zip",
            release_remote_size=100, release_remote_digest="sha256:" + "a" * 64,
        ))
