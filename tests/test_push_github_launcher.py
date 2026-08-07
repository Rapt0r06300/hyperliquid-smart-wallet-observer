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
    assert '-ProjectRoot "%~dp0."' in main_text
    assert "FETCH_HEAD" not in helper_text
    assert '"push", "origin", "main:main"' in helper_text
    assert "merge-base" in helper_text
    assert "refs/remotes/hypersmart-bundles" in helper_text
    assert "reset --hard" not in helper_text
    assert '"push", "--force"' not in helper_text

    for alias in ALIASES:
        alias_text = alias.read_text(encoding="utf-8")
        assert "POUSSER-GITHUB-FORCE.cmd" in alias_text
        assert "FETCH_HEAD" not in alias_text


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
