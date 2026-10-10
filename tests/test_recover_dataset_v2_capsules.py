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


def test_recovery_pages_halve_on_504_without_skipping_or_repeating(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "RECOVERY_RELEASE_PAGE_SIZE", 4)
    monkeypatch.setattr(module, "MIN_RECOVERY_RELEASE_PAGE_SIZE", 1)
    calls = []

    def fake_api(path):
        from urllib.parse import parse_qs
        query = parse_qs(path.split("?", 1)[1])
        size = int(query["per_page"][0])
        page = int(query["page"][0])
        calls.append((size, page))
        if size == 4 and page == 2:
            raise module.RecoveryError("GitHub HTTP 504")
        tags = [
            {"tag_name": f"alina-recovery-{i}", "created_at": f"2026-10-{i + 1:02}T00:00:00Z"}
            for i in range(7)
        ]
        first = (page - 1) * size
        return tags[first:first + size]

    monkeypatch.setattr(module, "_json_api", fake_api)
    found = module.list_recovery_releases("owner/repo")
    assert [x["tag_name"] for x in found] == [f"alina-recovery-{i}" for i in range(7)]
    assert calls == [(4, 1), (4, 2), (2, 3), (2, 4)]


def test_recovery_listing_504_at_min_page_never_returns_partial(monkeypatch):
    module = _module()
    import pytest
    monkeypatch.setattr(module, "RECOVERY_RELEASE_PAGE_SIZE", 2)
    monkeypatch.setattr(module, "MIN_RECOVERY_RELEASE_PAGE_SIZE", 1)

    def fake_api(path):
        if "page=1" in path:
            return [{"tag_name": "alina-recovery-first"}] * 2
        raise module.RecoveryError("GitHub HTTP 504")

    monkeypatch.setattr(module, "_json_api", fake_api)
    with pytest.raises(module.RecoveryError, match="HTTP 504"):
        module.list_recovery_releases("owner/repo")

def test_recovery_deep_offset_failure_switches_to_verified_git_refs(monkeypatch):
    module = _module()
    import subprocess

    monkeypatch.setattr(module, "RECOVERY_RELEASE_PAGE_SIZE", 2)
    monkeypatch.setattr(module, "MIN_RECOVERY_RELEASE_PAGE_SIZE", 1)

    def fake_api(path):
        if "/releases?" in path:
            raise module.RecoveryError("HTTP 504")
        if "/git/matching-refs/tags/" in path:
            return [
                {"ref": "refs/tags/alina-recovery-aaa"},
                {"ref": "refs/tags/alina-recovery-bbb"},
                {"ref": "refs/tags/unrelated"},
            ]
        raise AssertionError(path)

    def fake_gh(args, *, check=True):
        tag = args[1].rsplit("/", 1)[-1]
        if tag.endswith("bbb"):
            return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
        return subprocess.CompletedProcess(args, 0, __import__("json").dumps({
            "tag_name": tag, "created_at": "2026-10-10T00:00:00Z",
            "assets": [{"name": module.INDEX_NAME}],
        }), "")

    monkeypatch.setattr(module, "_json_api", fake_api)
    monkeypatch.setattr(module, "_gh", fake_gh)
    assert [r["tag_name"] for r in module.list_recovery_releases("owner/repo")] == [
        "alina-recovery-aaa"
    ]


def test_recovery_git_refs_refuses_ambiguous_release_status(monkeypatch):
    module = _module()
    import subprocess
    import pytest
    monkeypatch.setattr(module, "_json_api", lambda _path: [
        {"ref": "refs/tags/alina-recovery-one"},
    ])
    monkeypatch.setattr(
        module, "_gh", lambda args, *, check=True:
        subprocess.CompletedProcess(args, 1, "", "HTTP 403"),
    )
    with pytest.raises(module.RecoveryError, match="HTTP 403"):
        module._recovery_releases_from_git_refs("owner/repo")



def test_recovery_metadata_request_timeout_retries_but_never_assumes_missing(monkeypatch):
    module = _module()
    import subprocess
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/gh")
    calls, waits = [], []

    def fake_run(command, **kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.time, "sleep", waits.append)
    result = module._gh(["api", "repos/owner/repo/releases?per_page=25&page=40"])
    assert result.returncode == 0
    assert calls == [60, 60]
    assert waits == [1]
