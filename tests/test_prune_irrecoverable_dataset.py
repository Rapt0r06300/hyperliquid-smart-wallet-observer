from __future__ import annotations

import json

from tools import prune_irrecoverable_dataset as gc


def _row(dataset_id: str, status: str, asset: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "quality_status": status,
        "replay_compatible": False,
        "sha256": ("a" if dataset_id == "reject" else "b") * 64,
        "bytes": 10,
        "release_repository": gc.REPOSITORY,
        "release_tag": "data-test",
        "release_asset": asset,
        "release_remote_size": 10,
        "release_remote_digest": "sha256:" + (("a" if dataset_id == "reject" else "b") * 64),
        "manifest_path": f"datasets/rejected/{dataset_id}.manifest.json",
    }


def _result(row: dict) -> dict:
    return {
        "verified_from_release": True,
        "replay_compatible": False,
        "verifier_version": gc.VERIFIER_VERSION,
        "asset_sha256": row["sha256"],
        "asset_size": row["bytes"],
        "quality_status_after": row["quality_status"],
        "replay_reason": "INVALID_RECORD",
    }


def test_prepare_protects_safe_member_and_selects_terminal_standalone(monkeypatch, tmp_path):
    reject = _row("reject", "REJECT", "shared.zip")
    safe = _row("safe", "SAFE", "shared.zip")
    standalone = _row("terminal", "PARTIAL", "terminal.jsonl.gz")
    patch = tmp_path / "REPLAY_COMPAT_PATCH.json"
    plan = tmp_path / "DATA_DELETION_PLAN.json"
    patch.write_text(json.dumps({"results": {
        "reject": _result(reject), "terminal": _result(standalone),
    }}), encoding="utf-8")
    monkeypatch.setattr(gc, "PATCH", patch)
    monkeypatch.setattr(gc, "PLAN", plan)
    monkeypatch.setattr(gc, "_verified_snapshot", lambda: ({}, [reject, safe, standalone], "f" * 64))
    monkeypatch.setattr(gc, "release", lambda _tag: {})
    monkeypatch.setattr(gc, "assets", lambda _release: {
        "shared.zip": {"id": 1, "size": 10, "digest": reject["release_remote_digest"]},
        "terminal.jsonl.gz": {"id": 2, "size": 10, "digest": standalone["release_remote_digest"]},
    })

    result = gc.prepare(20)

    assert result["asset_count"] == 1
    assert result["dataset_count"] == 1
    assert result["assets"][0]["asset_name"] == "terminal.jsonl.gz"
    assert result["assets"][0]["datasets"][0]["dataset_id"] == "terminal"
    assert result["safe_assets_selected"] == 0


def test_terminal_requires_current_full_release_verification():
    row = _row("reject", "REJECT", "reject.jsonl.gz")
    stale = _result(row)
    stale["verifier_version"] = "old"
    retryable = _result(row)
    retryable["verified_from_release"] = False
    assert gc._terminal_rows([row], {"reject": stale}) == {}
    assert gc._terminal_rows([row], {"reject": retryable}) == {}
    assert set(gc._terminal_rows([row], {"reject": _result(row)})) == {"reject"}
