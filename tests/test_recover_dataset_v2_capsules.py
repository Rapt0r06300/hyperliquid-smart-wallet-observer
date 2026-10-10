from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _module():
    spec = importlib.util.spec_from_file_location(
        "recover_dataset_v2_capsules_test",
        ROOT / "tools" / "recover_dataset_v2_capsules.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_recover_pending_skips_completion_receipts_without_remote_probe(
    monkeypatch,
):
    module = _module()
    releases = [
        {
            "tag_name": "alina-recovery-complete",
            "created_at": "2026-10-07T00:00:00Z",
            "assets": [{"name": module.COMPLETE_NAME}],
        },
        {
            "tag_name": "alina-recovery-pending",
            "created_at": "2026-10-07T01:00:00Z",
            "assets": [{"name": module.INDEX_NAME}],
        },
    ]
    monkeypatch.setattr(module, "list_recovery_releases", lambda _repo: releases)
    calls = []

    def fake_recover_one(_repository, release, _root):
        calls.append(release["tag_name"])
        return {
            "recovery_tag": release["tag_name"],
            "requested_tag": "data-v2-test",
            "status": "RECOVERED",
            "canonical_release_tag": "data-v2-test",
            "shard_count": 1,
        }

    monkeypatch.setattr(module, "recover_one", fake_recover_one)

    report = module.recover_pending("owner/repo", limit=1)

    assert calls == ["alina-recovery-pending"]
    assert report["already_complete"] == 1
    assert report["attempted"] == 1
    assert report["recovered"] == 1
    assert report["failures"] == []

def test_recovery_retry_on_transient_github_504(monkeypatch):
    module = _module()
    import subprocess

    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/gh")
    calls = []
    waits = []

    def run(command, **_kwargs):
        calls.append(command)
        if len(calls) < 3:
            return subprocess.CompletedProcess(command, 1, "", "gh: HTTP 504")
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "sleep", waits.append)
    result = module._gh(["api", "repos/owner/repo/releases?per_page=100&page=10"])
    assert result.returncode == 0
    assert len(calls) == 3
    assert waits == [1, 2]


def test_recovery_permanent_api_error_never_retried(monkeypatch):
    module = _module()
    import subprocess
    import pytest

    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/gh")
    calls = []
    waits = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "gh: HTTP 403")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.time, "sleep", waits.append)
    with pytest.raises(module.RecoveryError, match="HTTP 403"):
        module._gh(["api", "repos/owner/repo/releases"])
    assert len(calls) == 1
    assert waits == []


def test_recovery_release_status_probe_fails_closed_on_504(monkeypatch):
    module = _module()
    import subprocess
    import pytest

    def bad_probe(args, *, check=True):
        return subprocess.CompletedProcess(args, 1, "", "gh: HTTP 504")

    monkeypatch.setattr(module, "_gh", bad_probe)
    with pytest.raises(module.RecoveryError, match="cannot verify canonical Release"):
        module._canonical_complete("owner/repo", "some-tag")
    with pytest.raises(module.RecoveryError, match="cannot verify canonical Release"):
        module._any_canonical_complete("owner/repo", ["some-tag"])


def test_recovery_missing_release_remains_recoverable(monkeypatch):
    module = _module()
    import subprocess

    monkeypatch.setattr(
        module, "_gh",
        lambda args, *, check=True: subprocess.CompletedProcess(
            args, 1, "", "gh: HTTP 404"
        ),
    )
    assert module._canonical_complete("owner/repo", "missing-tag") is False
    assert module._any_canonical_complete("owner/repo", ["missing-tag"]) is None
