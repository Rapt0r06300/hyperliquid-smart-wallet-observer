from __future__ import annotations

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


def test_prepare_protects_safe_member_and_selects_terminal_standalone(monkeypatch, tmp_path):
    reject = _row("reject", "REJECT", "shared.zip")
    safe = _row("safe", "SAFE", "shared.zip")
    standalone = _row("terminal", "REJECT", "terminal.jsonl.gz")
    repairable = _row("repairable", "PARTIAL", "repairable.jsonl.gz")
    plan = tmp_path / "DATA_DELETION_PLAN.json"
    monkeypatch.setattr(gc, "PLAN", plan)
    monkeypatch.setattr(gc, "_verified_snapshot", lambda: ({}, [reject, safe, standalone, repairable], "f" * 64))
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


def test_terminal_requires_explicit_reject_with_complete_asset_identity():
    row = _row("reject", "REJECT", "reject.jsonl.gz")
    assert gc._terminal_rows([{**row, "quality_status": "PARTIAL"}]) == {}
    assert gc._terminal_rows([{**row, "replay_compatible": True}]) == {}
    assert gc._terminal_rows([{**row, "bytes": 0}]) == {}
    assert gc._terminal_rows([{**row, "sha256": "not-a-sha"}]) == {}
    assert gc._terminal_rows([{**row, "release_asset": ""}]) == {}
    assert set(gc._terminal_rows([row])) == {"reject"}


def test_terminal_receipt_keeps_legacy_oversized_flat_tree(monkeypatch, tmp_path):
    receipt = tmp_path / "datasets" / "rejected" / "terminal.manifest.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"quality_status":"REJECT"}', encoding="utf-8")
    monkeypatch.setattr(gc, "_oversized_legacy_stage", lambda root, stage: stage == "rejected")
    assert gc._remove_terminal_receipt(
        tmp_path, "datasets/rejected/terminal.manifest.json",
    ) is False
    assert receipt.is_file()


def test_terminal_receipt_removes_only_safe_bounded_paths(monkeypatch, tmp_path):
    flat = tmp_path / "datasets" / "rejected" / "terminal.manifest.json"
    sharded = tmp_path / "datasets" / "sharded" / "rejected" / "aa" / "bb" / "t.manifest.json"
    for path in (flat, sharded):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gc, "_oversized_legacy_stage", lambda root, stage: stage == "rejected")
    assert gc._remove_terminal_receipt(tmp_path, "datasets/sharded/rejected/aa/bb/t.manifest.json")
    assert not sharded.exists()
    assert not gc._remove_terminal_receipt(tmp_path, "datasets/rejected/terminal.manifest.json")
    assert flat.exists()
    monkeypatch.setattr(gc, "_oversized_legacy_stage", lambda root, stage: False)
    assert gc._remove_terminal_receipt(tmp_path, "datasets/rejected/terminal.manifest.json")
    assert not flat.exists()


def test_terminal_receipt_rejects_path_traversal_or_symlink(tmp_path):
    import pytest
    for path in ("../../outside", "catalog/DATA_INDEX.json", "datasets/rejected/../safe/x",
                 "/tmp/outside", "datasets/untrusted/file.manifest.json"):
        with pytest.raises(gc.Refuse):
            gc._remove_terminal_receipt(tmp_path, path)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "datasets" / "rejected" / "link.manifest.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    with pytest.raises(gc.Refuse):
        gc._remove_terminal_receipt(tmp_path, "datasets/rejected/link.manifest.json")
    assert outside.read_text(encoding="utf-8") == "secret"


def test_predelete_rechecks_every_current_member_of_physical_asset():
    import pytest
    reject = _row("reject", "REJECT", "mixed.zip")
    frozen = {"release_tag": "data-test", "asset_name": "mixed.zip", "datasets": [{
        "dataset_id": reject["dataset_id"], "sha256": reject["sha256"],
        "bytes": reject["bytes"], "quality_status": reject["quality_status"],
        "manifest_path": reject["manifest_path"],
    }]}
    gc._verify_target_membership([reject], [frozen])
    with pytest.raises(gc.Refuse, match="DELETION_PHYSICAL_MEMBERSHIP_CHANGED"):
        gc._verify_target_membership([reject, _row("new-safe", "SAFE", "mixed.zip")], [frozen])
    with pytest.raises(gc.Refuse, match="DELETION_PHYSICAL_MEMBER_CHANGED"):
        gc._verify_target_membership([{**reject, "bytes": 9}], [frozen])


def test_partial_never_terminal_even_after_replay_verification_failure():
    partial = _row("partial", "PARTIAL", "partial.jsonl.gz")
    assert gc._terminal_rows([partial]) == {}


def test_old_partial_deletion_plan_is_rejected():
    import pytest
    reject = _row("reject", "REJECT", "shared.zip")
    partial = _row("partial", "PARTIAL", "shared.zip")
    plan = {"assets": [{"release_tag": "data-test", "asset_name": "shared.zip",
                        "datasets": [{"dataset_id": "reject", "quality_status": "REJECT"},
                                     {"dataset_id": "partial", "quality_status": "PARTIAL"}]}]}
    assert gc._reject_only_plan(plan) is False
    with pytest.raises(gc.Refuse, match="DELETION_REJECT_ONLY"):
        gc._verify_target_membership([reject, partial], plan["assets"])


def test_only_reject_plan_and_current_membership_can_delete():
    reject = _row("reject", "REJECT", "reject.jsonl.gz")
    plan = {"assets": [{"release_tag": "data-test", "asset_name": "reject.jsonl.gz",
                        "datasets": [{"dataset_id": "reject", "quality_status": "REJECT",
                                      "sha256": reject["sha256"], "bytes": reject["bytes"],
                                      "manifest_path": reject["manifest_path"]}]}]}
    assert gc._reject_only_plan(plan) is True
    gc._verify_target_membership([reject], plan["assets"])
    assert gc._reject_only_plan({"assets": []}) is False
