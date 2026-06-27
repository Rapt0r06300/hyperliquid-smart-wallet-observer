from __future__ import annotations

import os
import subprocess
import sys

from hl_observer.data_sources.provider_registry import default_provider_specs
from hl_observer.local_index.index_benchmark import run_local_scan_benchmark
from hl_observer.local_index.query_engine import scan_wallet_index
from hl_observer.local_index.wallet_index import WalletLocalIndex, fake_wallet
from hl_observer.realtime_monitor.hot_watch_rotation import HotWatchSlot, rotate_hot_watch
from hl_observer.wallet_universe.wallet_universe import import_wallet_universe_lines


def test_local_index_benchmark_scans_2000_wallets_without_network() -> None:
    result = run_local_scan_benchmark(2000)
    assert result.wallets_scanned == 2000
    assert result.network_used is False
    assert result.wallets_per_second > 0


def test_local_index_rejects_truncated_and_dedupes() -> None:
    index = WalletLocalIndex()
    assert index.upsert(fake_wallet(1)) is True
    assert index.upsert(fake_wallet(1)) is True
    assert index.upsert(fake_wallet(2)) is True
    assert len(index) == 2
    summary = scan_wallet_index(index, limit=10)
    assert summary.wallets_scanned == 2


def test_provider_registry_defaults_are_safe() -> None:
    providers = default_provider_specs()
    by_name = {provider.provider_name: provider for provider in providers}
    assert by_name["LocalCacheProvider"].enabled_by_default is True
    assert by_name["LocalCacheProvider"].requires_network is False
    assert by_name["OfficialInfoProvider"].enabled_by_default is False
    assert by_name["OfficialWsProvider"].enabled_by_default is False
    assert by_name["ExplorerPublicProvider"].enabled_by_default is False
    assert by_name["ThirdPartyProvider"].requires_api_key is True


def test_wallet_universe_import_rejects_truncated_and_invalid() -> None:
    good = "0x" + "a" * 40
    result = import_wallet_universe_lines([good, good, "0xabc...def", "nope"])
    assert result.imported == 1
    assert result.duplicates == 1
    assert result.rejected == 2
    assert "TRUNCATED_ADDRESS_REJECTED" in result.rejected_reasons
    assert "INVALID_ADDRESS_REJECTED" in result.rejected_reasons


def test_hot_watch_rotation_never_exceeds_ten_and_keeps_active_slot() -> None:
    active = HotWatchSlot(
        slot_id=1,
        wallet_address="0x" + "f" * 40,
        priority=1.0,
        assigned_at_ms=0,
        expires_at_ms=200_000,
        reason="existing",
        source="test",
        last_event_at_ms=99_000,
    )
    candidates = [(f"0x{i:040x}", float(i), 99_000) for i in range(20)]
    slots = rotate_hot_watch(candidates, now_ms=100_000, max_slots=10, existing_slots=[active])
    assert len(slots) == 10
    assert any(slot.wallet_address == active.wallet_address for slot in slots)


def test_new_cli_commands_are_available(tmp_path) -> None:
    env = os.environ.copy()
    env["HL_DATABASE_URL"] = f"sqlite:///{(tmp_path / 'cli_commands.sqlite3').as_posix()}"
    env["HL_LOGS_DIR"] = str(tmp_path / "logs")
    for args in [
        ["research-data-sources"],
        ["benchmark-local-scan", "--wallets", "2000"],
        ["scan-local", "--limit", "20"],
        ["hot-watch", "--duration-seconds", "5", "--dry-run"],
        ["simulation-report", "--period", "24h"],
    ]:
        completed = subprocess.run(
            [sys.executable, "-m", "hl_observer", *args],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
