from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import tools.publish_main_commit as publisher_module

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_CONTROL_WRITERS = (
    ".github/workflows/create-resumable-campaigns.yml",
    ".github/workflows/resumable-campaign-worker.yml",
    ".github/workflows/advance-analysis-stage.yml",
    ".github/workflows/analysis-stage-controller.yml",
    ".github/workflows/control-phase.yml",
    ".github/workflows/phase-request-controller.yml",
    ".github/workflows/alina-operator-intent.yml",
    ".github/workflows/alina-operator-dispatch.yml",
    ".github/workflows/campaign-resilience-receipt.yml",
    ".github/workflows/campaign-watchdog.yml",
    ".github/workflows/alina-canonical-closure-report.yml",
    ".github/workflows/economic-scoreboard-receipt.yml",
    ".github/workflows/canonical-spec-verification.yml",
)


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _configure(cwd: Path) -> None:
    _git("config", "user.name", "CopyVault test", cwd=cwd)
    _git("config", "user.email", "copyvault-test@example.invalid", cwd=cwd)


def test_campaign_control_workflows_use_the_shared_atomic_publisher() -> None:
    missing = [
        workflow
        for workflow in CAMPAIGN_CONTROL_WRITERS
        if "tools/publish_main_commit.py" not in (ROOT / workflow).read_text(encoding="utf-8")
    ]
    assert missing == []

    sparse_checkouts_missing_helper = [
        workflow
        for workflow in CAMPAIGN_CONTROL_WRITERS
        if "sparse-checkout:" in (ROOT / workflow).read_text(encoding="utf-8")
        and not any(
            line.strip() == "tools"
            for line in (ROOT / workflow).read_text(encoding="utf-8").splitlines()
        )
    ]
    assert sparse_checkouts_missing_helper == []


def test_parallel_main_publishers_preserve_both_fast_forward_commits(tmp_path: Path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is required for the local bare-repository integration test")

    publisher = ROOT / "tools" / "publish_main_commit.py"
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    _git("init", "--bare", "--initial-branch=main", str(origin))
    _git("clone", str(origin), str(seed))
    _configure(seed)
    (seed / "catalog").mkdir()
    (seed / "catalog" / "base.json").write_text("{}\n", encoding="utf-8")
    _git("add", "catalog/base.json", cwd=seed)
    _git("commit", "-m", "seed main", cwd=seed)
    base_sha = _git("rev-parse", "HEAD", cwd=seed)
    _git("push", "origin", "HEAD:refs/heads/main", cwd=seed)

    barrier = tmp_path / "push-barrier"
    barrier.mkdir()
    hook = """#!/bin/sh
set -eu
if [ -n \"${ALINA_TEST_WRITER:-}\" ] && [ ! -f \"$ALINA_TEST_BARRIER/$ALINA_TEST_WRITER\" ]; then
  : > \"$ALINA_TEST_BARRIER/$ALINA_TEST_WRITER\"
  i=0
  while [ \"$i\" -lt 500 ]; do
    if [ -f \"$ALINA_TEST_BARRIER/writer-a\" ] && [ -f \"$ALINA_TEST_BARRIER/writer-b\" ]; then exit 0; fi
    i=$((i+1))
    sleep 0.01
  done
  echo 'timed out waiting for both publishers at the push boundary' >&2
  exit 1
fi
exit 0
"""

    workers: list[tuple[str, Path]] = []
    for label, filename in (("writer-a", "campaign-a.json"), ("writer-b", "campaign-b.json")):
        checkout = tmp_path / label
        _git("clone", str(origin), str(checkout))
        _configure(checkout)
        (checkout / "catalog" / filename).write_text(f'{label}\n', encoding="utf-8")
        _git("add", f"catalog/{filename}", cwd=checkout)
        _git("commit", "-m", f"publish {label}", cwd=checkout)
        hook_path = checkout / ".git" / "hooks" / "pre-push"
        hook_path.write_text(hook, encoding="utf-8", newline="\n")
        if os.name != "nt":
            hook_path.chmod(0o755)
        workers.append((label, checkout))

    processes: list[tuple[str, subprocess.Popen[str]]] = []
    for label, checkout in workers:
        env = os.environ.copy()
        env["ALINA_TEST_WRITER"] = label
        env["ALINA_TEST_BARRIER"] = str(barrier)
        process = subprocess.Popen(
            [
                sys.executable,
                str(publisher),
                "--remote",
                "origin",
                "--branch",
                "main",
                "--max-attempts",
                "12",
                "--base-delay-seconds",
                "0.01",
                "--max-delay-seconds",
                "0.08",
            ],
            cwd=checkout,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append((label, process))

    reports: list[tuple[str, int, str, str]] = []
    for label, process in processes:
        try:
            stdout, stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            pytest.fail(f"{label} publisher timed out; stdout={stdout!r}; stderr={stderr!r}")
        reports.append((label, process.returncode, stdout, stderr))

    assert all(code == 0 for _, code, _, _ in reports), reports

    verified = tmp_path / "verified"
    _git("clone", str(origin), str(verified))
    assert (verified / "catalog" / "campaign-a.json").read_text(encoding="utf-8") == "writer-a\n"
    assert (verified / "catalog" / "campaign-b.json").read_text(encoding="utf-8") == "writer-b\n"
    assert _git("merge-base", "--is-ancestor", base_sha, "HEAD", cwd=verified) == ""
    commits = _git("log", "--format=%s", "main", cwd=verified).splitlines()
    assert commits.count("publish writer-a") == 1
    assert commits.count("publish writer-b") == 1


def test_conflicting_main_publish_keeps_remote_and_local_commits_unmodified(tmp_path: Path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is required for the local bare-repository integration test")

    publisher = ROOT / "tools" / "publish_main_commit.py"
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    _git("init", "--bare", "--initial-branch=main", str(origin))
    _git("clone", str(origin), str(seed))
    _configure(seed)
    (seed / "catalog").mkdir()
    (seed / "catalog" / "shared.json").write_text('{"value":"base"}\n', encoding="utf-8")
    _git("add", "catalog/shared.json", cwd=seed)
    _git("commit", "-m", "seed main", cwd=seed)
    _git("push", "origin", "HEAD:refs/heads/main", cwd=seed)

    writer_a = tmp_path / "writer-a"
    writer_b = tmp_path / "writer-b"
    _git("clone", str(origin), str(writer_a))
    _git("clone", str(origin), str(writer_b))
    for checkout in (writer_a, writer_b):
        _configure(checkout)

    (writer_a / "catalog" / "shared.json").write_text('{"value":"accepted-a"}\n', encoding="utf-8")
    _git("add", "catalog/shared.json", cwd=writer_a)
    _git("commit", "-m", "publish writer-a", cwd=writer_a)
    _git("push", "origin", "HEAD:refs/heads/main", cwd=writer_a)

    (writer_b / "catalog" / "shared.json").write_text('{"value":"pending-b"}\n', encoding="utf-8")
    _git("add", "catalog/shared.json", cwd=writer_b)
    _git("commit", "-m", "publish writer-b", cwd=writer_b)
    pending_sha = _git("rev-parse", "HEAD", cwd=writer_b)

    publish = subprocess.run(
        [sys.executable, str(publisher), "--branch", "main", "--max-attempts", "3"],
        cwd=writer_b,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert publish.returncode != 0
    assert "rebase conflict" in publish.stderr
    assert _git("rev-parse", "HEAD", cwd=writer_b) == pending_sha
    assert _git("status", "--porcelain", cwd=writer_b) == ""

    verified = tmp_path / "verified"
    _git("clone", str(origin), str(verified))
    assert (verified / "catalog" / "shared.json").read_text(encoding="utf-8") == '{"value":"accepted-a"}\n'
    remote_has_pending = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pending_sha, "main"],
        cwd=verified,
        capture_output=True,
        text=True,
    )
    assert remote_has_pending.returncode == 128
    assert "not a valid commit name" in remote_has_pending.stderr.casefold()


def test_git_transport_timeouts_are_bounded_retryable_and_noninteractive(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def timeout(*command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["timeout"] = kwargs.get("timeout")
        env = kwargs.get("env")
        observed["terminal_prompt"] = env.get("GIT_TERMINAL_PROMPT") if isinstance(env, dict) else None
        raise subprocess.TimeoutExpired(
            cmd=list(command),
            timeout=float(kwargs.get("timeout", 0.0)),
            output=b"partial git output",
            stderr=b"transport stalled",
        )

    monkeypatch.setattr(publisher_module.subprocess, "run", timeout)
    monkeypatch.setattr(publisher_module, "GIT_COMMAND_TIMEOUT_SECONDS", 0.25)

    result = publisher_module._git("fetch", "origin")

    assert result.returncode == 124
    assert "timed out" in result.stderr.casefold()
    assert observed == {"timeout": 0.25, "terminal_prompt": "0"}
    assert publisher_module._retryable(result)
