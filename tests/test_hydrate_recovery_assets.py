"""Bounded quarantine hydration: default dry-run, immutable cache preserved."""
from __future__ import annotations
import hashlib
from tools import hydrate_recovery_assets as h

SHA_A="a"*64
SHA_B="b"*64


def rows():
    return {"shards": [
        {"dataset_id": "a", "family": "l2book", "quality_status": "PARTIAL",
         "replay_compatible": False, "release_tag": "tag",
         "release_asset": "a.jsonl.gz", "release_container_asset": "pack.zip",
         "release_remote_size": 100, "release_remote_digest": "sha256:" + SHA_B,
         "bytes": 13, "sha256": SHA_A},
        {"dataset_id": "b", "family": "l2book", "quality_status": "REJECT",
         "replay_compatible": False, "release_tag": "tag",
         "release_asset": "b.jsonl.gz", "release_container_asset": "pack.zip",
         "release_remote_size": 100, "release_remote_digest": "sha256:" + SHA_B,
         "bytes": 14, "sha256": SHA_A},
    ]}


def test_selects_unique_release_asset_under_budget():
    plan = h.select_assets(rows(), {("tag","pack.zip"): (100,SHA_B)})
    assert plan["candidate_shards"] == 2
    assert plan["selected_unique_outer_assets"] == 1
    assert plan["selected_source_asset_bytes"] == 100
    assert plan["complete_coverage_claimed"] is False
    assert plan["selection"][0]["source_url"].startswith(
        "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/releases/download/"
    )
    limited = h.select_assets(rows(), {("tag","pack.zip"): (100,SHA_B)}, max_bytes=99)
    assert limited["selected_unique_outer_assets"] == 0
    assert limited["deferred_or_excluded_outer_assets_by_reason"]["BUDGET_DEFERRED"] == 1


def test_default_dry_run_does_not_create_any_file(tmp_path):
    cache=tmp_path/"releases"
    cache.mkdir()
    plan=h.select_assets(rows(), {("tag","pack.zip"): (100,SHA_B)})
    report=h.hydrate_selected(plan,cache)
    assert report["source_asset_outcomes"][0]["status"]=="NOT_DOWNLOADED_DRY_RUN"
    assert not (cache/"tag").exists()
    assert report["recovered_shards"] is None


def test_conflicted_source_is_never_overwritten(tmp_path):
    cache=tmp_path/"releases"
    (cache/"tag").mkdir(parents=True)
    path=cache/"tag"/"pack.zip"
    path.write_bytes(b"original-corruption")
    plan=h.select_assets(rows(), {("tag","pack.zip"): (100,SHA_B)})
    report=h.hydrate_selected(plan,cache,execute=True)
    assert report["source_asset_outcomes"][0]["status"]=="CACHE_CONFLICT_PRESERVED"
    assert path.read_bytes()==b"original-corruption"


def test_download_uses_existing_verified_restorer_not_reimplementation(monkeypatch,tmp_path):
    cache=tmp_path/"releases"
    cache.mkdir()
    plan=h.select_assets(rows(), {("tag","pack.zip"): (100,SHA_B)})
    calls=[]
    def fake_download(asset, destination, **kwargs):
        calls.append((asset["name"], asset["digest"], str(destination)))
        return {"verification_status":"VERIFIED"}
    monkeypatch.setattr(h,"download_asset",fake_download)
    result=h.hydrate_selected(plan,cache,execute=True)
    assert result["downloaded_or_reused_verified_assets"]==1
    assert calls[0][0]=="pack.zip"
    assert calls[0][1]=="sha256:"+SHA_B
    assert result["replay_certified"] is False


def test_pagination_advances_unique_outer_assets_without_quadratic_lookup():
    index=rows()
    next_item=dict(index["shards"][0], dataset_id="c", release_tag="tag2")
    index["shards"].append(next_item)
    assets={("tag","pack.zip"):(100,SHA_B),("tag2","pack.zip"):(100,SHA_B)}
    first=h.select_assets(index,assets,max_assets=1,asset_offset=0)
    second=h.select_assets(index,assets,max_assets=1,asset_offset=1)
    assert first["eligible_unique_outer_assets"]==2
    assert second["eligible_unique_outer_assets"]==2
    assert first["selection"][0]["release_tag"]=="tag"
    assert second["selection"][0]["release_tag"]=="tag2"
    assert second["asset_offset"]==1
