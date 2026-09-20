from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from hl_observer.datasets.github_release_bridge import DatasetRecord, ReleaseAsset
from hl_observer.datasets.streaming_materializer import materialize_records_streaming


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def test_streaming_materializer_extracts_zip_and_rebuilds_chunks(tmp_path: Path) -> None:
    source_assets = tmp_path / "source_assets"
    cache = tmp_path / "cache"
    output = tmp_path / "output"
    source_assets.mkdir()

    zip_path = source_assets / "pack.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("runtime/data/a.jsonl", b'{"a":1}\n')
        archive.writestr("runtime/data/b.jsonl", b'{"b":2}\n')

    original_large = b"0123456789" * 200
    part1 = source_assets / "part1.bin"
    part2 = source_assets / "part2.bin"
    part1.write_bytes(original_large[:900])
    part2.write_bytes(original_large[900:])

    assets = {
        "pack.zip": ReleaseAsset(
            asset_id=1,
            name="pack.zip",
            size=zip_path.stat().st_size,
            digest=f"sha256:{_sha256(zip_path)}",
        ),
        "part1.bin": ReleaseAsset(
            asset_id=2,
            name="part1.bin",
            size=part1.stat().st_size,
            digest=f"sha256:{_sha256(part1)}",
        ),
        "part2.bin": ReleaseAsset(
            asset_id=3,
            name="part2.bin",
            size=part2.stat().st_size,
            digest=f"sha256:{_sha256(part2)}",
        ),
    }

    records = [
        DatasetRecord(
            relative_path="runtime/data/a.jsonl",
            size=len(b'{"a":1}\n'),
            sha256=hashlib.sha256(b'{"a":1}\n').hexdigest(),
            storage="zip_entry",
            asset="pack.zip",
        ),
        DatasetRecord(
            relative_path="runtime/data/b.jsonl",
            size=len(b'{"b":2}\n'),
            sha256=hashlib.sha256(b'{"b":2}\n').hexdigest(),
            storage="zip_entry",
            asset="pack.zip",
        ),
        DatasetRecord(
            relative_path="runtime/data/large.bin",
            size=len(original_large),
            sha256=hashlib.sha256(original_large).hexdigest(),
            storage="raw_chunks",
            chunks=(
                {"asset": "part1.bin", "part": 1},
                {"asset": "part2.bin", "part": 2},
            ),
        ),
    ]

    def fake_download(asset: ReleaseAsset, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / asset.name
        shutil.copy2(source_assets / asset.name, destination)
        return destination

    result = materialize_records_streaming(
        records,
        assets,
        output,
        cache,
        repository="Rapt0r06300/hypersmart-datasets",
        purge_assets_after_use=True,
        downloader=fake_download,
    )

    assert (output / "runtime/data/a.jsonl").read_bytes() == b'{"a":1}\n'
    assert (output / "runtime/data/b.jsonl").read_bytes() == b'{"b":2}\n'
    assert (output / "runtime/data/large.bin").read_bytes() == original_large
    assert result["created_files"] == 3
    assert result["downloaded_asset_count"] == 3
    assert result["purged_asset_count"] == 3
    assert not any(cache.iterdir())


def test_streaming_materializer_rejects_path_escape(tmp_path: Path) -> None:
    source_assets = tmp_path / "source_assets"
    cache = tmp_path / "cache"
    output = tmp_path / "output"
    source_assets.mkdir()

    zip_path = source_assets / "pack.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("../escape.txt", b"bad")

    asset = ReleaseAsset(
        asset_id=1,
        name="pack.zip",
        size=zip_path.stat().st_size,
        digest=f"sha256:{_sha256(zip_path)}",
    )
    record = DatasetRecord(
        relative_path="../escape.txt",
        size=3,
        sha256=hashlib.sha256(b"bad").hexdigest(),
        storage="zip_entry",
        asset="pack.zip",
    )

    def fake_download(asset: ReleaseAsset, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / asset.name
        shutil.copy2(source_assets / asset.name, destination)
        return destination

    import pytest

    with pytest.raises(Exception):
        materialize_records_streaming(
            [record],
            {"pack.zip": asset},
            output,
            cache,
            repository="Rapt0r06300/hypersmart-datasets",
            purge_assets_after_use=True,
            downloader=fake_download,
        )
