from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from queue import Empty

import pytest

from hl_observer.backtesting import copy_vault_local_lab as lab


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
