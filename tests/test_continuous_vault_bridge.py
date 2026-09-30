from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from hl_observer.datasets.github_release_bridge import DatasetBridgeError
from hl_observer.datasets import continuous_vault_bridge


def _contents_payload(payload: dict[str, object]) -> dict[str, object]:
    raw = json.dumps(payload).encode("utf-8")
    return {
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }


def test_load_continuous_pointer_decodes_private_contents(monkeypatch) -> None:
    pointer = {
        "schema": continuous_vault_bridge.POINTER_SCHEMA,
        "repository": continuous_vault_bridge.DEFAULT_REPOSITORY,
        "latest_snapshot_id": "snap-1",
        "latest_release_id": 123,
        "latest_release_tag": "alina-vault-snap-1",
        "index_asset": {
            "name": "VAULT_FILE_INDEX.json.gz",
            "asset_id": 456,
            "size": 100,
            "sha256": "a" * 64,
        },
    }

    monkeypatch.setattr(
        continuous_vault_bridge,
        "get_json",
        lambda path: _contents_payload(pointer),
    )
    result = continuous_vault_bridge.load_continuous_pointer()

    assert result["latest_snapshot_id"] == "snap-1"
    assert result["latest_release_id"] == 123
    assert result["index_asset"]["asset_id"] == 456


def test_load_continuous_pointer_rejects_wrong_repository(monkeypatch) -> None:
    pointer = {
        "schema": continuous_vault_bridge.POINTER_SCHEMA,
        "repository": "someone/else",
        "index_asset": {
            "asset_id": 456,
            "size": 100,
            "sha256": "a" * 64,
        },
    }
    monkeypatch.setattr(
        continuous_vault_bridge,
        "get_json",
        lambda path: _contents_payload(pointer),
    )

    with pytest.raises(DatasetBridgeError):
        continuous_vault_bridge.load_continuous_pointer()


def test_iter_continuous_records_excludes_archived_and_stale_by_default() -> None:
    payload = {
        "schema": continuous_vault_bridge.INDEX_SCHEMA,
        "files": {
            "runtime/data/current.jsonl": {
                "present_local": True,
                "release_tag": "tag-current",
                "storage": "zip_entry",
                "asset": "current.zip",
                "size": 10,
                "sha256": "1" * 64,
            },
            "runtime/data/deleted.jsonl": {
                "present_local": False,
                "deleted_at_snapshot": "snap-2",
                "release_tag": "tag-old",
                "storage": "raw_chunks",
                "chunks": [{"asset": "old.bin", "part": 1}],
                "size": 20,
                "sha256": "2" * 64,
            },
            "runtime/data/stale.jsonl": {
                "present_local": True,
                "backup_stale": True,
                "release_tag": "tag-stale",
                "storage": "zip_entry",
                "asset": "stale.zip",
                "size": 30,
                "sha256": "3" * 64,
            },
        },
    }

    current_rows = list(
        continuous_vault_bridge.iter_continuous_records(payload)
    )
    historical_rows = list(
        continuous_vault_bridge.iter_continuous_records(
            payload,
            include_archived_deleted=True,
        )
    )
    all_rows = list(
        continuous_vault_bridge.iter_continuous_records(
            payload,
            include_archived_deleted=True,
            include_stale_prior=True,
        )
    )

    assert [row.relative_path for row in current_rows] == [
        "runtime/data/current.jsonl"
    ]
    assert {row.relative_path for row in historical_rows} == {
        "runtime/data/current.jsonl",
        "runtime/data/deleted.jsonl",
    }
    assert {row.relative_path for row in all_rows} == {
        "runtime/data/current.jsonl",
        "runtime/data/deleted.jsonl",
        "runtime/data/stale.jsonl",
    }
    assert {row.release_tag for row in all_rows} == {
        "tag-current",
        "tag-old",
        "tag-stale",
    }


def test_continuous_workspace_pointer_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALINA_DATASET_HOME", str(tmp_path / "datasets"))
    root = tmp_path / "project"
    root.mkdir()
    workspace = continuous_vault_bridge.continuous_workspace_for_digest(
        root,
        "economic-core",
        "a" * 64,
    )
    workspace.mkdir(parents=True)

    pointer = continuous_vault_bridge.write_continuous_workspace_pointer(
        root,
        "economic-core",
        digest="a" * 64,
        workspace=workspace,
        vault_snapshot_id="snap-3",
        vault_release_id=789,
    )

    assert pointer.is_file()
    assert (
        continuous_vault_bridge.resolve_continuous_workspace(root, "economic-core")
        == workspace.resolve()
    )


def test_continuous_workspace_rejects_escape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALINA_DATASET_HOME", str(tmp_path / "datasets"))
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(DatasetBridgeError):
        continuous_vault_bridge.write_continuous_workspace_pointer(
            root,
            "economic-core",
            digest="b" * 64,
            workspace=outside,
            vault_snapshot_id="snap-4",
            vault_release_id=999,
        )
