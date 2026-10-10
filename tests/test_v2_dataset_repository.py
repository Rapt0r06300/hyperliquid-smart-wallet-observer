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



def test_packed_shard_uses_logical_member_when_redundant_locator_omitted():
    row = _safe_row(
        release_asset="x.jsonl.gz",
        release_storage="zip_entry",
        release_container_asset="packed-shards-0000.zip",
        release_remote_digest="sha256:" + "b" * 64,
        release_remote_size=1000,
    )
    shard = SafeShard.from_index_row(row)
    assert shard.release_member == "x.jsonl.gz"
    assert shard.release_container_asset == "packed-shards-0000.zip"



def test_selector_resolves_canonical_inherited_repository_only_when_declared():
    compact = _safe_row()
    compact.pop("release_repository")
    selected = select_safe_shards({
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "shards": [compact],
    })
    assert len(selected) == 1
    assert selected[0].release_repository == "Rapt0r06300/hyperliquid-smart-wallet-observer"

    with pytest.raises(DatasetV2Error, match="missing"):
        select_safe_shards({"shards": [compact]})
    with pytest.raises(DatasetV2Error, match="foreign"):
        select_safe_shards({"release_repository_default": "another/repo", "shards": [compact]})


def test_safe_release_download_retries_504_then_verifies_sha(tmp_path, monkeypatch):
    import hashlib
    import requests
    from hl_observer.datasets.v2_repository import download_safe_shard

    data = b"immutable trade history"
    shard = SafeShard.from_index_row(_safe_row(
        sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
    ))
    calls = []

    class Response:
        def __init__(self, status):
            self.status = status
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def raise_for_status(self):
            if self.status != 200:
                error_response = requests.Response()
                error_response.status_code = self.status
                raise requests.HTTPError(response=error_response)
        def iter_content(self, chunk_size):
            yield data

    def get(*_args, **_kwargs):
        calls.append(1)
        return Response(504 if len(calls) == 1 else 200)

    monkeypatch.setattr("hl_observer.datasets.v2_repository.requests.get", get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    path = tmp_path / "trades.jsonl.gz"
    assert download_safe_shard(shard, path).read_bytes() == data
    assert len(calls) == 2
    assert not path.with_suffix(".gz.part").exists()


def test_safe_release_download_does_not_retry_404(tmp_path, monkeypatch):
    import requests
    from hl_observer.datasets.v2_repository import download_safe_shard

    calls = []

    class NotFound:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def raise_for_status(self):
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)

    def get(*_args, **_kwargs):
        calls.append(1)
        return NotFound()

    monkeypatch.setattr("hl_observer.datasets.v2_repository.requests.get", get)
    with pytest.raises(DatasetV2Error, match="HTTP 404"):
        download_safe_shard(SafeShard.from_index_row(_safe_row()), tmp_path / "trades.jsonl.gz")
    assert len(calls) == 1


def test_safe_release_stream_retry_removes_partial_bytes(tmp_path, monkeypatch):
    import hashlib
    import requests
    from hl_observer.datasets.v2_repository import download_safe_shard

    data = b"verified-data"
    shard = SafeShard.from_index_row(_safe_row(
        sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
    ))
    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size):
            if len(calls) == 1:
                yield b"bad-prefix"
                raise requests.ConnectionError("connection reset")
            yield data

    def get(*_args, **_kwargs):
        calls.append(1)
        return Response()

    monkeypatch.setattr("hl_observer.datasets.v2_repository.requests.get", get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    path = tmp_path / "trades.jsonl.gz"
    assert download_safe_shard(shard, path).read_bytes() == data
    assert len(calls) == 2
    assert not path.with_suffix(".gz.part").exists()


def test_remote_v2_reader_reconstructs_verified_partitions_without_network(monkeypatch):
    import hashlib
    import json
    from tools.partitioned_data_index import partition_index
    from hl_observer.datasets import v2_repository as module

    original = {
        "schema": "alina.data_index.v2",
        "release_repository_default": module.DEFAULT_REPOSITORY,
        "shards": [_safe_row(dataset_id=f"shard-{n}") for n in range(9)],
    }
    root, parts = partition_index(original, max_partition_bytes=650)
    raw_index = json.dumps(root).encode("utf-8")
    assets = {"catalog/DATA_INDEX.json": raw_index, **{
        "catalog/" + key: value for key, value in parts.items()
    }}
    calls = []
    class Response:
        def __init__(self, body):
            self.content = body
        def raise_for_status(self):
            return None
    def get(url, **_kwargs):
        path = url.split("/main/")[-1]
        calls.append(path)
        return Response(assets[path])
    monkeypatch.setattr(module.requests, "get", get)
    loaded, sha = module.load_index()
    assert loaded == original
    assert sha == hashlib.sha256(raw_index).hexdigest()
    assert len(calls) == len(parts) + 1
    assert len(module.select_safe_shards(loaded)) == 9


def test_remote_v2_reader_fails_closed_if_partition_bytes_corrupted(monkeypatch):
    import json
    from tools.partitioned_data_index import partition_index
    from hl_observer.datasets import v2_repository as module

    root, parts = partition_index({
        "schema": "alina.data_index.v2",
        "shards": [_safe_row(dataset_id="one")],
    })
    assets = {"catalog/DATA_INDEX.json": json.dumps(root).encode(), **{
        "catalog/" + key: b"corrupt" for key in parts
    }}
    class Response:
        def __init__(self, body): self.content = body
        def raise_for_status(self): pass
    monkeypatch.setattr(
        module.requests, "get",
        lambda url, **_k: Response(assets[url.split("/main/")[-1]]),
    )
    with pytest.raises(DatasetV2Error, match="SHA-256/size mismatch"):
        module.load_index()


def test_remote_v2_reader_refuses_partition_path_escape(monkeypatch):
    import json
    from tools.partitioned_data_index import partition_index
    from hl_observer.datasets import v2_repository as module

    root, parts = partition_index({
        "schema": "alina.data_index.v2",
        "shards": [_safe_row(dataset_id="one")],
    })
    root["partitions"][0]["path"] = "../bad.json"
    calls = []
    class Response:
        content = json.dumps(root).encode()
        def raise_for_status(self): pass
    def get(url, **_kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(module.requests, "get", get)
    with pytest.raises(DatasetV2Error, match="partition path"):
        module.load_index()
    assert len(calls) == 1
