from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hl_observer.backtesting.copy_vault_evidence_inventory import (
    INVENTORIED_NOT_PROOF,
    build_inventory,
    inventory_path,
)


def test_inventory_hashes_regular_file_but_never_allows_closure(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    payload = b"real local receipt\n"
    path.write_bytes(payload)

    report = build_inventory(tmp_path, ["receipt.json"])

    assert report["proof_status"] == INVENTORIED_NOT_PROOF
    assert report["closure_allowed"] is False
    entry = report["entries"][0]
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
    assert entry["size_bytes"] == len(payload)


def test_inventory_is_explicit_for_missing_paths(tmp_path: Path) -> None:
    entry = inventory_path(tmp_path, "missing.json")
    assert entry.exists is False
    assert entry.error == "MISSING"
    assert entry.sha256 is None


def test_inventory_rejects_paths_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        inventory_path(tmp_path, "../outside.json")


def test_inventory_refuses_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this runner")

    entry = inventory_path(tmp_path, "link.json")
    assert entry.symlink is True
    assert entry.error == "SYMLINK_REFUSED"
    assert entry.sha256 is None
