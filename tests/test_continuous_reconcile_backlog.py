"""Fail-closed inventory and Git error classification for continuous Release waves."""
import pytest
from tools.continuous_reconcile_backlog import pending, PACK


def test_sparse_historical_publication_keeps_fail_closed_catalog_validation() -> None:
    source = __import__("inspect").getsource(
        __import__("tools.continuous_reconcile_backlog", fromlist=["publish"]).publish
    )
    assert '"tools/check_dataset_quality.py", "--catalog-only"' in source
    assert '"git", "add", "--sparse", "catalog", "datasets"' in source


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


def test_budget_grows_after_proven_multi_release_publication() -> None:
    from tools.continuous_reconcile_backlog import next_shard_budget
    assert next_shard_budget(20000, 4, 4) == 26666
    assert next_shard_budget(60000, 4, 4) == 60000
    assert next_shard_budget(20000, 1, 1) == 20000


def test_budget_shrinks_on_rejected_pack_and_rejects_missing_proof() -> None:
    from tools.continuous_reconcile_backlog import next_shard_budget
    assert next_shard_budget(30000, 6, 3) == 15000
    assert next_shard_budget(5000, 2, 1) == 5000
    for args in ((20000, 4, 0), (20000, 4, 5), (4000, 2, 2)):
        with pytest.raises(ValueError, match="adaptive wave"):
            next_shard_budget(*args)


def test_large_first_release_grows_staging_budget_without_skipping(
    tmp_path, monkeypatch,
) -> None:
    import tools.continuous_reconcile_backlog as module
    attempted = []

    def fake_select(tags, root, *, max_shards, max_manifest_bytes):
        attempted.append(max_shards)
        if max_shards < 33000:
            raise ValueError("single Release exceeds safe publication budget: first")
        return [tags[0]], 33000

    monkeypatch.setattr(module, "select_prefix", fake_select)
    assert module.select_with_bounded_oversized_retry(
        ["first", "second"], tmp_path, shard_budget=20000,
    ) == (["first"], 33000, 40000)
    assert attempted == [20000, 40000]


def test_oversized_release_fails_closed_at_hard_cap(tmp_path, monkeypatch) -> None:
    import tools.continuous_reconcile_backlog as module
    attempted = []

    def fake_select(tags, root, *, max_shards, max_manifest_bytes):
        attempted.append(max_shards)
        raise ValueError("single Release exceeds safe publication budget: massive")

    monkeypatch.setattr(module, "select_prefix", fake_select)
    with pytest.raises(ValueError, match="single Release"):
        module.select_with_bounded_oversized_retry(
            ["massive"], tmp_path, shard_budget=20000,
        )
    assert attempted == [20000, 40000, 80000, 100000]


def test_invalid_release_never_triggers_budget_growth(tmp_path, monkeypatch) -> None:
    import tools.continuous_reconcile_backlog as module

    def fake_select(tags, root, *, max_shards, max_manifest_bytes):
        raise ValueError("invalid immutable Release manifest")

    monkeypatch.setattr(module, "select_prefix", fake_select)
    with pytest.raises(ValueError, match="invalid immutable"):
        module.select_with_bounded_oversized_retry(
            ["invalid"], tmp_path, shard_budget=20000,
        )


def test_pending_cache_reuses_exact_git_blob_only(monkeypatch):
    import tools.continuous_reconcile_backlog as module
    calls = []

    def fake_read(_):
        calls.append("read")
        return {"shards": []}

    monkeypatch.setattr(module, "read_index", fake_read)
    sha_old = "a" * 40
    sha_new = "b" * 40
    expected = ["data-v2-first"]
    assert module.current_pending(
        "invalid-inventory-because-cache-is-valid",
        set(), sha_old, sha_old, expected,
    ) == expected
    assert calls == []
    expected.append("data-v2-mutated")
    assert module.current_pending(
        "invalid-inventory-because-cache-is-valid",
        set(), sha_old, sha_old, expected,
    ) is not expected
    assert module.current_pending(
        "data-v2-fresh\ttrue\n", set(), sha_new, sha_old, expected,
    ) == ["data-v2-fresh"]
    assert calls == ["read"]


def test_index_blob_sha_requires_exact_git_object_identity(monkeypatch):
    import subprocess
    import tools.continuous_reconcile_backlog as module
    monkeypatch.setattr(
        module, "run",
        lambda *args, **kw: subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", ""),
    )
    assert module.index_blob_sha() == "a" * 40
    monkeypatch.setattr(
        module, "run",
        lambda *args, **kw: subprocess.CompletedProcess(args, 0, "bad-sha", ""),
    )
    with pytest.raises(RuntimeError, match="invalid canonical index"):
        module.index_blob_sha()



def test_oversized_staging_budget_returns_to_safe_steady_state() -> None:
    from tools.continuous_reconcile_backlog import next_shard_budget

    # A valid oversized Release may temporarily require 80k-100k shards.
    assert next_shard_budget(80000, requested=1, published=1) == 60000
    assert next_shard_budget(100000, requested=1, published=1) == 60000
    assert next_shard_budget(100000, requested=3, published=3) == 60000
    # Rejected pack reductions must remain conservative.
    assert next_shard_budget(100000, requested=3, published=1) == 30000
    # Over the absolute staging cap is forbidden, not silently clamped.
    with pytest.raises(ValueError, match="invalid adaptive wave"):
        next_shard_budget(100001, requested=1, published=1)


def test_release_window_expands_only_after_durable_multi_release_proof() -> None:
    from tools.continuous_reconcile_backlog import next_release_window
    assert next_release_window(24, requested=12, published=12) == 48
    assert next_release_window(48, requested=30, published=30) == 96
    assert next_release_window(96, requested=30, published=30) == 96
    assert next_release_window(24, requested=1, published=1) == 24


def test_release_window_recovers_from_rejected_pack_without_skipping() -> None:
    from tools.continuous_reconcile_backlog import next_release_window
    assert next_release_window(96, requested=50, published=25) == 48
    assert next_release_window(48, requested=10, published=5) == 24
    assert next_release_window(24, requested=10, published=5) == 24
    for args in ((23, 2, 2), (97, 2, 2), (24, 0, 0), (24, 4, 0),
                 (24, 2, 3)):
        with pytest.raises(ValueError, match="adaptive Release window"):
            next_release_window(*args)

def test_historical_manifest_budget_uses_verified_success_and_pack_refusal() -> None:
    from tools.continuous_reconcile_backlog import next_manifest_budget
    mib = 1024 * 1024
    assert next_manifest_budget(64 * mib, 3, 3) == 96 * mib
    assert next_manifest_budget(96 * mib, 4, 4) == 128 * mib
    assert next_manifest_budget(128 * mib, 6, 6) == 128 * mib
    assert next_manifest_budget(128 * mib, 6, 3) == 64 * mib
    assert next_manifest_budget(64 * mib, 1, 1) == 64 * mib
    for args in ((63 * mib, 2, 2), (129 * mib, 2, 2),
                 (64 * mib, 2, 0), (64 * mib, 2, 3)):
        with pytest.raises(ValueError, match="adaptive manifest"):
            next_manifest_budget(*args)


def test_historical_manifest_staging_budget_is_propagated_and_bounded(
    monkeypatch, tmp_path,
) -> None:
    import tools.continuous_reconcile_backlog as module
    seen = []

    def fake_select(tags, root, *, max_shards, max_manifest_bytes):
        seen.append(max_manifest_bytes)
        return [tags[0]], 5000

    monkeypatch.setattr(module, "select_prefix", fake_select)
    result = module.select_with_bounded_oversized_retry(
        ["first"], tmp_path, shard_budget=20000,
        manifest_budget_bytes=96 * 1024 * 1024,
    )
    assert result == (["first"], 5000, 20000)
    assert seen == [96 * 1024 * 1024]
    with pytest.raises(ValueError, match="historical manifest"):
        module.select_with_bounded_oversized_retry(
            ["first"], tmp_path, shard_budget=20000,
            manifest_budget_bytes=129 * 1024 * 1024,
        )
