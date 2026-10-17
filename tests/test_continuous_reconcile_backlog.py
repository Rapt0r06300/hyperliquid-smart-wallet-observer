"""Fail-closed inventory and Git error classification for continuous Release waves."""
import pytest
from tools.continuous_reconcile_backlog import pending, PACK


def test_pending_respects_release_aliases_status_and_quarantine() -> None:
    index = {
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "run_manifest_release_tags_by_release": {"data-v2-physical": "data-v2-alias"},
        "shards": [
            {"release_tag": "data-v2-physical"},
            {"release_tag": "copy-vault-v2-done"},
        ],
    }
    rows = (
        "data-v2-next\ttrue\n"
        "data-v2-alias\ttrue\n"
        "copy-vault-v2-done\ttrue\n"
        "archive-v2-hold\ttrue\n"
        "data-v2-missing\tfalse\n"
        "data-v2-next\ttrue\n"
    )
    assert pending(rows, index, {"archive-v2-hold"}) == ["data-v2-next"]


def test_malformed_inventory_rejected() -> None:
    with pytest.raises(ValueError):
        pending("missing-tab", {"shards": []}, set())
    with pytest.raises(ValueError):
        pending("../attack\ttrue", {"shards": []}, set())


def test_git_pack_failure_not_confused_with_concurrent_main_update() -> None:
    assert PACK.search("remote unpack failed: index-pack failed")
    assert PACK.search("tree too large")
    assert not PACK.search("! [rejected] HEAD -> main (fetch first)")


def test_remote_contains_head_checks_exact_git_ancestry(monkeypatch):
    import subprocess
    import tools.continuous_reconcile_backlog as module
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args)
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", "")
        if args[:3] == ("git", "merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(module, "run", fake_run)
    assert module.remote_contains_head()
    assert ("git", "fetch", "origin", "main") in seen
    assert ("git", "merge-base", "--is-ancestor", "a" * 40, "origin/main") in seen


def test_disjoint_rebase_refusal_does_not_force_or_retry_push(monkeypatch):
    import subprocess
    import tools.continuous_reconcile_backlog as module
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 3, "", "unsafe remote changes")

    monkeypatch.setattr(module, "run", fake_run)
    assert module.try_disjoint_campaign_rebase() == (False, False)
    assert len(seen) == 1
    assert seen[0][:3] == ("python", "tools/rebase_disjoint_catalog_publication.py", "--remote")


def test_disjoint_rebase_reports_pack_rejection_without_forcing(monkeypatch):
    import subprocess
    import tools.continuous_reconcile_backlog as module
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args)
        if args[0] == "python":
            return subprocess.CompletedProcess(args, 0, "SAFE_DISJOINT_REBASE_OK", "")
        return subprocess.CompletedProcess(args, 1, "", "remote unpack failed: index-pack failed")

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "remote_contains_head", lambda: False)
    assert module.try_disjoint_campaign_rebase() == (False, True)
    assert not any("--force" in args for args in seen)


def test_disjoint_rebase_published_requires_remote_ancestry(monkeypatch):
    import subprocess
    import tools.continuous_reconcile_backlog as module
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "OK", "")

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "remote_contains_head", lambda: True)
    assert module.try_disjoint_campaign_rebase() == (True, False)
    assert any(args[:3] == ("git", "push", "--no-thin") for args in seen)
