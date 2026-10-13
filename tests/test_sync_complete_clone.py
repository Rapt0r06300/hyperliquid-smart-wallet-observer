"""Offline proof of canonical-main update + published-byte recovery entrypoints."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "alina_complete_sync_test", ROOT / "tools" / "sync_complete_clone.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stub_main(monkeypatch, module, root, *, dirty=False, origin=None):
    calls = []
    current_origin = origin or (
        "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer.git"
    )
    responses = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("symbolic-ref", "--quiet", "--short", "HEAD"): "main",
        ("remote", "get-url", "origin"): current_origin,
        ("status", "--porcelain", "--untracked-files=no"): " M README.md" if dirty else "",
        ("fetch", "--no-tags", "origin", "main"): "",
        ("rev-parse", "refs/remotes/origin/main"): "b" * 40,
        ("merge", "--ff-only", "refs/remotes/origin/main"): "",
        ("rev-parse", "HEAD"): "b" * 40,
    }

    def command(_root, *args):
        calls.append(args)
        if args not in responses:
            raise AssertionError(f"unexpected git command {args}")
        return responses[args]

    monkeypatch.setattr(module, "_git", command)
    return calls


def test_clean_local_main_fetches_then_fast_forwards_without_reset(monkeypatch, tmp_path):
    module = _module()
    root = tmp_path.resolve()
    calls = _stub_main(monkeypatch, module, root)
    assert module.synchronize_main(root) == "b" * 40
    assert calls.index(("fetch", "--no-tags", "origin", "main")) < calls.index(
        ("merge", "--ff-only", "refs/remotes/origin/main")
    )
    assert not any("reset" in args or "rebase" in args or "stash" in args for args in calls)


def test_dirty_tracked_files_abort_before_fetch(monkeypatch, tmp_path):
    module = _module()
    calls = _stub_main(monkeypatch, module, tmp_path.resolve(), dirty=True)
    with pytest.raises(module.SyncError, match="local tracked files"):
        module.synchronize_main(tmp_path)
    assert not any(command[0] == "fetch" for command in calls)


def test_foreign_origin_refused_even_when_branch_is_main(monkeypatch, tmp_path):
    module = _module()
    calls = _stub_main(
        monkeypatch, module, tmp_path.resolve(),
        origin="https://github.com/attacker/fork.git"
    )
    with pytest.raises(module.SyncError, match="origin"):
        module.synchronize_main(tmp_path)
    assert not any(command[0] == "fetch" for command in calls)


def test_skip_update_keeps_head_and_avoids_network(monkeypatch, tmp_path):
    module = _module()
    calls = _stub_main(monkeypatch, module, tmp_path.resolve(), dirty=True)
    assert module.synchronize_main(tmp_path, update=False) == "b" * 40
    assert not any(command[0] in {"fetch", "merge"} for command in calls)


def test_non_fast_forward_fails_without_altering_local_history(monkeypatch, tmp_path):
    module = _module()
    calls = _stub_main(monkeypatch, module, tmp_path.resolve())
    original_git = module._git

    def git(root, *args):
        if args[0] == "merge":
            raise module.SyncError("git merge failed (exit 1): not possible to fast-forward")
        return original_git(root, *args)

    monkeypatch.setattr(module, "_git", git)
    with pytest.raises(module.SyncError, match="fast-forward"):
        module.synchronize_main(tmp_path)
    assert not any("reset" in args or "rebase" in args for args in calls)


def test_restore_delegates_to_existing_engine_and_propagates_failure(monkeypatch, tmp_path):
    module = _module()
    calls = []
    monkeypatch.setenv("GH_TOKEN", "token-for-test")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.restore_published(tmp_path, snapshot=True) == 3
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "--replay-ready" in command
    assert "--everything" not in command
    assert "--clone-root" not in command  # Legacy LFS reuse is disabled.
    assert "--recover-verifiable" in command
    assert "--materialize-available-local-snapshot" not in command
    assert "--preflight-only" not in command
    assert kwargs["cwd"] == tmp_path.resolve()
    assert kwargs["env"]["GIT_LFS_SKIP_SMUDGE"] == "1"
    assert kwargs["env"]["GH_TOKEN"] == "token-for-test"


def test_preflight_never_downloads_and_avoids_snapshot_mutation(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setenv("GH_TOKEN", "token-for-test")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.restore_published(tmp_path, preflight=True) == 3
    assert len(commands) == 1
    assert "--preflight-only" in commands[0]
    assert "--materialize-available-local-snapshot" not in commands[0]


def test_root_entrypoints_are_reusable_in_existing_checkout():
    windows = (ROOT / "ALINA_SYNC_COMPLETE.cmd").read_text(encoding="utf-8")
    unix = (ROOT / "ALINA_SYNC_COMPLETE.sh").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in windows
    assert windows.count("tools\\sync_complete_clone.py %*") == 3
    assert windows.count("exit /b %ERRORLEVEL%") == 3
    assert "GIT_LFS_SKIP_SMUDGE=1" in windows
    assert 'exec python3 tools/sync_complete_clone.py "$@"' in unix
    assert "GIT_LFS_SKIP_SMUDGE=1" in unix


def test_successful_sync_writes_valid_sha_bound_checkpoint(monkeypatch, tmp_path):
    module = _module()
    mock_script = tmp_path / "tools" / "sync_complete_clone.py"
    monkeypatch.setattr(module, "__file__", str(mock_script))
    monkeypatch.setattr(module, "synchronize_main", lambda *_a, **_k: "a" * 40)
    report_dir = tmp_path / "runtime" / "recovery" / "full"
    report_dir.mkdir(parents=True)
    catalog = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"shards":[]}', encoding="utf-8")
    catalog_sha = hashlib.sha256(catalog.read_bytes()).hexdigest()
    (report_dir / "RESTORE_REPORT.json").write_text(json.dumps({
        "status": "REPLAY_READY_COMPLETE",
        "repository": module.REPOSITORY,
        "source_inventory_sha256": "c" * 64,
        "catalog_verification": {"source_index_sha256": catalog_sha},
    }), encoding="utf-8")
    monkeypatch.setattr(module, "restore_published", lambda *_a, **_k: 0)
    assert module.main([]) == 0
    path = tmp_path / "runtime" / "recovery" / "full" / "SYNC_REPORT.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["git_head"] == "a" * 40
    assert result["status"] == "REPLAY_READY_COMPLETE"
    assert result["restore_exit_code"] == 0
    assert result["restore_report"] == "RESTORE_REPORT.json"
    assert result["source_inventory_sha256"] == "c" * 64
    assert result["catalog_index_sha256"] == catalog_sha


def test_zero_restore_exit_without_complete_report_fails_closed(monkeypatch, tmp_path):
    module = _module()
    mock_script = tmp_path / "tools" / "sync_complete_clone.py"
    monkeypatch.setattr(module, "__file__", str(mock_script))
    monkeypatch.setattr(module, "synchronize_main", lambda *_a, **_k: "d" * 40)
    monkeypatch.setattr(module, "restore_published", lambda *_a, **_k: 0)
    catalog = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"shards":[]}', encoding="utf-8")

    assert module.main([]) == 2
    checkpoint = json.loads(
        (tmp_path / "runtime" / "recovery" / "full" / "SYNC_REPORT.json")
        .read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "RESTORE_INCOMPLETE"
    assert checkpoint["restore_exit_code"] == 0


def test_failed_restore_cannot_write_successful_sync_checkpoint(monkeypatch, tmp_path):
    module = _module()
    mock_script = tmp_path / "tools" / "sync_complete_clone.py"
    monkeypatch.setattr(module, "__file__", str(mock_script))
    monkeypatch.setattr(module, "synchronize_main", lambda *_a, **_k: "b" * 40)
    monkeypatch.setattr(module, "restore_published", lambda *_a, **_k: 3)
    catalog = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"shards":[]}', encoding="utf-8")
    assert module.main(["--preflight-only"]) == 3
    path = tmp_path / "runtime" / "recovery" / "full" / "SYNC_REPORT.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["git_head"] == "b" * 40
    assert result["status"] == "RESTORE_INCOMPLETE"
    assert result["restore_exit_code"] == 3
    assert result["restore_report"] == "RESTORE_PREFLIGHT.json"


def test_lfs_filters_disabled_in_attributes():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert not any(
        "filter=lfs" in line and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )
