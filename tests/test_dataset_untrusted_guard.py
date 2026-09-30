from __future__ import annotations

import hashlib

import pytest

from hl_observer.datasets.dataset_untrusted_guard import (
    DatasetUntrustedError,
    assert_workspace_safe,
    validate_relative_member,
)
from hl_observer.datasets.github_release_bridge import DatasetBridgeError, _safe_destination


def test_dataset_paths_fail_closed_against_traversal_and_executables(tmp_path):
    assert validate_relative_member("runtime/data/book.jsonl") == "runtime/data/book.jsonl"
    for bad in ("../escape", "C:/evil", "/absolute", "runtime/data/payload.exe", "x.ps1", "x.py"):
        with pytest.raises(DatasetUntrustedError):
            validate_relative_member(bad)
    with pytest.raises(DatasetBridgeError):
        _safe_destination(tmp_path, "../zip-slip.txt")


def test_workspace_rejects_dataset_symlink_or_script(tmp_path):
    root = tmp_path / "ws"; (root / "runtime" / "data").mkdir(parents=True)
    (root / "runtime" / "data" / "ok.jsonl").write_text("{}\n", encoding="utf-8")
    assert assert_workspace_safe(root)["ok"] is True
    (root / "runtime" / "data" / "evil.ps1").write_text("Write-Host evil", encoding="utf-8")
    with pytest.raises(DatasetUntrustedError):
        assert_workspace_safe(root)


def test_only_hash_pinned_trusted_resume_tools_are_allowed(tmp_path):
    root = tmp_path / "ws"; (root / "runtime" / "data").mkdir(parents=True); (root / "tools").mkdir()
    tool = root / "tools" / "pipeline_copie_reel.py"; tool.write_text("print('trusted')\n", encoding="utf-8")
    digest = hashlib.sha256(tool.read_bytes()).hexdigest()
    result = assert_workspace_safe(root, trusted_file_sha256={"tools/pipeline_copie_reel.py": digest})
    assert result["trusted_files_verified"] == 1
    tool.write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(DatasetUntrustedError, match="hash mismatch"):
        assert_workspace_safe(root, trusted_file_sha256={"tools/pipeline_copie_reel.py": digest})
