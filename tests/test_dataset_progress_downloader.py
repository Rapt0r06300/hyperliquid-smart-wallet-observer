from __future__ import annotations

import hashlib
from pathlib import Path

from hl_observer.datasets import progress_downloader
from hl_observer.datasets.github_release_bridge import ReleaseAsset
from hl_observer.datasets.progress_downloader import human_bytes, human_eta


def test_human_bytes_reste_lisible() -> None:
    assert human_bytes(0) == "0.00 B"
    assert human_bytes(1024) == "1.00 KiB"
    assert human_bytes(1024 * 1024) == "1.00 MiB"
    assert human_bytes(1024 * 1024 * 1024) == "1.00 GiB"


def test_human_eta_reste_lisible() -> None:
    assert human_eta(None) == "--:--:--"
    assert human_eta(0) == "00:00:00"
    assert human_eta(65) == "00:01:05"
    assert human_eta(3661) == "01:01:01"


def test_downloader_autonome_utilise_le_transport_et_verifie_le_sha(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    payload = b"asset-prive-verifie"
    asset = ReleaseAsset(
        asset_id=123,
        name="asset.bin",
        size=len(payload),
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
    )
    calls: list[tuple[str, int]] = []

    def fake_download(*, repository, asset_id, destination, chunk_bytes=4 * 1024 * 1024):
        calls.append((repository, asset_id))
        destination.write_bytes(payload)

    monkeypatch.setattr(progress_downloader, "download_release_asset", fake_download)
    result = progress_downloader.download_needed_assets_with_progress(
        tmp_path,
        {asset.name: asset},
        [asset.name],
        repository="exemple/prive",
        heartbeat_seconds=0.01,
    )

    destination = result[asset.name]
    assert destination.read_bytes() == payload
    assert calls == [("exemple/prive", 123)]
    output = capsys.readouterr().out
    assert "SHA256 OK" in output
    assert "TOTAL=100.0%" in output
