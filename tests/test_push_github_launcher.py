from __future__ import annotations

import os
import shutil

import pytest
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_LAUNCHER = ROOT / "POUSSER-GITHUB-FORCE.cmd"
ALIASES = [ROOT / "POUSSER_TOUT_LE_TRAVAIL.cmd", ROOT / "REPARER_ET_POUSSER.cmd"]
HELPER = ROOT / "tools" / "push_github_safe.ps1"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git(repo: Path, *args: str) -> str:
    return _run("git", *args, cwd=repo).stdout.strip()


def test_push_launchers_share_one_safe_implementation() -> None:
    main_text = MAIN_LAUNCHER.read_text(encoding="utf-8")
    helper_text = HELPER.read_text(encoding="utf-8")

    assert "tools\\push_github_safe.ps1" in main_text
    assert "tools\\git\\cmd\\git.exe" in main_text
    assert '-GitExecutable "%HYPERSMART_GIT%"' in main_text
    assert '"%~1"=="--dry-run"' in main_text
    assert '-ProjectRoot "%~dp0."' in main_text
    assert "FETCH_HEAD" not in helper_text
    assert '"push", "origin", "main:main"' in helper_text
    assert "merge-base" in helper_text
    assert "refs/remotes/hypersmart-bundles" in helper_text
    assert "reset --hard" not in helper_text
    assert '"push", "--force"' not in helper_text
    assert "PREPARER_GIT_PORTABLE.cmd" in helper_text
    assert '"^(runtime|logs|data)/"' in helper_text

    for alias in ALIASES:
        alias_text = alias.read_text(encoding="utf-8")
        assert "POUSSER-GITHUB-FORCE.cmd" in alias_text
        assert "FETCH_HEAD" not in alias_text


def test_portable_git_installer_is_pinned_and_hash_verified() -> None:
    installer = (ROOT / "tools" / "install_portable_git.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "PREPARER_GIT_PORTABLE.cmd").read_text(encoding="utf-8")

    assert "git-for-windows/git/releases/download" in installer
    assert "MinGit-2.54.0-64-bit.zip" in installer
    assert "04F937E1F0918B17B9BE6F2294CB2BB66E96E1D9832D1C298E2DE088A1D0E668" in installer
    assert "Get-FileHash" in installer
    assert "cmd\\git.exe" in installer
    assert 'cd /d "%~dp0"' in bootstrap
    assert "install_portable_git.ps1" in bootstrap


@pytest.mark.skipif(os.name != "nt", reason="le lanceur GitHub s'execute via Windows PowerShell")
def test_safe_push_reconciles_remote_and_skips_stale_bundle(tmp_path: Path) -> None:
    if shutil.which("powershell.exe") is None:
        raise AssertionError("Windows PowerShell est requis par le lanceur GitHub")

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    local = tmp_path / "local"

    _run("git", "init", "--bare", str(remote), cwd=tmp_path)
    _run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    _git(seed, "config", "user.name", "HyperSmart Test")
    _git(seed, "config", "user.email", "hypersmart-test@example.invalid")
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "base.txt")
    _git(seed, "commit", "-m", "base")
    base_sha = _git(seed, "rev-parse", "HEAD")
    _git(seed, "branch", "a-pousser", base_sha)
    stale_bundle = tmp_path / "hypersmart_launcher.bundle"
    _git(seed, "bundle", "create", str(stale_bundle), "a-pousser")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    _run("git", "clone", "-b", "main", str(remote), str(local), cwd=tmp_path)
    _git(local, "config", "user.name", "HyperSmart Test")
    _git(local, "config", "user.email", "hypersmart-test@example.invalid")

    _git(seed, "checkout", "-b", "bundle-divergent", base_sha)
    (seed / "bundle-only.txt").write_text("bundle only\n", encoding="utf-8")
    _git(seed, "add", "bundle-only.txt")
    _git(seed, "commit", "-m", "divergent bundle work")
    divergent_sha = _git(seed, "rev-parse", "HEAD")
    divergent_bundle = tmp_path / "hypersmart_428.bundle"
    _git(seed, "bundle", "create", str(divergent_bundle), "bundle-divergent")
    _git(seed, "checkout", "main")

    (seed / "remote.txt").write_text("remote\n", encoding="utf-8")
    _git(seed, "add", "remote.txt")
    _git(seed, "commit", "-m", "remote work")
    remote_work_sha = _git(seed, "rev-parse", "HEAD")
    _git(seed, "push", "origin", "main")

    (local / "local.txt").write_text("local\n", encoding="utf-8")
    _git(local, "add", "local.txt")
    _git(local, "commit", "-m", "local work")
    local_work_sha = _git(local, "rev-parse", "HEAD")
    exclude_file = local / ".git" / "info" / "exclude"
    exclude_file.write_text("*.bundle\n", encoding="utf-8")
    shutil.copy2(stale_bundle, local / stale_bundle.name)
    shutil.copy2(divergent_bundle, local / divergent_bundle.name)

    result = _run(
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(HELPER),
        "-ProjectRoot",
        str(local),
        cwd=local,
    )

    assert "[DEJA INTEGRE]" in result.stdout
    assert "[ARCHIVE SANS MERGE]" in result.stdout
    assert "main et origin/main sont identiques" in result.stdout
    remote_main = _git(local, "rev-parse", "refs/remotes/origin/main")
    assert _git(local, "rev-parse", "main") == remote_main
    assert _git(local, "merge-base", "--is-ancestor", remote_work_sha, remote_main) == ""
    assert _git(local, "merge-base", "--is-ancestor", local_work_sha, remote_main) == ""
    assert _git(local, "rev-parse", "refs/remotes/hypersmart-bundles/hypersmart_428/bundle-divergent") == divergent_sha
    divergent_in_main = subprocess.run(
        ("git", "merge-base", "--is-ancestor", divergent_sha, remote_main),
        cwd=local,
        capture_output=True,
    )
    assert divergent_in_main.returncode == 1


@pytest.mark.skipif(os.name != "nt", reason="le helper GitHub s'execute via Windows PowerShell")
def test_safe_push_tolerates_runtime_dirt_but_refuses_source_dirt(tmp_path: Path) -> None:
    git_exe = shutil.which("git")
    if git_exe is None or shutil.which("powershell.exe") is None:
        raise AssertionError("Git et Windows PowerShell sont requis")

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    local = tmp_path / "local"
    _run("git", "init", "--bare", str(remote), cwd=tmp_path)
    _run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    _git(seed, "config", "user.name", "HyperSmart Test")
    _git(seed, "config", "user.email", "hypersmart-test@example.invalid")
    (seed / "runtime").mkdir()
    (seed / "src").mkdir()
    (seed / "runtime" / "state.json").write_text("{}\n", encoding="utf-8")
    (seed / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _run("git", "clone", "-b", "main", str(remote), str(local), cwd=tmp_path)

    (local / "runtime" / "state.json").write_text('{"live":true}\n', encoding="utf-8")
    runtime_result = subprocess.run(
        (
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(HELPER), "-ProjectRoot", str(local),
            "-GitExecutable", git_exe, "-DryRun",
        ),
        cwd=local,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert runtime_result.returncode == 0, runtime_result.stdout + runtime_result.stderr
    assert "Artefacts runtime vivants ignores" in runtime_result.stdout

    (local / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    source_result = subprocess.run(
        (
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(HELPER), "-ProjectRoot", str(local),
            "-GitExecutable", git_exe, "-DryRun",
        ),
        cwd=local,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert source_result.returncode != 0
    assert "n'est pas committe" in source_result.stdout
