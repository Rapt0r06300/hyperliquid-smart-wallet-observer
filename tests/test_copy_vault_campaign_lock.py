from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from queue import Empty

import pytest

from hl_observer.backtesting import copy_vault_local_lab as lab


def _campaign_inputs(workspace: Path, repository_root: Path) -> None:
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in lab._MATERIALIZED_TAPE_NAMES:
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    assets = [{
        "dataset_id": "fixture-safe-l2",
        "family": "copy_vault_l2",
        "release_tag": "fixture-release",
        "release_asset": "fixture-l2.jsonl.gz",
        "manifest_path": "catalog/manifests/fixture-safe-l2.json",
        "bytes": 1,
        "sha256": "c" * 64,
    }]
    source_index_sha = "b" * 64
    manifest = {
        "paper_read_only": True,
        "real_execution": False,
        "source_index_sha256": source_index_sha,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 12,
        "unique_books": 12,
        "data_complete": True,
        "materialized_tapes": tape_manifest,
        "verified_source_assets": assets,
        "source_asset_inventory_count": len(assets),
        "source_asset_inventory_sha256": lab._source_asset_inventory_sha256(assets),
        "source_asset_inventory_complete": True,
    }
    manifest["selection_digest"] = lab._source_selection_digest(source_index_sha, assets)
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    research_root = repository_root / "runtime" / "codex_research"
    research_root.mkdir(parents=True)
    (research_root / "HYPOTHESIS_LEDGER.jsonl").write_text("", encoding="utf-8")
    (research_root / "COPY_V21_PHYSICAL_FREEZE.json").write_text(
        json.dumps({"freeze": {"parameters": {
            "core_notional_usd": 50,
            "probe_notional_usd": 10,
            "daily_profit_lock_usd": 5,
        }}}),
        encoding="utf-8",
    )


def _install_campaign_stubs() -> None:
    signal_times = [
        (10 + day) * 86_400_000 + 60_000 for day in range(12)
    ]
    metaorders = [
        {"signal_ts_ms": timestamp, "action": "ADD", "coin": "BTC"}
        for timestamp in signal_times
    ]
    books = {"BTC": [{"ts_ms": timestamp - 1_000} for timestamp in signal_times]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {
                "live_fill_rows": len(metaorders),
                "causal_live_fill_rows": len(metaorders),
                "historical_fill_rows": 0,
            }

    lab._load_pipeline = lambda: Pipeline()
    lab._campaign_engine_source_sha256 = lambda _pipeline: "d" * 64
    lab.cv.cluster_metaorders = lambda _entries: (metaorders, {})
    lab.cv.load_observed_books = lambda *_args, **_kwargs: (books, {})
    lab.evaluate_frozen_v21_segment = lambda *_args, **_kwargs: {
        "eligible": False,
        "reasons": ["temporary lock fixture"],
        "candidate_count": 0,
        "daily_mean_net_pnl_usd": 0.0,
        "active_day_mean_net_pnl_usd": 0.0,
        "statistics": {
            "sample_count": 1,
            "distinct_days": 1,
            "daily_net_pnl_usd": [0.0],
            "daily_net_pnl_usd_exact_decimal": ["0"],
        },
    }


def _run_blocked_campaign(
    workspace: str,
    repository_root: str,
    acquired: multiprocessing.synchronize.Event,
    continue_run: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    _install_campaign_stubs()

    def wait_until_released(_repository_root, *, exclude_selection_digest):
        acquired.set()
        if not continue_run.wait(15):
            raise TimeoutError("campaign test owner timed out")
        return 0

    lab._prior_copy_vault_trial_count = wait_until_released
    try:
        result = lab.run_local_campaign(
            workspace, repository_root=repository_root, max_trials=1,
        )
        results.put({"status": result.get("status"), "reason": result.get("reason")})
    except BaseException as exc:  # noqa: BLE001 - report child failures to the parent test.
        results.put({"error": f"{type(exc).__name__}: {exc}"})


def _forbid_os_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        pytest.fail("Copy-Vault campaign locks must not probe PIDs with os.kill")

    monkeypatch.setattr(lab.os, "kill", fail_if_called)


def _release_lock(lock: object) -> None:
    release = getattr(lock, "release", None)
    if callable(release):
        release()
    elif isinstance(lock, int):
        os.close(lock)


def _hold_campaign_lock(
    path: str,
    acquired: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
    errors: multiprocessing.queues.Queue,
) -> None:
    try:
        lock = lab._campaign_lock(Path(path))
        acquired.set()
        if not release.wait(15):
            errors.put("timed out waiting for release")
        _release_lock(lock)
    except BaseException as exc:  # noqa: BLE001 - report child failures to the parent test.
        errors.put(f"{type(exc).__name__}: {exc}")


def test_live_campaign_lock_rejects_second_owner_without_signalling_pid(tmp_path, monkeypatch):
    lock_path = tmp_path / "campaign.lock"
    _forbid_os_kill(monkeypatch)

    owner = lab._campaign_lock(lock_path)
    try:
        with pytest.raises(RuntimeError, match="COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"):
            lab._campaign_lock(lock_path)
    finally:
        _release_lock(owner)

    assert lock_path.is_file()


def test_stale_or_corrupt_pid_text_does_not_override_os_lock(tmp_path, monkeypatch):
    lock_path = tmp_path / "campaign.lock"
    lock_path.write_text("not-a-live-lock-owner\n", encoding="ascii")
    _forbid_os_kill(monkeypatch)

    owner = lab._campaign_lock(lock_path)
    try:
        assert lock_path.is_file()
    finally:
        _release_lock(owner)

    assert str(os.getpid()) in lock_path.read_text(encoding="ascii")
    # The path is deliberately stable: unlinking it can split the OS lock across inodes.
    assert lock_path.is_file()


def test_campaign_lock_allows_only_one_process(tmp_path, monkeypatch):
    lock_path = tmp_path / "campaign.lock"
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    errors = context.Queue()
    child = context.Process(
        target=_hold_campaign_lock,
        args=(str(lock_path), acquired, release, errors),
    )
    child.start()
    try:
        assert acquired.wait(15), "child did not acquire the campaign lock"
        _forbid_os_kill(monkeypatch)
        with pytest.raises(RuntimeError, match="COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"):
            lab._campaign_lock(lock_path)
    finally:
        release.set()
        child.join(timeout=15)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)

    assert child.exitcode == 0
    with pytest.raises(Empty):
        errors.get_nowait()
    assert lock_path.is_file()


def test_os_lock_is_released_after_owner_crash_without_replacing_lock_path(tmp_path):
    lock_path = tmp_path / "campaign.lock"
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    errors = context.Queue()
    child = context.Process(
        target=_hold_campaign_lock,
        args=(str(lock_path), acquired, release, errors),
    )
    child.start()
    assert acquired.wait(15), "child did not acquire the campaign lock"

    child.terminate()
    child.join(timeout=15)
    if child.is_alive():
        child.kill()
        child.join(timeout=5)

    assert child.exitcode != 0
    assert lock_path.is_file()
    owner = lab._campaign_lock(lock_path)
    try:
        assert lock_path.is_file()
    finally:
        _release_lock(owner)
    assert lock_path.is_file()


def test_run_local_campaign_rejects_concurrent_process_before_trial_work(tmp_path):
    workspace = tmp_path / "workspace"
    repository_root = tmp_path / "repo"
    workspace.mkdir()
    _campaign_inputs(workspace, repository_root)
    _install_campaign_stubs()

    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    continue_run = context.Event()
    results = context.Queue()
    child = context.Process(
        target=_run_blocked_campaign,
        args=(str(workspace), str(repository_root), acquired, continue_run, results),
    )
    child.start()
    try:
        assert acquired.wait(20), "campaign owner did not reach the held-lock checkpoint"
        contender = lab.run_local_campaign(
            workspace, repository_root=repository_root, max_trials=1,
        )
        assert contender["status"] == "TECHNICAL_FAILURE"
        assert contender["reason"] == "COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"
    finally:
        continue_run.set()
        child.join(timeout=20)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)

    assert child.exitcode == 0
    assert results.get(timeout=5).get("error") is None
    lock_path = (
        repository_root / "runtime" / "codex_research"
        / "copy_vault_continuous_lab" / ".active.lock"
    )
    assert lock_path.is_file()


def test_run_local_campaign_releases_lock_after_unexpected_exception(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository_root = tmp_path / "repo"
    workspace.mkdir()
    _campaign_inputs(workspace, repository_root)
    _install_campaign_stubs()

    def raise_unexpected_exception(_repository_root, *, exclude_selection_digest):
        raise AssertionError("injected campaign failure")

    monkeypatch.setattr(
        lab, "_prior_copy_vault_trial_count", raise_unexpected_exception,
    )

    with pytest.raises(AssertionError, match="injected campaign failure"):
        lab.run_local_campaign(
            workspace, repository_root=repository_root, max_trials=1,
        )

    lock_path = (
        repository_root / "runtime" / "codex_research"
        / "copy_vault_continuous_lab" / ".active.lock"
    )
    assert lock_path.is_file()
    owner = lab._campaign_lock(lock_path)
    try:
        assert lock_path.is_file()
    finally:
        _release_lock(owner)
    assert lock_path.is_file()
    owner = lab._campaign_lock(lock_path)
    try:
        assert lock_path.is_file()
    finally:
        _release_lock(owner)
    assert lock_path.is_file()
