"""Deterministic Git reconciliation tests on disposable local bare remotes.

No real GitHub network, credentials, users' PCs, or AlinaSync shards.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.alina_git_code_sync import Synchronizer


def git(root: Path, *args: str, allow_error: bool = False) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode and not allow_error:
        raise AssertionError(f"git {args!r}: {completed.stderr}")
    return completed.stdout.strip()


@pytest.fixture
def repos(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALINA_SYNC_TEST_REMOTE_ALLOWED", "1")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--initial-branch=main")
    git(seed, "config", "user.email", "test@example.com")
    git(seed, "config", "user.name", "tester")
    (seed / "src").mkdir()
    (seed / "src" / "base.py").write_text("base = 1\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "initial")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "--bare", str(seed), str(origin))
    local = tmp_path / "local"
    cloud = tmp_path / "cloud"
    git(tmp_path, "clone", str(origin), str(local))
    git(tmp_path, "clone", str(origin), str(cloud))
    for path in (local, cloud):
        git(path, "config", "user.email", "test@example.com")
        git(path, "config", "user.name", "tester")
    return local, cloud, origin


def cloud_commit(cloud: Path, path: str, data: str):
    dst = cloud / path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(data, encoding="utf-8")
    git(cloud, "add", ".")
    git(cloud, "commit", "-m", "cloud change")
    git(cloud, "push", "origin", "main")


def run_sync(local: Path, *, dry: bool = False, wip: bool = False):
    task = Synchronizer(local, dry_run=dry, allow_test_remote=True)
    rc = task.run(wip_only=wip)
    receipt = json.loads((
        local / "runtime/reports/git-sync/LAST_SYNC.json"
    ).read_text(encoding="utf-8"))
    assert receipt["shard_downloads"] is False
    assert receipt["force_push"] is False
    return rc, receipt


def test_converges_without_losing_either_author(repos):
    local, cloud, origin = repos
    cloud_commit(cloud, "docs/cloud.md", "cloud\n")
    (local / "tools").mkdir()
    (local / "tools/local.py").write_text("local = 1\n")
    rc, receipt = run_sync(local)
    assert rc == 0 and receipt["status"] == "SYNCHRONIZED"
    assert receipt["local_commit_created"] is True
    assert git(local, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")
    assert git(origin, "show", "main:docs/cloud.md") == "cloud"
    assert git(origin, "show", "main:tools/local.py") == "local = 1"
    assert (local / "docs/cloud.md").read_text() == "cloud\n"
    assert not git(local, "diff", "--name-only")


def test_clean_sync_never_commits_empty(repos):
    local, _, origin = repos
    before = git(origin, "rev-parse", "main")
    rc, receipt = run_sync(local)
    assert rc == 0
    assert receipt["local_commit_created"] is False
    assert receipt["push_attempts"] == 0
    assert git(local, "rev-parse", "HEAD") == before


def test_wip_can_be_saved_locally_without_upload(repos):
    local, _, origin = repos
    before = git(origin, "rev-parse", "main")
    (local / "src" / "unfinished.py").write_text("def broken(:\n")
    rc, receipt = run_sync(local, wip=True)
    assert rc == 0 and receipt["status"] == "LOCAL_CHECKPOINT_ONLY"
    assert git(origin, "rev-parse", "main") == before
    assert git(local, "show", "HEAD:src/unfinished.py") == "def broken(:"
    assert git(local, "rev-parse", "HEAD") != before


def test_default_fails_closed_on_incomplete_python_but_keeps_wip(repos):
    local, _, origin = repos
    before = git(origin, "rev-parse", "main")
    (local / "src" / "unfinished.py").write_text("def broken(:\n")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"
    assert receipt["local_commit_created"] is True
    assert receipt["local_syntax_check"] == "FAILED_WIP_CHECKPOINT_PRESERVED"
    assert git(origin, "rev-parse", "main") == before


def test_locally_downloaded_shards_and_env_remain_untouched(repos):
    local, _, origin = repos
    shard = local / "runtime/recovery/full/usable/unpacked/shard.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b"local SAFE payload\n")
    (local / ".env").write_text("DONT_UPLOAD=secret\n")
    (local / "src" / "new.py").write_text("code = True\n")
    rc, _ = run_sync(local)
    assert rc == 0
    assert shard.read_bytes() == b"local SAFE payload\n"
    assert (local / ".env").read_text() == "DONT_UPLOAD=secret\n"
    tree = git(origin, "ls-tree", "-r", "--name-only", "main")
    assert "src/new.py" in tree and ".env" not in tree
    assert "shard.jsonl" not in tree


def test_pre_staged_secret_blocks_without_unstaging(repos):
    local, _, origin = repos
    old = git(origin, "rev-parse", "main")
    (local / ".env").write_text("TOKEN=secret")
    git(local, "add", "-f", ".env")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"
    assert git(origin, "rev-parse", "main") == old
    assert ".env" in git(local, "diff", "--cached", "--name-only")


def test_conflicting_edits_abort_merge_and_keep_both_commits(repos):
    local, cloud, origin = repos
    cloud_commit(cloud, "src/base.py", "base = 200\n")
    (local / "src/base.py").write_text("base = 300\n")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["local_commit_created"] is True
    assert receipt["status"] == "NO_GO"
    assert git(local, "show", "HEAD:src/base.py") == "base = 300"
    assert git(origin, "show", "main:src/base.py") == "base = 200"
    assert git(local, "rev-parse", "-q", "--verify", "MERGE_HEAD",
               allow_error=True) == ""
    assert git(local, "rev-parse", "refs/alina-sync/last-local-checkpoint") == git(
        local, "rev-parse", "HEAD"
    )
    kit = local / receipt["conflict_kit"]
    assert kit.is_dir() and (kit / "RESOLUTION.md").is_file()
    manifest = json.loads((kit / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["includes_shards"] is False
    assert manifest["no_auto_choice"] is True
    assert manifest["local_head"] == git(local, "rev-parse", "HEAD")
    assert manifest["files"][0]["path"] == "src/base.py"
    assert (kit / "00-base.txt").read_text() == "base = 1\\n".replace("\\n", "\n")
    assert (kit / "00-local.txt").read_text() == "base = 300\\n".replace("\\n", "\n")
    assert (kit / "00-github.txt").read_text() == "base = 200\\n".replace("\\n", "\n")


def test_dry_run_does_not_mutate_git(repos):
    local, cloud, origin = repos
    cloud_commit(cloud, "docs/remote.md", "remote\n")
    (local / "src" / "local.py").write_text("local = 1\n")
    local_head = git(local, "rev-parse", "HEAD")
    remote_head = git(origin, "rev-parse", "main")
    rc, receipt = run_sync(local, dry=True)
    assert rc == 0 and receipt["status"] == "DRY_RUN_ONLY"
    assert git(local, "rev-parse", "HEAD") == local_head
    assert git(origin, "rev-parse", "main") == remote_head
    assert git(local, "diff", "--cached", "--name-only") == ""


def test_cloud_fast_forward_without_local_changes(repos):
    local, cloud, origin = repos
    cloud_commit(cloud, "docs/cloud.md", "cloud\n")
    rc, receipt = run_sync(local)
    assert rc == 0 and receipt["status"] == "SYNCHRONIZED"
    assert not receipt["local_commit_created"]
    assert receipt["merge_commits_created"] == 0
    assert git(local, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_ignored_data_collision_refused(repos):
    local, cloud, origin = repos
    dst = local / "runtime/session.json"
    dst.parent.mkdir()
    dst.write_text("local critical state\n")
    cloud_commit(cloud, "runtime/session.json", "remote state\n")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"
    assert dst.read_text() == "local critical state\n"
    assert git(origin, "show", "main:runtime/session.json") == "remote state"


def test_concurrent_cloud_push_retries_without_force(repos):
    local, cloud, origin = repos
    (local / "src" / "local.py").write_text("local = 1\n")

    class RacingSync(Synchronizer):
        raced = False

        def command(self, *args, **kwargs):
            if args and args[0] == "push" and not self.raced:
                self.raced = True
                cloud_commit(cloud, "docs/race.md", "race\n")
            return super().command(*args, **kwargs)

    task = RacingSync(local, allow_test_remote=True)
    assert task.run() == 0
    assert task.report["push_attempts"] == 2
    assert git(origin, "show", "main:docs/race.md") == "race"
    assert git(origin, "show", "main:src/local.py") == "local = 1"


def test_main_branch_is_mandatory(repos):
    local, _, _ = repos
    git(local, "checkout", "-b", "another-branch")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"


def test_tracked_modified_data_never_overwritten(repos):
    local, _, origin = repos
    data = local / "data/safe.jsonl"
    data.parent.mkdir()
    data.write_text("initial\n")
    git(local, "add", "-f", "data/safe.jsonl")
    git(local, "commit", "-m", "historical data")
    git(local, "push", "origin", "main")
    data.write_text("my latest local bytes\n")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"
    assert data.read_text() == "my latest local bytes\n"


def test_pem_private_key_prevented_before_staging(repos):
    local, _, origin = repos
    original = git(origin, "rev-parse", "main")
    local_key = local / "src" / "oops.txt"
    local_key.write_text(
        "-----BEGIN PRIVATE KEY-----\n"
        "not-a-real-key\n"
        "-----END PRIVATE KEY-----\n"
    )
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["status"] == "NO_GO"
    assert git(local, "diff", "--cached", "--name-only") == ""
    assert git(local, "rev-parse", "HEAD") == original
    assert git(origin, "rev-parse", "main") == original
    assert local_key.exists()


def test_nested_python_dataset_and_runtime_directories_are_source(repos):
    local, _, origin = repos
    paths = (
        "src/hl_observer/datasets/new_adapter.py",
        "src/hl_observer/runtime/new_worker.py",
    )
    for name in paths:
        dst = local / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("is_real_code = True\n", encoding="utf-8")
    rc, receipt = run_sync(local)
    assert rc == 0 and receipt["status"] == "SYNCHRONIZED"
    for name in paths:
        assert git(origin, "show", f"main:{name}") == "is_real_code = True"



def test_windows_launcher_bootstraps_git_without_legacy_cmd() -> None:
    """Double-click resolves missing local helpers without fetching shards."""
    launcher = Path(__file__).resolve().parents[1] / "POUSSER-GITHUB-FORCE.cmd"
    source = launcher.read_text(encoding="utf-8-sig")
    assert 'call "%~dp0PREPARER_GIT_PORTABLE.cmd"' not in source
    assert 'call :download_source "tools/install_portable_git.ps1"' in source
    assert 'call :download_source "tools/alina_git_code_sync.py"' in source
    assert "ALINA_BOOTSTRAP_REF=8d632ee8266d5854ce0d7a9791c9c71775e10f86" in source
    assert '-File "%ALINA_INSTALLER%"' in source
    assert 'if exist "%ProgramFiles%\\Git\\cmd\\git.exe"' in source
    assert 'if exist "%LOCALAPPDATA%\\Programs\\Git\\cmd\\git.exe"' in source
    assert ':get_engine' in source
    assert 'findstr /C:"alina.git_conflict_kit.v1"' in source
    assert 'if /I "%SYNC_OPTION%"=="--portable-self-check" goto :self_check' in source
    assert "GIT_LFS_SKIP_SMUDGE=1" in source
    assert "restore_alina.py" not in source
    assert "alina_sync" not in source.casefold()
