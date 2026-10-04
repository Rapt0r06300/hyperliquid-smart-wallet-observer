from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "publish_dataset_v2_release_test",
        ROOT / "tools" / "publish_dataset_v2_release.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_capacity_reserves_run_manifest_slot() -> None:
    module = _module()
    module.validate_release_capacity(999)
    with pytest.raises(module.PublishError):
        module.validate_release_capacity(1000)


def test_publish_uploads_data_assets_plus_one_run_manifest_only(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests_dir = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)

    manifest_paths = []
    asset_rows = []
    for index in range(2):
        asset_name = f"asset-{index}.jsonl.gz"
        asset_path = assets / asset_name
        asset_path.write_bytes(f"payload-{index}".encode())
        digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        dataset_id = f"dataset-{index}"
        manifest = {
            "dataset_id": dataset_id,
            "family": "l2Book",
            "venue": "bybit",
            "symbol": "BTCUSDT",
            "start_ts_ms": 1000 + index,
            "end_ts_ms": 1000 + index,
            "sha256": digest,
            "bytes": asset_path.stat().st_size,
            "event_count": 1,
            "collector_version": "a" * 40,
            "source": "bybit_public_ws",
            "quality_status": "PARTIAL",
            "release_asset": asset_name,
            "asset_verified": False,
            "provenance": {
                "public_data_only": True,
                "authenticated": False,
                "real_execution": False,
                "transports": ["websocket"],
            },
            "integrity": {
                "gap_count": 0,
                "duplicate_count": 0,
                "regression_count": 0,
                "missing_timestamp_count": 0,
                "missing_monotonic_count": 0,
                "desync_count": 0,
                "duplicates_deduped": True,
            },
            "synchronization": {"connection_count": 1},
            "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
            "required_channels": [],
            "observed_channels": ["l2Book"],
            "cost_model": {"applicable": False, "ready": False},
        }
        path = manifests_dir / f"{dataset_id}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_paths.append(f"manifests/{path.name}")
        asset_rows.append(
            {
                "id": 100 + index,
                "name": asset_name,
                "size": asset_path.stat().st_size,
                "digest": "sha256:" + digest,
            }
        )

    (bundle / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "collector_version": "a" * 40,
                "shard_count": 2,
                "manifests": manifest_paths,
                "assets": [f"assets/asset-{i}.jsonl.gz" for i in range(2)],
            }
        ),
        encoding="utf-8",
    )

    uploaded = []

    monkeypatch.setattr(
        module,
        "ensure_release",
        lambda **_kwargs: {"id": 77, "assets": []},
    )

    def fake_upload_file(*, repository, tag, path):
        uploaded.append(Path(path).name)

    monkeypatch.setattr(module, "upload_file", fake_upload_file)

    def fake_json(_args):
        rows = list(asset_rows)
        if "RUN_MANIFEST.json" in uploaded:
            rows.append(
                {
                    "id": 999,
                    "name": "RUN_MANIFEST.json",
                    "size": 1,
                    "digest": "sha256:" + "0" * 64,
                }
            )
        return {"id": 77, "assets": rows}

    monkeypatch.setattr(module, "_json", fake_json)

    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-run-test",
        target="main",
        title="test",
    )

    assert uploaded == ["asset-0.jsonl.gz", "asset-1.jsonl.gz", "RUN_MANIFEST.json"]
    assert not any(name.startswith("dataset-") and name.endswith(".json") for name in uploaded)
    assert result["shard_count"] == 2
    assert result["code_sha"] == "a" * 40
    assert result["event_count"] == 2
    assert result["gap_count"] == 0
    assert result["start_ts_ms"] == 1000
    assert result["end_ts_ms"] == 1001
    assert result["venues"] == ["bybit"]
    assert result["symbols"] == ["BTCUSDT"]
    assert result["asset_sha256s"] == [row["sha256"] for row in result["manifests"]]
    # PARTIAL fixtures must never be presented as SAFE replay coverage.
    assert result["safe_coverage_matrix"]["safe_partitions"] == 0
    assert result["safe_coverage_matrix"]["coins"] == []
    assert (bundle / "RUN_MANIFEST.json").is_file()



def test_upload_file_retries_transient_release_visibility_race(tmp_path, monkeypatch) -> None:
    module = _module()
    asset = tmp_path / "asset.jsonl.gz"
    asset.write_bytes(b"payload")

    calls = []

    class Result:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stderr = stderr
            self.stdout = ""

    def fake_run(args, *, check=True):
        calls.append((list(args), check))
        if len(calls) == 1:
            return Result(1, "release not found")
        return Result(0)

    sleeps = []
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    module.upload_file(
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="copy-vault-v2-test-s1",
        path=asset,
    )

    assert len(calls) == 2
    assert all(check is False for _args, check in calls)
    assert sleeps == [1.0]

def test_publish_skips_existing_compatible_assets(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests_dir = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)
    asset = assets / "already-there.jsonl.gz"
    asset.write_bytes(b"payload")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "dataset_id": "dataset-existing",
        "family": "l2Book",
        "venue": "okx",
        "symbol": "BTC-USDT-SWAP",
        "start_ts_ms": 1000,
        "end_ts_ms": 1000,
        "sha256": digest,
        "bytes": asset.stat().st_size,
        "event_count": 1,
        "collector_version": "a" * 40,
        "source": "okx_public_ws",
        "quality_status": "PARTIAL",
        "release_asset": asset.name,
        "asset_verified": False,
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["websocket"],
        },
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
            "duplicates_deduped": True,
        },
        "synchronization": {"connection_count": 1},
        "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
        "required_channels": [],
        "observed_channels": ["l2Book"],
        "cost_model": {"applicable": False, "ready": False},
    }
    manifest_path = manifests_dir / "dataset-existing.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "collector_version": "a" * 40,
                "collection_run_id": "run-existing",
                "shard_count": 1,
                "manifests": ["manifests/dataset-existing.json"],
                "assets": ["assets/already-there.jsonl.gz"],
            }
        ),
        encoding="utf-8",
    )
    remote_asset = {
        "id": 101,
        "name": asset.name,
        "size": asset.stat().st_size,
        "digest": "sha256:" + digest,
    }
    monkeypatch.setattr(
        module,
        "ensure_release",
        lambda **_kwargs: {"id": 77, "assets": [remote_asset]},
    )
    uploaded = []
    monkeypatch.setattr(
        module,
        "upload_file",
        lambda **kwargs: uploaded.append(Path(kwargs["path"]).name),
    )

    def fake_json(_args):
        rows = [remote_asset]
        if "RUN_MANIFEST.json" in uploaded:
            rows.append(
                {
                    "id": 999,
                    "name": "RUN_MANIFEST.json",
                    "size": 1,
                    "digest": "sha256:" + "0" * 64,
                }
            )
        return {"id": 77, "assets": rows}

    monkeypatch.setattr(module, "_json", fake_json)
    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-run-existing",
        target="main",
        title="test",
    )

    assert uploaded == ["RUN_MANIFEST.json"]
    assert result["shard_count"] == 1


def test_upload_file_retries_api_rate_limit(tmp_path, monkeypatch) -> None:
    module = _module()
    asset = tmp_path / "asset.jsonl.gz"
    asset.write_bytes(b"payload")
    calls = []

    class Result:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stderr = stderr
            self.stdout = ""

    def fake_run(args, *, check=True):
        calls.append((list(args), check))
        if len(calls) == 1:
            return Result(1, "HTTP 403: API rate limit exceeded for installation")
        return Result(0)

    sleeps = []
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    module.upload_file(
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-test",
        path=asset,
    )

    assert len(calls) == 2
    assert sleeps == [30.0]


def test_publish_moves_stale_incomplete_release_to_fresh_retry_tag(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests_dir = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)

    asset = assets / "current.jsonl.gz"
    asset.write_bytes(b"current-payload")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "dataset_id": "dataset-current",
        "family": "trades",
        "venue": "bitget",
        "symbol": "BTCUSDT",
        "start_ts_ms": 1000,
        "end_ts_ms": 1001,
        "sha256": digest,
        "bytes": asset.stat().st_size,
        "event_count": 1,
        "collector_version": "a" * 40,
        "source": "bitget_public_ws",
        "quality_status": "PARTIAL",
        "release_asset": asset.name,
        "asset_verified": False,
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["websocket"],
        },
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
            "duplicates_deduped": True,
        },
        "synchronization": {"connection_count": 1},
        "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
        "required_channels": [],
        "observed_channels": ["trades"],
        "cost_model": {"applicable": False, "ready": False},
    }
    manifest_path = manifests_dir / "dataset-current.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "collector_version": "a" * 40,
                "collection_run_id": "run-current",
                "shard_count": 1,
                "manifests": ["manifests/dataset-current.json"],
                "assets": ["assets/current.jsonl.gz"],
            }
        ),
        encoding="utf-8",
    )

    stale = {
        "id": 501,
        "name": "stale-from-old-attempt.jsonl.gz",
        "size": 123,
        "digest": "sha256:" + "1" * 64,
    }
    releases = [
        {"id": 77, "assets": [stale]},
        {"id": 78, "assets": []},
    ]

    def fake_ensure_release(**_kwargs):
        return releases.pop(0)

    deleted = []
    monkeypatch.setattr(module, "ensure_release", fake_ensure_release)

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(args, *, check=True):
        deleted.append(list(args))
        return Result()

    monkeypatch.setattr(module, "_run", fake_run)

    uploaded = []
    monkeypatch.setattr(
        module,
        "upload_file",
        lambda **kwargs: uploaded.append(Path(kwargs["path"]).name),
    )

    current_remote = {
        "id": 601,
        "name": asset.name,
        "size": asset.stat().st_size,
        "digest": "sha256:" + digest,
    }

    def fake_json(_args):
        rows = [current_remote]
        if "RUN_MANIFEST.json" in uploaded:
            run_path = bundle / "RUN_MANIFEST.json"
            rows.append(
                {
                    "id": 999,
                    "name": "RUN_MANIFEST.json",
                    "size": run_path.stat().st_size,
                    "digest": "sha256:" + hashlib.sha256(run_path.read_bytes()).hexdigest(),
                }
            )
        return {"id": 78, "assets": rows}

    monkeypatch.setattr(module, "_json", fake_json)

    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-retry-test",
        target="main",
        title="test",
    )

    assert not any(args[:2] == ["release", "delete"] for args in deleted)
    assert uploaded == ["current.jsonl.gz", "RUN_MANIFEST.json"]
    assert result["release_id"] == 78
    assert result["requested_release_tag"] == "data-v2-retry-test"
    assert result["release_tag"].startswith("data-v2-retry-test-retry-")


def test_publish_refuses_to_mutate_finalized_release_with_foreign_assets(
    tmp_path, monkeypatch
) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests_dir = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)

    asset = assets / "current.jsonl.gz"
    asset.write_bytes(b"payload")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    manifest = {
        "dataset_id": "dataset-current",
        "family": "trades",
        "venue": "okx",
        "symbol": "BTC-USDT-SWAP",
        "start_ts_ms": 1000,
        "end_ts_ms": 1000,
        "sha256": digest,
        "bytes": asset.stat().st_size,
        "event_count": 1,
        "collector_version": "a" * 40,
        "source": "okx_public_ws",
        "quality_status": "PARTIAL",
        "release_asset": asset.name,
        "asset_verified": False,
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["websocket"],
        },
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
            "duplicates_deduped": True,
        },
        "synchronization": {"connection_count": 1},
        "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
        "required_channels": [],
        "observed_channels": ["trades"],
        "cost_model": {"applicable": False, "ready": False},
    }
    path = manifests_dir / "dataset-current.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (bundle / "BUNDLE_INDEX.json").write_text(
        json.dumps(
            {
                "collector_version": "a" * 40,
                "collection_run_id": "run-current",
                "shard_count": 1,
                "manifests": ["manifests/dataset-current.json"],
                "assets": ["assets/current.jsonl.gz"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "ensure_release",
        lambda **_kwargs: {
            "id": 77,
            "assets": [
                {
                    "id": 1,
                    "name": "RUN_MANIFEST.json",
                    "size": 1,
                    "digest": "sha256:" + "0" * 64,
                },
                {
                    "id": 2,
                    "name": "foreign.jsonl.gz",
                    "size": 1,
                    "digest": "sha256:" + "0" * 64,
                },
            ],
        },
    )

    with pytest.raises(module.PublishError, match="refusing to mutate immutable evidence"):
        module.publish_bundle(
            bundle,
            repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
            tag="data-v2-finalized-test",
            target="main",
            title="test",
        )
