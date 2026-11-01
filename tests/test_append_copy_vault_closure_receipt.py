"""Tests for append-only exact-HEAD Copy-Vault closure wrappers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.append_copy_vault_closure_receipt import append_receipts


HEAD = "a" * 40


def _receipt(name: str, head_sha: str = HEAD) -> dict[str, object]:
    return {
        "name": name,
        "head_sha": head_sha,
        "evidence_status": "UNMEASURABLE",
        "decision": "NO_GO",
    }


def test_appends_objects_and_is_idempotent(tmp_path: Path) -> None:
    wrapper = tmp_path / "H-T99.json"
    receipt = tmp_path / "receipt.json"
    wrapper.write_text(json.dumps([_receipt("old")]) + "\n", encoding="utf-8")
    receipt.write_text(json.dumps([_receipt("new")]) + "\n", encoding="utf-8")

    first = append_receipts(wrapper, receipt)
    second = append_receipts(wrapper, receipt)
    rows = json.loads(wrapper.read_text(encoding="utf-8"))

    assert first["added"] == 1
    assert second["added"] == 0
    assert [row["name"] for row in rows] == ["old", "new"]


def test_rejects_stale_or_unbound_receipt_without_modifying_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "H-T99.json"
    receipt = tmp_path / "receipt.json"
    original = [_receipt("old")]
    wrapper.write_text(json.dumps(original) + "\n", encoding="utf-8")
    receipt.write_text(json.dumps(_receipt("bad", "not-a-sha")) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="head_sha"):
        append_receipts(wrapper, receipt)

    assert json.loads(wrapper.read_text(encoding="utf-8")) == original
