from __future__ import annotations

import pkgutil
import signal
from pathlib import Path

import pytest

import hl_observer
from tests.coverage_contract_harness import require_explicit_coverage_shard, run_typed_contracts


def _small_modules() -> tuple[str, ...]:
    package_root = Path(next(iter(hl_observer.__path__)))
    modules = []
    for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer."):
        relative = info.name.removeprefix("hl_observer.").replace(".", "/")
        source = package_root / f"{relative}.py"
        if not source.is_file():
            continue
        if len(source.read_text(encoding="utf-8", errors="ignore").splitlines()) <= 60:
            modules.append(info.name)
    return tuple(sorted(modules))


def test_typed_long_tail_contracts_are_offline_and_bounded(tmp_path, monkeypatch) -> None:
    if not hasattr(signal, "setitimer"):
        pytest.skip("POSIX bounded-call support required")
    shard, total = require_explicit_coverage_shard()
    modules = _small_modules()
    assert len(modules) >= 750
    targets = modules[shard::total]
    imported, attempts, completed, controlled_failures = run_typed_contracts(
        targets,
        tmp_path,
        monkeypatch,
    )
    assert imported >= max(1, int(len(targets) * 0.95))
    assert attempts >= max(10, len(targets))
    assert completed >= max(2, len(targets) // 4)
    assert completed + controlled_failures == attempts
