from __future__ import annotations

import hashlib
from pathlib import Path

from hl_observer.datasets.github_release_bridge import ReleaseAsset
from hl_observer.datasets.progress_downloader import cache_transfer_plan


def _asset(payload: bytes = b"contenu-attendu") -> ReleaseAsset:
    return ReleaseAsset(
        asset_id=321,
        name="asset.bin",
        size=len(payload),
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def test_plan_signale_un_cache_final_corrompu_sans_le_detruire(tmp_path: Path) -> None:
    asset = _asset()
    cache = tmp_path / "data" / "hypersmart_datasets" / "assets"
    cache.mkdir(parents=True)
    destination = cache / asset.name
    destination.write_bytes(b"x" * asset.size)

    plan = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name])

    assert plan["verified_cache_bytes"] == 0
    assert plan["remaining_network_bytes"] == asset.size
    assert plan["invalid_cached_names"] == [asset.name]
    assert destination.is_file(), "la planification doit rester non destructive"


def test_plan_distingue_cache_verifie_et_partiel_reutilisable(tmp_path: Path) -> None:
    payload = b"contenu-attendu"
    asset = _asset(payload)
    cache = tmp_path / "data" / "hypersmart_datasets" / "assets"
    cache.mkdir(parents=True)
    destination = cache / asset.name
    destination.write_bytes(payload)

    verified = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name])
    assert verified["verified_cache_bytes"] == asset.size
    assert verified["remaining_network_bytes"] == 0
    assert verified["invalid_cached_names"] == []

    destination.unlink()
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.write_bytes(payload[:5])
    resumed = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name])
    assert resumed["partial_cache_bytes"] == 5
    assert resumed["remaining_network_bytes"] == asset.size - 5
    assert resumed["partial_cache_names"] == [asset.name]
