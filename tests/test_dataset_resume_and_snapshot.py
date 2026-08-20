from __future__ import annotations

import hashlib
from pathlib import Path

from hl_observer.datasets.github_release_bridge import ReleaseAsset
from hl_observer.datasets.progress_downloader import cache_transfer_plan
from hl_observer.ops.dataset_bridge import snapshot_fingerprint


def _asset(name: str, payload: bytes, asset_id: int = 1) -> ReleaseAsset:
    return ReleaseAsset(
        asset_id=asset_id,
        name=name,
        size=len(payload),
        digest="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def test_cache_plan_ne_recompte_pas_un_asset_final_verifie(tmp_path: Path) -> None:
    payload = b"abcdefghij"
    asset = _asset("part-001.bin", payload)
    cache = tmp_path / "data/hypersmart_datasets/assets"
    cache.mkdir(parents=True)
    (cache / asset.name).write_bytes(payload)

    plan = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name])

    assert plan["verified_cache_bytes"] == len(payload)
    assert plan["remaining_network_bytes"] == 0


def test_cache_plan_compte_seulement_la_fin_manquante_du_part(tmp_path: Path) -> None:
    payload = b"abcdefghij"
    asset = _asset("part-002.bin", payload)
    cache = tmp_path / "data/hypersmart_datasets/assets"
    cache.mkdir(parents=True)
    (cache / (asset.name + ".part")).write_bytes(payload[:6])

    plan = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name])

    assert plan["partial_cache_bytes"] == 6
    assert plan["remaining_network_bytes"] == 4


def test_force_recompte_integralement_meme_si_cache_present(tmp_path: Path) -> None:
    payload = b"abcdefghij"
    asset = _asset("part-003.bin", payload)
    cache = tmp_path / "data/hypersmart_datasets/assets"
    cache.mkdir(parents=True)
    (cache / asset.name).write_bytes(payload)

    plan = cache_transfer_plan(tmp_path, {asset.name: asset}, [asset.name], force=True)

    assert plan["remaining_network_bytes"] == len(payload)


def test_snapshot_fingerprint_change_si_manifeste_ou_asset_change(tmp_path: Path) -> None:
    manifest = tmp_path / "FULL_UPLOADED_FILE_MANIFEST.jsonl.gz"
    manifest.write_bytes(b"manifest-v1")
    release = {"name": "FULL", "tag_name": "full", "published_at": "2026-08-16"}
    asset = _asset("part.bin", b"abc", 10)
    first = snapshot_fingerprint(
        manifest,
        release,
        {asset.name: asset},
        repository="Rapt0r06300/hypersmart-datasets",
        release_id=371149058,
    )
    manifest.write_bytes(b"manifest-v2")
    second = snapshot_fingerprint(
        manifest,
        release,
        {asset.name: asset},
        repository="Rapt0r06300/hypersmart-datasets",
        release_id=371149058,
    )
    assert len(first) == 64
    assert first != second
