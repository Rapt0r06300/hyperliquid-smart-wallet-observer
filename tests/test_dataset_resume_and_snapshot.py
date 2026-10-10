from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from hl_observer.datasets.github_release_bridge import ReleaseAsset
from hl_observer.datasets.progress_downloader import cache_transfer_plan
from hl_observer.ops.dataset_bridge import snapshot_fingerprint
from hl_observer.control_plane.resumable_campaign import CampaignManifest, sha256_json


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


def test_resumable_campaign_validate_digest_matches_raw_manifest(tmp_path: Path) -> None:
    manifest = CampaignManifest(
        campaign_id="analysis-e3-pnl-proof-v2",
        kind="module_pnl_proof",
        code_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        code_sha="a" * 40,
        dataset_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        dataset_generation="V2_FRESH",
        config_sha256="b" * 64,
        work_plan_sha256="c" * 64,
        expires_at="2026-10-07T00:00:00+00:00",
        created_at="2026-09-29T00:00:00+00:00",
        schema_version="alina.resumable_campaign.v2",
        creation_phase="ANALYZE",
        phase_epoch=3,
        source_collection_epoch=2,
        collection_cutoff_at_utc="2026-09-29T10:56:59Z",
        dataset_selection_id="d" * 64,
        analysis_stage="PNL_PROOF",
    )
    raw = manifest.to_dict()
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(raw, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "tools/resumable_campaign.py", "validate", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == sha256_json(raw)


def test_v2_legacy_external_dataset_repository_is_refused(tmp_path: Path) -> None:
    manifest = CampaignManifest(
        campaign_id="foreign-data-refused", kind="market_collection",
        code_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        code_sha="a" * 40, dataset_repo="Rapt0r06300/alina-smartflow-datasets-v2",
        dataset_generation="V2_FRESH", config_sha256="b" * 64,
        work_plan_sha256="c" * 64, expires_at="2026-10-07T00:00:00+00:00",
        created_at="2026-09-29T00:00:00+00:00",
        schema_version="alina.resumable_campaign.v2",
        creation_phase="COLLECT", phase_epoch=3,
    )
    path = tmp_path / "invalid-campaign.json"
    path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/resumable_campaign.py", "validate", str(path)],
        check=False, capture_output=True, text=True,
    )
    assert completed.returncode != 0
    assert "canonical Alina repository" in completed.stderr
