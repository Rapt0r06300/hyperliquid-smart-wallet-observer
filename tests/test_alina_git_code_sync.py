"""Deterministic Git reconciliation tests on disposable local bare remotes.

No real GitHub network, credentials, users' PCs, or AlinaSync shards.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import alina_git_code_sync as sync_module
from tools.alina_git_code_sync import Synchronizer, _status_paths


def test_status_paths_parse_spaces_and_rename_records():
    raw = (
        b" M src/file with space.py\0"
        b"R  docs/new name.md\0docs/old name.md\0"
    )
    assert _status_paths(raw) == [
        "src/file with space.py", "docs/new name.md", "docs/old name.md",
    ]


def test_inventory_uses_cached_status_for_tracked_changes(tmp_path: Path) -> None:
    task = Synchronizer(tmp_path)
    commands: list[tuple[str, ...]] = []

    def fake_command(*args: str, **_kwargs):
        commands.append(args)
        if args[0] == "status":
            return subprocess.CompletedProcess(
                args, 0, b" M src/changed.py\0", b""
            )
        return subprocess.CompletedProcess(args, 0, b"", b"")

    task.command = fake_command  # type: ignore[method-assign]
    staged, tracked, untracked = task._inventory()

    assert staged == []
    assert tracked == ["src/changed.py"]
    assert untracked == []
    assert any(args[:2] == ("status", "--porcelain=v1") for args in commands)
    assert not any("--modified" in args or "--deleted" in args for args in commands)


def test_sync_receipt_records_exact_preflight_inventory_and_remote_divergence(repos):
    local, cloud, origin = repos
    local_head = git(local, "rev-parse", "HEAD")
    cloud_commit(cloud, "docs/cloud.md", "cloud\n")
    remote_head = git(origin, "rev-parse", "main")
    (local / "src" / "base.py").write_text("base = 2\n", encoding="utf-8")
    (local / "tools").mkdir()
    (local / "tools" / "local.py").write_text("local = 1\n", encoding="utf-8")
    protected = local / "runtime" / "recovery" / "full" / "usable" / "shard.jsonl"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"fixture only\n")

    rc, receipt = run_sync(local)

    assert rc == 0
    preflight = receipt["preflight"]
    inventory = preflight["inventory"]
    assert preflight["local_head"] == local_head
    assert preflight["remote_head_observed"] == remote_head
    assert preflight["remote_head_fetched"] == remote_head
    assert preflight["ahead_commits"] == 0
    assert preflight["behind_commits"] == 1
    assert inventory["staged"]["count"] == 0
    assert inventory["tracked_changes"]["paths"] == ["src/base.py"]
    assert inventory["untracked"]["paths"] == ["tools/local.py"]
    assert "/runtime/**" in inventory["excluded_untracked_patterns"]
    assert all("shard.jsonl" not in path for path in inventory["untracked"]["paths"])
    assert protected.read_bytes() == b"fixture only\n"


def test_timed_out_inventory_is_explicitly_logged_and_keeps_wip(
    repos, monkeypatch, capsys,
) -> None:
    local, _, origin = repos
    local_head = git(local, "rev-parse", "HEAD")
    wip = local / "src" / "base.py"
    wip.write_text("base = 9\n", encoding="utf-8")
    real_run_git = sync_module._run_git

    def timeout_status(root, git_executable, args, **kwargs):
        if args and args[0] == "status":
            return real_run_git(
                root,
                sys.executable,
                ["-c", "import time; time.sleep(5)"],
                timeout=0.02,
                on_progress=kwargs.get("on_progress"),
            )
        return real_run_git(root, git_executable, args, **kwargs)

    monkeypatch.setattr(sync_module, "_run_git", timeout_status)
    task = Synchronizer(local, allow_test_remote=True)

    rc = task.run()
    receipt = json.loads(
        (local / "runtime/reports/git-sync/LAST_SYNC.json").read_text(
            encoding="utf-8"
        )
    )

    assert rc == 2
    assert receipt["status"] == "NO_GO"
    timeout = next(
        row for row in receipt["git_commands"]
        if row["operation"] == "Inventaire des modifications locales"
    )
    assert timeout["timed_out"] is True
    assert timeout["exit_code"] == -1
    assert task.report["push_attempts"] == 0
    assert task.report["local_commit_created"] is False
    assert git(local, "rev-parse", "HEAD") == local_head
    assert git(origin, "rev-parse", "main") == local_head
    assert wip.read_text(encoding="utf-8") == "base = 9\n"
    output = capsys.readouterr().out
    assert "[TIMEOUT] Inventaire des modifications locales" in output
    assert "[NO_GO]" in output


def test_git_command_prints_named_step_duration_and_exit_code(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    calls = []

    def fake_run_git(root, git, args, **kwargs):
        calls.append((tuple(args), kwargs))
        return subprocess.CompletedProcess([git, *args], 0, b"", b"")

    monkeypatch.setattr(sync_module, "_run_git", fake_run_git)
    task = Synchronizer(tmp_path)
    task.command("status", "--porcelain=v1", "-z", "--untracked-files=no")

    output = capsys.readouterr().out
    assert "[GIT 001]" in output
    assert "Inventaire des modifications locales" in output
    assert "code=0" in output
    assert "duree=" in output
    assert len(task.report["git_commands"]) == 1
    assert calls[0][1]["live_stderr"] is False


@pytest.mark.parametrize("verb", ["fetch", "push"])
def test_network_git_commands_stream_progress_to_terminal(
    tmp_path: Path, monkeypatch, capsys, verb: str,
) -> None:
    calls = []

    def fake_run_git(root, git, args, **kwargs):
        calls.append((tuple(args), kwargs))
        return subprocess.CompletedProcess([git, *args], 0, b"", None)

    monkeypatch.setattr(sync_module, "_run_git", fake_run_git)
    task = Synchronizer(tmp_path)
    task.command(verb, "--progress", "origin")

    output = capsys.readouterr().out
    assert "GitHub" in output
    assert "code=0" in output
    assert calls[0][1]["live_stderr"] is True


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
    assert receipt["merge_commits_created"] == 0
    assert receipt["rebases_performed"] == 1
    assert git(origin, "rev-list", "--merges", "main") == ""
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


def test_conflicting_edits_abort_rebase_and_keep_both_commits(repos):
    local, cloud, origin = repos
    cloud_commit(cloud, "src/base.py", "base = 200\n")
    (local / "src/base.py").write_text("base = 300\n")
    rc, receipt = run_sync(local)
    assert rc == 2 and receipt["local_commit_created"] is True
    assert receipt["status"] == "NO_GO"
    assert git(local, "show", "HEAD:src/base.py") == "base = 300"
    assert git(origin, "show", "main:src/base.py") == "base = 200"
    assert receipt["merge_commits_created"] == 0
    assert receipt["rebases_performed"] == 0
    assert git(local, "rev-parse", "-q", "--verify", "MERGE_HEAD",
               allow_error=True) == ""
    assert git(local, "rev-parse", "refs/alina-sync/last-local-checkpoint") == git(
        local, "rev-parse", "HEAD"
    )
    gitdir = Path(git(local, "rev-parse", "--absolute-git-dir"))
    assert not (gitdir / "rebase-merge").exists()
    assert not (gitdir / "rebase-apply").exists()
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
    assert receipt["rebases_performed"] == 0
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


def test_exact_historical_jsonl_relocation_syncs_with_concurrent_cloud_change(repos):
    local, cloud, origin = repos
    source = "CLAUDE_TASKS.jsonl"
    destination = "docs/archive/root-history/CLAUDE_TASKS.jsonl"
    payload = '{"task":"historical registry"}\n'
    cloud_commit(cloud, source, payload)
    git(local, "pull", "--ff-only")
    original_blob = subprocess.run(
        ["git", "show", f"HEAD:{source}"], cwd=local,
        capture_output=True, check=True,
    ).stdout

    archived = local / destination
    archived.parent.mkdir(parents=True, exist_ok=True)
    (local / source).replace(archived)
    cloud_commit(cloud, "docs/cloud.md", "remote change preserved\n")

    rc, receipt = run_sync(local)

    assert rc == 0 and receipt["status"] == "SYNCHRONIZED"
    assert receipt["merge_commits_created"] == 0
    assert receipt["rebases_performed"] == 1
    assert git(origin, "rev-list", "--merges", "main") == ""
    assert receipt["verified_historical_relocations"] == [{
        "source": source,
        "destination": destination,
        "sha256": hashlib.sha256(original_blob).hexdigest(),
        "worktree_sha256": hashlib.sha256(archived.read_bytes()).hexdigest(),
        "proof": "INDEX_AND_WORKTREE_BLOB_EXACT",
    }]
    tree = set(git(origin, "ls-tree", "-r", "--name-only", "main").splitlines())
    assert source not in tree and destination in tree
    archived_blob = subprocess.run(
        ["git", "show", f"main:{destination}"], cwd=origin,
        capture_output=True, check=True,
    ).stdout
    assert archived_blob == original_blob
    assert git(origin, "show", "main:docs/cloud.md") == "remote change preserved"
    assert git(local, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_modified_historical_jsonl_relocation_stays_protected(repos):
    local, cloud, origin = repos
    source = "CLAUDE_TASKS.jsonl"
    destination = "docs/archive/root-history/CLAUDE_TASKS.jsonl"
    payload = '{"task":"historical registry"}\n'
    cloud_commit(cloud, source, payload)
    git(local, "pull", "--ff-only")

    archived = local / destination
    archived.parent.mkdir(parents=True, exist_ok=True)
    (local / source).replace(archived)
    archived.write_text(payload + '{"task":"changed"}\n', encoding="utf-8")

    rc, receipt = run_sync(local)

    assert rc == 2 and receipt["status"] == "NO_GO"
    assert receipt["local_commit_created"] is False
    assert receipt["push_attempts"] == 0
    assert archived.read_text(encoding="utf-8") == payload + '{"task":"changed"}\n'
    tree = set(git(origin, "ls-tree", "-r", "--name-only", "main").splitlines())
    assert source in tree and destination not in tree
    assert git(local, "diff", "--cached", "--name-only") == ""


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
    assert git(origin, "show", "main:data/safe.jsonl") == "initial"


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



def test_conflict_kit_python_source_has_no_invalid_escape_warnings() -> None:
    import warnings

    source = (Path(__file__).resolve().parents[1] /
              "tools/alina_git_code_sync.py").read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, "tools/alina_git_code_sync.py", "exec")
    assert "alina.git_conflict_kit.v1" in source
    assert r"\`" not in source


def test_windows_launcher_bootstraps_git_without_legacy_cmd() -> None:
    """Double-click resolves missing local helpers without fetching shards."""
    launcher = Path(__file__).resolve().parents[1] / "POUSSER-GITHUB-FORCE.cmd"
    source = launcher.read_text(encoding="utf-8-sig")
    assert 'call "%~dp0PREPARER_GIT_PORTABLE.cmd"' not in source
    assert 'call :download_source "tools/install_portable_git.ps1"' in source
    assert 'call :download_source "tools/alina_git_code_sync.py"' in source
    assert "ALINA_BOOTSTRAP_REF=main" in source
    assert '-File "%ALINA_INSTALLER%"' in source
    assert 'if exist "%ProgramFiles%\\Git\\cmd\\git.exe"' in source
    assert 'if exist "%LOCALAPPDATA%\\Programs\\Git\\cmd\\git.exe"' in source
    assert ':get_engine' in source
    assert 'ALINA_ENGINE_REQUIRED_BUILD=2026-10-27-linear-safe-relocation-v3' in source
    assert 'findstr /C:"%ALINA_ENGINE_REQUIRED_BUILD%"' in source
    assert 'findstr /C:"%ALINA_ENGINE_REQUIRED_BUILD%" "%ALINA_ENGINE%"' in source
    assert 'if /I "%SYNC_OPTION%"=="--portable-self-check" goto :self_check' in source
    assert "GIT_LFS_SKIP_SMUDGE=1" in source
    assert "restore_alina.py" not in source
    assert "alina_sync" not in source.casefold()
    assert "[LANCEUR 1/6]" in source
    assert "[LANCEUR 6/6]" in source
    assert "DRY-RUN TERMINE" in source


def test_new_edit_during_fetch_is_checkpointed_and_published(repos):
    local, _, origin = repos
    original = git(origin, "rev-parse", "main")

    class LateEdit(Synchronizer):
        wrote = False
        fetch_count = 0

        def command(self, *args, **kwargs):
            result = super().command(*args, **kwargs)
            if args and args[0] == "fetch":
                self.fetch_count += 1
            if self.fetch_count == 2 and not self.wrote:
                self.wrote = True
                (local / "src" / "added_during_fetch.py").write_text(
                    "late = True\n", encoding="utf-8"
                )
            return result

    task = LateEdit(local, allow_test_remote=True)
    assert task.run() == 0
    assert task.report["status"] == "SYNCHRONIZED"
    assert task.report["publishable_paths_seen"] == 1
    assert task.report["late_checkpoint_attempts"] == 1
    assert task.report["late_local_paths"] == ["src/added_during_fetch.py"]
    assert task.report["push_attempts"] == 1
    assert git(origin, "rev-parse", "main") != original
    assert git(origin, "show", "main:src/added_during_fetch.py") == "late = True"
    assert git(local, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_late_invalid_python_saved_locally_never_pushed(repos):
    local, _, origin = repos
    before = git(origin, "rev-parse", "main")

    class LateInvalid(Synchronizer):
        wrote = False
        fetch_count = 0

        def command(self, *args, **kwargs):
            result = super().command(*args, **kwargs)
            if args and args[0] == "fetch":
                self.fetch_count += 1
            if self.fetch_count == 2 and not self.wrote:
                self.wrote = True
                (local / "src" / "incomplete.py").write_text(
                    "def broken(:\n", encoding="utf-8"
                )
            return result

    task = LateInvalid(local, allow_test_remote=True)
    assert task.run() == 2
    assert task.report["status"] == "NO_GO"
    assert task.report["local_commit_created"] is True
    assert task.report["local_syntax_check"] == "FAILED_WIP_CHECKPOINT_PRESERVED"
    assert git(origin, "rev-parse", "main") == before
    assert git(local, "show", "HEAD:src/incomplete.py") == "def broken(:"


def test_repeated_external_edits_stop_after_bounded_local_checkpoints(repos):
    local, _, origin = repos
    before = git(origin, "rev-parse", "main")

    class AlwaysChanging(Synchronizer):
        n = 0
        fetch_count = 0

        def command(self, *args, **kwargs):
            result = super().command(*args, **kwargs)
            if args and args[0] == "fetch":
                self.fetch_count += 1
                if self.fetch_count >= 2:
                    self.n += 1
                (local / "src" / f"concurrent_{self.n}.py").write_text(
                    f"value = {self.n}\n", encoding="utf-8"
                )
            return result

    task = AlwaysChanging(local, allow_test_remote=True)
    assert task.run() == 2
    assert task.report["status"] == "NO_GO"
    assert task.report["push_attempts"] == 0
    assert task.report["late_checkpoint_attempts"] == 3
    assert "src/concurrent_4.py" in task.report["late_local_paths"]
    assert "change encore" in task.report["error"]
    assert git(origin, "rev-parse", "main") == before
    for i in range(1, 4):
        assert git(local, "show", f"HEAD:src/concurrent_{i}.py") == f"value = {i}"
    assert (local / "src/concurrent_4.py").is_file()
