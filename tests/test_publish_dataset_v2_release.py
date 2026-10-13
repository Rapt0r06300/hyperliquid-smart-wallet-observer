from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import zipfile
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


def _locally_valid_manifest(dataset_id: str, **overrides):
    row = {
        "dataset_id": dataset_id,
        "family": "l2Book",
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 1000,
        "end_ts_ms": 1001,
        "sha256": "a" * 64,
        "bytes": 10,
        "event_count": 1,
        "collector_version": "b" * 40,
        "source": "bybit_public_ws",
        "quality_status": "PARTIAL",
        "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
        "asset_verified": False,
        "replay_compatible": True,
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
    row.update(overrides)
    return row


def test_release_capacity_reserves_run_manifest_slot() -> None:
    module = _module()
    module.validate_release_capacity(999)
    with pytest.raises(module.PublishError):
        module.validate_release_capacity(1000)


def test_partition_publishable_manifests_requires_explicit_safe_replayable() -> None:
    module = _module()
    rows = [
        _locally_valid_manifest("eligible", quality_status="SAFE"),
        _locally_valid_manifest("safe-unproven", quality_status="SAFE", replay_compatible=False),
        _locally_valid_manifest("partial", quality_reasons=["COST_MODEL_NOT_READY"]),
        _locally_valid_manifest("reject", quality_status="REJECT", replay_compatible=False),
        _locally_valid_manifest("unknown", quality_status="MYSTERY"),
    ]

    eligible, diagnostic = module.partition_publishable_manifests(rows)

    assert [row["dataset_id"] for row in eligible] == ["eligible"]
    assert [row["dataset_id"] for row in diagnostic] == [
        "partial", "reject", "safe-unproven", "unknown",
    ]
    assert all(row["validation_allowed"] is False for row in diagnostic)
    assert all(row["replay_compatible"] is False for row in diagnostic)


def test_partition_allows_only_remote_verification_pending_candidate() -> None:
    module = _module()
    rows = [
        _locally_valid_manifest("remote-pending"),
        _locally_valid_manifest(
            "has-gap-too",
            quality_reasons=["REMOTE_ASSET_NOT_VERIFIED", "SEQUENCE_OR_QUEUE_GAP"],
            integrity={"gap_count": 1},
        ),
    ]

    eligible, diagnostic = module.partition_publishable_manifests(rows)

    assert [row["dataset_id"] for row in eligible] == ["remote-pending"]
    assert [row["dataset_id"] for row in diagnostic] == ["has-gap-too"]


def test_partition_preserves_manifest_path_binding_for_duplicate_identity(tmp_path) -> None:
    module = _module()
    safe_path = tmp_path / "safe.json"
    rejected_path = tmp_path / "rejected.json"
    shared = {
        "release_asset": "duplicate.jsonl.gz",
        "sha256": "a" * 64,
    }
    rows = [
        _locally_valid_manifest("duplicate", **shared),
        _locally_valid_manifest(
            "duplicate",
            **shared,
            quality_reasons=["REMOTE_ASSET_NOT_VERIFIED", "SEQUENCE_OR_QUEUE_GAP"],
            replay_compatible=False,
        ),
    ]

    eligible, diagnostic = module.partition_manifest_entries(
        [safe_path, rejected_path], rows
    )

    assert eligible == [(safe_path, rows[0])]
    assert diagnostic[0][0] == rejected_path
    assert diagnostic[0][1]["validation_allowed"] is False


def test_final_publication_inventory_must_be_safe_and_replayable() -> None:
    module = _module()
    module.assert_safe_final_manifests([
        {"dataset_id": "safe", "quality_status": "SAFE", "replay_compatible": True}
    ])

    with pytest.raises(module.PublishError, match="final manifest is not SAFE"):
        module.assert_safe_final_manifests([
            {
                "dataset_id": "partial",
                "quality_status": "PARTIAL",
                "replay_compatible": False,
            }
        ])


def test_quality_register_is_deterministic_metadata_without_payload(tmp_path) -> None:
    module = _module()
    rejected = [{
        "dataset_id": "bad-window",
        "family": "trades",
        "venue": "gate",
        "symbol": "BTC_USDT",
        "quality_status": "PARTIAL",
        "quality_reasons": ["GAP"],
        "release_asset": "bad.jsonl.gz",
        "bytes": 123,
        "sha256": "a" * 64,
        "event_count": 7,
        "trade_count": 6,
        "collector_version": "b" * 40,
        "provenance": {"source": "public_ws"},
        "local_source_path": "/runner/private/raw.jsonl",
        "local_asset_path": str(tmp_path / "payload"),
        "payload": "market bytes must never be copied",
        "validation_allowed": True,
        "replay_compatible": True,
    }]

    first = module.write_quality_register(tmp_path, rejected)
    assert first is not None
    first_bytes = first.read_bytes()
    second = module.write_quality_register(tmp_path, list(reversed(rejected)))

    assert second == first
    assert second.read_bytes() == first_bytes
    register = json.loads(gzip.decompress(first_bytes))
    assert register["schema"] == "alina.dataset_quality_rejections.v1"
    assert register["row_count"] == 1
    [row] = register["rows"]
    assert row["dataset_id"] == "bad-window"
    assert row["bytes"] == 123
    assert row["sha256"] == "a" * 64
    assert row["validation_allowed"] is False
    assert row["replay_compatible"] is False
    assert "local_source_path" not in row
    assert "local_asset_path" not in row
    assert "payload" not in row


def test_quality_register_is_absent_without_rejections(tmp_path) -> None:
    module = _module()

    assert module.write_quality_register(tmp_path, []) is None
    assert not (tmp_path / "QUALITY_REJECTIONS.json.gz").exists()


def _write_safe_only_test_bundle(tmp_path, rows):
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests.mkdir(parents=True)
    manifest_names = []
    for row in rows:
        payload = str(row["dataset_id"]).encode("utf-8")
        asset_name = f"{row['dataset_id']}.jsonl.gz"
        (assets / asset_name).write_bytes(payload)
        manifest = {
            **_locally_valid_manifest(str(row["dataset_id"])),
            "release_asset": asset_name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "event_count": 1,
            "collector_version": "a" * 40,
            **row,
        }
        path = manifests / f"{row['dataset_id']}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_names.append(f"manifests/{path.name}")
    (bundle / "BUNDLE_INDEX.json").write_text(json.dumps({
        "collector_version": "a" * 40,
        "collection_run_id": "safe-only-test",
        "manifests": manifest_names,
    }), encoding="utf-8")
    return bundle


def _mock_release_io(module, monkeypatch, uploaded):
    monkeypatch.setattr(module, "ensure_release", lambda **_kw: {"id": 77, "assets": []})
    monkeypatch.setattr(
        module, "upload_file",
        lambda **kwargs: uploaded.append(Path(kwargs["path"])),
    )

    def fake_json(_args):
        return {"id": 77, "assets": [{
            "id": index,
            "name": path.name,
            "size": path.stat().st_size,
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        } for index, path in enumerate(uploaded, 1)]}

    monkeypatch.setattr(module, "_json", fake_json)


def test_publish_zero_safe_uploads_only_diagnostics_and_manifest(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = _write_safe_only_test_bundle(tmp_path, [{
        "dataset_id": "rejected",
        "quality_status": "REJECT",
        "quality_reasons": ["SEQUENCE_OR_QUEUE_GAP"],
        "replay_compatible": False,
    }])
    uploaded = []
    _mock_release_io(module, monkeypatch, uploaded)

    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-zero-safe",
        target="main",
        title="zero safe",
    )

    assert uploaded == []
    assert result["status"] == "NO_REPLAY_ADMISSIBLE_SHARDS"
    assert result["excluded_payload_count"] == 1
    assert result["real_execution"] is False


def test_publish_mixed_bundle_filters_payload_and_capsule_inputs(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = _write_safe_only_test_bundle(tmp_path, [
        {
            "dataset_id": "safe-candidate",
            "quality_status": "PARTIAL",
            "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
            "replay_compatible": True,
        },
        {
            "dataset_id": "partial-gap",
            "quality_status": "PARTIAL",
            "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED", "SEQUENCE_OR_QUEUE_GAP"],
            "replay_compatible": False,
        },
    ])
    capsule_inputs = []
    monkeypatch.setattr(
        module,
        "publish_recovery_capsule",
        lambda _root, **kwargs: capsule_inputs.extend(kwargs["manifests"]),
    )
    uploaded = []
    _mock_release_io(module, monkeypatch, uploaded)

    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-mixed-safe",
        target="main",
        title="mixed safe",
    )

    assert [row["dataset_id"] for row in capsule_inputs] == ["safe-candidate"]
    assert [path.name for path in uploaded] == [
        "safe-candidate.jsonl.gz", "QUALITY_REJECTIONS.json.gz", "RUN_MANIFEST.json",
    ]
    assert result["shard_count"] == 1
    assert result["quality_register"]["row_count"] == 1


def test_compaction_packs_many_shards_deterministically(tmp_path) -> None:
    module = _module()
    root = tmp_path / "bundle"
    assets = root / "assets"
    assets.mkdir(parents=True)
    manifests = []
    for index in range(5):
        name = f"shard-{index}.jsonl.gz"
        payload = f"payload-{index}".encode()
        (assets / name).write_bytes(payload)
        manifests.append({
            "dataset_id": f"dataset-{index}",
            "release_asset": name,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    first = module.build_compacted_assets(root, manifests, members_per_asset=2)
    first_digests = [row["sha256"] for row in first]
    second = module.build_compacted_assets(root, manifests, members_per_asset=2)

    assert len(first) == 3
    assert [row["sha256"] for row in second] == first_digests
    assert [len(row["manifests"]) for row in first] == [2, 2, 1]
    with zipfile.ZipFile(first[0]["path"]) as archive:
        assert archive.namelist() == ["shard-0.jsonl.gz", "shard-1.jsonl.gz"]
        assert archive.read("shard-0.jsonl.gz") == b"payload-0"


def test_compaction_splits_before_github_file_size_limit(tmp_path) -> None:
    module = _module()
    root = tmp_path / "bundle"
    assets = root / "assets"
    assets.mkdir(parents=True)
    manifests = []
    for index in range(3):
        payload = b"1234567890"
        name = f"shard-{index}.jsonl.gz"
        (assets / name).write_bytes(payload)
        manifests.append({"dataset_id": str(index), "release_asset": name,
                          "bytes": len(payload),
                          "sha256": hashlib.sha256(payload).hexdigest()})

    compacted = module.build_compacted_assets(
        root, manifests, members_per_asset=100, max_payload_bytes=20,
    )

    assert [len(row["manifests"]) for row in compacted] == [2, 1]


def test_publish_compacts_large_bundle_into_two_github_writes(tmp_path, monkeypatch) -> None:
    module = _module()
    bundle = tmp_path / "bundle"
    assets = bundle / "assets"
    manifests_dir = bundle / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)
    manifest_paths = []
    for index in range(module.COMPACTION_MIN_SHARDS):
        name = f"asset-{index:03d}.jsonl.gz"
        payload = f"payload-{index}".encode()
        (assets / name).write_bytes(payload)
        manifest = {
            "dataset_id": f"dataset-{index}", "family": "trades",
            "venue": "gate", "symbol": "BTC_USDT",
            "start_ts_ms": 1000 + index, "end_ts_ms": 1000 + index,
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
            "event_count": 1, "collector_version": "a" * 40,
            "source": "gate_public_ws", "quality_status": "PARTIAL",
            "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
            "release_asset": name, "asset_verified": False,
            "replay_compatible": True,
            "provenance": {"public_data_only": True, "authenticated": False,
                           "real_execution": False, "transports": ["websocket"]},
            "integrity": {"gap_count": 0, "duplicate_count": 0,
                          "regression_count": 0, "missing_timestamp_count": 0,
                          "missing_monotonic_count": 0, "desync_count": 0,
                          "duplicates_deduped": True},
            "synchronization": {"connection_count": 1},
            "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
            "required_channels": [], "observed_channels": ["trades"],
            "cost_model": {"applicable": False, "ready": False},
        }
        path = manifests_dir / f"dataset-{index}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_paths.append(f"manifests/{path.name}")
    (bundle / "BUNDLE_INDEX.json").write_text(json.dumps({
        "collector_version": "a" * 40,
        "collection_run_id": "run-1",
        "manifests": manifest_paths,
    }), encoding="utf-8")

    uploaded = []
    monkeypatch.setattr(module, "ensure_release", lambda **_kwargs: {"id": 77, "assets": []})

    def fake_upload_file(*, repository, tag, path):
        uploaded.append(Path(path))

    monkeypatch.setattr(module, "upload_file", fake_upload_file)

    def fake_json(_args):
        rows = []
        for index, path in enumerate(uploaded, 1):
            rows.append({"id": index, "name": path.name, "size": path.stat().st_size,
                         "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"id": 77, "assets": rows}

    monkeypatch.setattr(module, "_json", fake_json)
    result = module.publish_bundle(
        bundle,
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        tag="data-v2-run-compacted",
        target="main",
        title="compacted",
    )

    assert [path.name for path in uploaded] == ["packed-shards-0000.zip", "RUN_MANIFEST.json"]
    assert result["shard_count"] == module.COMPACTION_MIN_SHARDS
    assert result["release_parts"][0]["asset_count"] == 1
    assert all(row["release"]["storage"] == "zip_entry" for row in result["manifests"])


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
            "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
            "release_asset": asset_name,
            "asset_verified": False,
            "replay_compatible": True,
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
    # Locally valid candidates become SAFE only after exact remote verification.
    assert result["safe_coverage_matrix"]["safe_partitions"] == 1
    assert result["safe_coverage_matrix"]["coins"] == ["BTC"]
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
        "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
        "release_asset": asset.name,
        "asset_verified": False,
        "replay_compatible": True,
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
        "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
        "release_asset": asset.name,
        "asset_verified": False,
        "replay_compatible": True,
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
        "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"],
        "release_asset": asset.name,
        "asset_verified": False,
        "replay_compatible": True,
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


def test_recovery_capsule_persists_exact_bundle_before_canonical_upload(tmp_path, monkeypatch) -> None:
    module = _module()
    root = tmp_path / "bundle"
    assets = root / "assets"
    manifests_dir = root / "manifests"
    assets.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)
    payload = b"immutable-trades"
    asset = assets / "trades.jsonl.gz"
    asset.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "dataset_id": "dataset-recovery",
        "release_asset": asset.name,
        "sha256": digest,
        "bytes": len(payload),
    }
    manifest_path = manifests_dir / "dataset-recovery.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bundle_index = {
        "collector_version": "a" * 40,
        "collection_run_id": "run-recovery",
        "manifests": ["manifests/dataset-recovery.json"],
        "assets": ["assets/trades.jsonl.gz"],
    }
    (root / "BUNDLE_INDEX.json").write_text(
        json.dumps(bundle_index), encoding="utf-8"
    )

    monkeypatch.setenv("ALINA_RECOVERY_CAPSULE", "1")
    uploaded = []
    monkeypatch.setattr(
        module,
        "ensure_release",
        lambda **_kwargs: {"id": 55, "assets": []},
    )
    monkeypatch.setattr(
        module,
        "upload_file",
        lambda **kwargs: uploaded.append(Path(kwargs["path"])),
    )

    def fake_json(_args):
        rows = []
        for path in uploaded:
            rows.append(
                {
                    "id": len(rows) + 1,
                    "name": path.name,
                    "size": path.stat().st_size,
                    "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        return {"id": 55, "assets": rows}

    monkeypatch.setattr(module, "_json", fake_json)

    result = module.publish_recovery_capsule(
        root,
        index=bundle_index,
        manifest_paths=[manifest_path],
        manifests=[manifest],
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
        requested_release_tag="data-v2-run-recovery",
        target="main",
        title="test",
    )

    assert result is not None
    assert result["part_count"] == 1
    assert [path.name for path in uploaded] == [
        "ALINA_RECOVERY_INDEX.json",
        "ALINA_RECOVERY_BUNDLE.part000.tar",
    ]

    import tarfile

    with tarfile.open(uploaded[1], "r") as archive:
        names = set(archive.getnames())
    assert "BUNDLE_INDEX.json" in names
    assert "manifests/dataset-recovery.json" in names
    assert "assets/trades.jsonl.gz" in names
