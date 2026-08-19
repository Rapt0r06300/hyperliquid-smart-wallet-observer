from __future__ import annotations

import hashlib

import pytest

import hl_observer.ops.portable_clone_inventory as inv
from hl_observer.ops.portable_clone_inventory import PortableCloneError


def test_classification_and_secret_scan_policy() -> None:
    assert inv._classification("runtime/data/state.sqlite") == ("sqlite", None)
    assert inv._classification("runtime/data/state.sqlite-wal")[0] == "exclude"
    assert inv._classification("runtime/cache/x.txt")[0] == "file"
    assert inv._classification(".pytest_cache/x")[0] == "exclude"
    assert inv._classification("runtime/a.lock")[0] == "exclude"
    assert inv._classification(".env")[0] == "secret"
    assert inv._classification("config.env.example")[0] == "file"
    assert inv._classification("wallet.key")[0] == "secret"
    assert inv._classification(inv.MANIFEST_NAME)[0] == "exclude"
    assert inv._should_scan_private_key_content("config.txt", 100) is True
    assert inv._should_scan_private_key_content("tools/python/a.txt", 100) is False
    assert inv._should_scan_private_key_content("x.bin", 100) is False
    assert inv._should_scan_private_key_content("config.txt", inv.MAX_SECRET_SCAN_SIZE + 1) is False


def test_durable_summary_and_machine_fingerprint(monkeypatch) -> None:
    files = {
        "runtime/data/ledger.sqlite": {"sha256": "a", "size": 1},
        "runtime/data/sessions/s1/DATA_CATALOG.json": {"sha256": "b", "size": 2},
        "runtime/reports/r.json": {"sha256": "c", "size": 3},
        "data/history.json": {"sha256": "d", "size": 4},
    }
    summary = inv._durable_artifact_summary(files)
    assert summary["ledgers"]["count"] == 1
    assert summary["sessions"]["count"] == 1
    assert summary["reports"]["count"] == 1
    assert summary["histories"]["count"] >= 2
    assert all(len(row["sha256"]) == 64 for row in summary.values())

    monkeypatch.setattr(inv.platform, "node", lambda: "node-a")
    monkeypatch.setattr(inv.uuid, "getnode", lambda: 123)
    monkeypatch.delenv("COMPUTERNAME", raising=False)
    one = inv.machine_fingerprint()
    two = inv.machine_fingerprint()
    assert one == two == hashlib.sha256("node-a|123".encode()).hexdigest()


def test_path_helpers_and_reparse_guard(tmp_path) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    assert inv._resolved(root) == root.resolve()
    assert inv._is_within(child, root) is True
    assert inv._is_within(root, child) is False
    assert inv._is_public_template(".env.example") is True
    assert inv._is_public_template("x.sample") is True
    assert inv._is_public_template(".env") is False
    with pytest.raises(PortableCloneError, match="reparse point refused"):
        inv._assert_reparse_allowed("link")


def test_inventory_classifies_durable_files_and_exclusions(tmp_path, monkeypatch) -> None:
    root = tmp_path / "project"
    (root / "runtime" / "data").mkdir(parents=True)
    (root / ".pytest_cache").mkdir()
    (root / "src").mkdir()
    (root / "runtime" / "data" / "state.sqlite").write_bytes(b"db")
    (root / "runtime" / "data" / "state.sqlite-wal").write_bytes(b"wal")
    module_text = "print('x')"
    (root / "src" / "module.py").write_text(module_text, encoding="utf-8")
    (root / ".pytest_cache" / "cache").write_text("x", encoding="utf-8")
    monkeypatch.setattr(inv.AP, "contient_cle_privee", lambda path: False)
    result = inv.inventory(root)
    paths = {row.relative_path: row for row in result.files}
    assert set(paths) == {"runtime/data/state.sqlite", "src/module.py"}
    assert paths["runtime/data/state.sqlite"].kind == "sqlite"
    assert result.sqlite_count == 1
    assert result.total_bytes == 2 + len(module_text.encode("utf-8"))
    excluded = {row["path"]: row["reason"] for row in result.excluded}
    assert ".pytest_cache/" in excluded
    assert excluded["runtime/data/state.sqlite-wal"] == "sqlite_sidecar_replaced_by_backup"


def test_inventory_fail_closed_for_missing_root_and_secrets(tmp_path, monkeypatch) -> None:
    with pytest.raises(PortableCloneError, match="source root does not exist"):
        inv.inventory(tmp_path / "missing")

    root = tmp_path / "secret"
    root.mkdir()
    (root / ".env").write_text("TOKEN=x", encoding="utf-8")
    with pytest.raises(PortableCloneError, match="secret/private-key material"):
        inv.inventory(root, scan_private_key_content=False)

    root2 = tmp_path / "content-secret"
    root2.mkdir()
    key = root2 / "config.txt"
    key.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(inv.AP, "contient_cle_privee", lambda path: path.name == "config.txt")
    with pytest.raises(PortableCloneError, match="secret/private-key material"):
        inv.inventory(root2)


def test_available_drive_roots_on_current_non_windows_platform() -> None:
    if inv.os.name == "nt":
        pytest.skip("non-Windows branch only")
    roots = list(inv._available_drive_roots())
    assert len(roots) == 1
    assert roots[0].is_absolute()
