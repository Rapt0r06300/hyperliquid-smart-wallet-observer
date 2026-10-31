from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

from hl_observer.backtesting import copy_vault_local_lab as local_lab
from hl_observer.backtesting.copy_vault_local_lab import (
    _historical_train_proxy,
    _market_context_row,
    _record_external_market_catalog_row,
    _signal_coverage,
    load_improvement_history,
    materialize_safe_workspace,
    record_frozen_candidate,
    run_historical_trade_replay,
)


def test_safe_market_context_is_exposed_to_lab_without_becoming_pnl() -> None:
    wrapper = {
        "source_id": "hyperliquid_public_copy_vault_market_ws",
        "channel": "copy_vault_trades",
        "instrument": "xyz:TSLA",
        "event_kind": "EVENT",
        "exchange_ts_ms": 2_002,
        "received_ts_ms": 2_010,
        "local_monotonic_ns": 123,
        "provenance": {
            "venue": "hyperliquid", "access": "read_only",
            "authenticated": False, "transport": "websocket",
            "timestamp_semantics": "causal_event_availability",
        },
        "raw_payload": json.dumps({"channel": "trades", "data": [{
            "coin": "xyz:TSLA", "time": 2_002, "px": "100.5", "sz": "1",
            "side": "B", "hash": "0xtrade", "tid": 7,
        }]}),
        "raw_sha256": "a" * 64,
        "parsed_summary": {"event_count": 1, "data_gate_ready": False},
        "read_only": True,
        "real_execution": False,
        "_raw": {"channel": "trades", "data": [{
            "coin": "xyz:TSLA", "time": 2_002, "px": "100.5", "sz": "1",
            "side": "B", "hash": "0xtrade", "tid": 7,
        }]},
    }

    row = _market_context_row(wrapper, family="copy_vault_trades", audit=Counter())

    assert row is not None
    assert row["instrument"] == "xyz:TSLA"
    assert row["event_ts_ms"] == 2_002
    assert row["pnl_eligible"] is False
    assert row["observation_only"] is True


def test_safe_market_context_rejects_native_instrument_mismatch() -> None:
    wrapper = {
        "source_id": "hyperliquid_public_copy_vault_market_ws",
        "channel": "copy_vault_bbo", "instrument": "xyz:TSLA",
        "exchange_ts_ms": 2_002, "received_ts_ms": 2_010,
        "provenance": {
            "venue": "hyperliquid", "access": "read_only",
            "authenticated": False, "transport": "websocket",
            "timestamp_semantics": "causal_event_availability",
        },
        "raw_payload": "{}", "raw_sha256": "b" * 64,
        "parsed_summary": {"data_gate_ready": False},
        "read_only": True, "real_execution": False,
        "_raw": {"channel": "bbo", "data": {
            "coin": "XYZ:TSLA", "time": 2_002,
            "bbo": [{"px": "100", "sz": "1"}, {"px": "101", "sz": "1"}],
        }},
    }
    audit = Counter()
    assert _market_context_row(wrapper, family="copy_vault_bbo", audit=audit) is None
    assert audit["MARKET_NATIVE_INSTRUMENT_MISMATCH_REJECTED"] == 1


def test_external_safe_catalog_inventory_is_bounded_and_never_pnl_eligible() -> None:
    inventory = {}
    row = {
        "dataset_id": "binance-bbo-1", "family": "bbo", "venue": "BINANCE",
        "quality_status": "SAFE", "replay_compatible": True,
        "validation_allowed": True, "bytes": 1234,
        "event_count": 50, "start_ts_ms": 1_000, "end_ts_ms": 2_000,
        "trade_count": 40, "trade_count_exact": True,
        "unique_trade_count": 39, "unique_trade_count_exact": True,
    }

    _record_external_market_catalog_row(inventory, row)
    _record_external_market_catalog_row(inventory, {**row, "dataset_id": "binance-bbo-2"})
    summary = local_lab._external_market_catalog_rows(inventory)[0]

    assert summary["venue"] == "binance" and summary["family"] == "bbo"
    assert summary["safe_catalog_shards"] == 2
    assert summary["replay_compatible_safe_catalog_shards"] == 2
    assert summary["safe_catalog_bytes"] == 2468
    assert summary["event_count_exact"] is True and summary["event_count"] == 100
    assert summary["trade_count_exact"] is True and summary["trade_count"] == 80
    assert summary["unique_trade_count_exact"] is True
    assert summary["unique_trade_count"] == 78
    assert summary["pnl_eligible"] is False
    assert summary["replay_eligible"] is False
    assert summary["loaded_payload_rows"] == 0


def test_external_catalog_inventory_marks_inexact_counts_unknown() -> None:
    inventory = {}
    _record_external_market_catalog_row(inventory, {
        "dataset_id": "okx-trades-1", "family": "trades", "venue": "okx",
        "quality_status": "SAFE", "replay_compatible": True,
        "bytes": 100, "event_count": 5,
        "trade_count": 4, "trade_count_exact": False,
        "unique_trade_count": None, "unique_trade_count_exact": False,
    })

    summary = local_lab._external_market_catalog_rows(inventory)[0]

    assert summary["event_count"] == 5 and summary["event_count_exact"] is True
    assert summary["trade_count"] is None and summary["trade_count_exact"] is False
    assert summary["unique_trade_count"] is None
    assert summary["unique_trade_count_exact"] is False


def test_funding_rate_requires_exact_forward_window_and_stays_out_of_pnl() -> None:
    coverage = {
        "schema": "alina.copy_vault_exact_window_receipt.v1",
        "status": "COMPLETE", "request_type": "fundingHistory",
        "window_kind": "FORWARD", "requested_start_ms": 1_000,
        "requested_end_ms": 2_000, "leaf_start_ms": 1_000,
        "leaf_end_ms": 2_000, "leaf_response_rows": 1,
        "leaf_accepted_rows": 1, "forward_evidence_allowed": True,
    }
    wrapper = {
        "channel": "copy_vault_funding_rates", "source_id": "hyperliquid_public_funding_history_forward",
        "instrument": "BTC", "received_ts_ms": 1_600,
        "provenance": {
            "network": "mainnet", "access": "read_only", "authenticated": False,
            "transport": "https", "request_type": "fundingHistory",
            "window_kind": "FORWARD", "forward_evidence_allowed": True,
        },
        "read_only": True, "real_execution": False,
        "raw_sha256": "a" * 64,
        "_raw": {"channel": "fundingHistory", "data": {
            "coin": "BTC", "coverage": coverage,
            "records": [{"time": 1_500, "fundingRate": "0.0001", "premium": "0.002"}],
        }},
    }

    rows = local_lab._funding_rate_rows(
        wrapper, family="copy_vault_funding_rates", audit=Counter(),
    )

    assert len(rows) == 2
    assert rows[0]["record_type"] == "COVERAGE_RECEIPT"
    assert rows[1]["record_type"] == "SETTLEMENT_RATE"
    assert rows[1]["funding_rate"] == pytest.approx(0.0001)
    assert rows[1]["premium"] == pytest.approx(0.002)
    assert rows[1]["forward_evidence_allowed"] is True
    assert rows[1]["pnl_eligible"] is False


def test_funding_rate_rejects_receipt_that_claims_forward_with_no_forward_permission() -> None:
    wrapper = {
        "channel": "copy_vault_funding_rates",
        "source_id": "hyperliquid_public_funding_history_forward",
        "instrument": "BTC", "received_ts_ms": 1_600,
        "provenance": {
            "network": "mainnet", "access": "read_only", "authenticated": False,
            "transport": "https", "request_type": "fundingHistory",
            "window_kind": "FORWARD", "forward_evidence_allowed": False,
        },
        "read_only": True, "real_execution": False,
        "_raw": {"channel": "fundingHistory", "data": {
            "coin": "BTC", "coverage": {
                "schema": "alina.copy_vault_exact_window_receipt.v1",
                "status": "COMPLETE", "request_type": "fundingHistory",
                "window_kind": "FORWARD", "requested_start_ms": 1_000,
                "requested_end_ms": 2_000, "leaf_start_ms": 1_000,
                "leaf_end_ms": 2_000, "leaf_response_rows": 0,
                "leaf_accepted_rows": 0, "forward_evidence_allowed": True,
            },
            "records": [],
        }},
    }
    audit = Counter()

    assert local_lab._funding_rate_rows(
        wrapper, family="copy_vault_funding_rates", audit=audit,
    ) == []
    assert audit["FUNDING_RATE_RECEIPT_OR_PROVENANCE_INVALID_REJECTED"] == 1


def _write_gzip(path: Path, row: dict) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def test_signal_coverage_reports_short_sample_without_inventing_days() -> None:
    day_ms = 86_400_000

    coverage = _signal_coverage([day_ms + 1_000, day_ms + 7_201_000, 2 * day_ms + 1_000, 0])

    assert coverage == {
        "distinct_utc_days": 2,
        "minimum_utc_days_required": 6,
        "signal_start_ms": day_ms + 1_000,
        "signal_end_ms": 2 * day_ms + 1_000,
        "signal_span_hours": 24.0,
    }


@pytest.mark.parametrize("stale_owner", ["not-a-live-owner-proof", "2147483647"])
def test_campaign_lock_reuses_stable_os_lock_file_and_recovers_stale_pid(
    tmp_path: Path, stale_owner: str,
) -> None:
    lock_path = tmp_path / "runtime" / "copy-vault" / ".active.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(f"{stale_owner}\n", encoding="ascii")
    original_file_id = (lock_path.stat().st_dev, lock_path.stat().st_ino)

    lock = local_lab._campaign_lock(lock_path)
    try:
        assert lock_path.is_file()
        assert callable(getattr(lock, "release", None))
        second_lock = None
        try:
            second_lock = local_lab._campaign_lock(lock_path)
        except RuntimeError as exc:
            assert str(exc) == "COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"
        else:
            pytest.fail("a second campaign acquired the same OS lock")
        finally:
            if second_lock is not None:
                second_lock.release()
    finally:
        release = getattr(lock, "release", None)
        if callable(release):
            release()
        elif type(lock) is int:  # Close the legacy descriptor so the fixture can clean up.
            os.close(lock)

    assert lock_path.is_file(), "releasing the OS lock must not unlink its stable path"
    assert (lock_path.stat().st_dev, lock_path.stat().st_ino) == original_file_id
    second_lock = local_lab._campaign_lock(lock_path)
    second_lock.release()
    assert lock_path.is_file()


def test_campaign_lock_excludes_other_process_and_recovers_after_process_exit(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "runtime" / "copy-vault" / ".active.lock"
    locked_marker = tmp_path / "child-locked"
    release_marker = tmp_path / "child-exit"
    script = "\n".join(
        [
            "import os, sys, time",
            "from pathlib import Path",
            "from hl_observer.backtesting.copy_vault_local_lab import _campaign_lock",
            "lock = _campaign_lock(Path(sys.argv[1]))",
            "Path(sys.argv[2]).write_text('locked', encoding='ascii')",
            "deadline = time.monotonic() + 10",
            "while not Path(sys.argv[3]).exists() and time.monotonic() < deadline:",
            "    time.sleep(0.01)",
            "os._exit(0 if Path(sys.argv[3]).exists() else 3)",
        ]
    )
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(root / "src"), str(root), env.get("PYTHONPATH", "")])
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path), str(locked_marker), str(release_marker)],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not locked_marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                _, stderr = process.communicate()
                pytest.fail(f"lock holder exited before acquiring the lock: {stderr}")
            time.sleep(0.01)
        assert locked_marker.is_file(), "child did not acquire the OS lock in time"

        with pytest.raises(RuntimeError, match="COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"):
            local_lab._campaign_lock(lock_path)

        assert lock_path.is_file()
        release_marker.write_text("exit", encoding="ascii")
        assert process.wait(timeout=10) == 0

        recovered_lock = local_lab._campaign_lock(lock_path)
        recovered_lock.release()
        assert lock_path.is_file(), "recovery must reuse, not unlink, the stable lock path"
    finally:
        release_marker.touch(exist_ok=True)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_campaign_lock_maps_filesystem_failures_to_technical_error(tmp_path: Path) -> None:
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("block parent creation", encoding="ascii")

    with pytest.raises(RuntimeError, match="COPY_VAULT_CAMPAIGN_LOCK_UNREADABLE"):
        local_lab._campaign_lock(parent_file / ".active.lock")


def test_run_local_campaign_releases_lock_after_internal_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(json.dumps({
        "paper_read_only": True,
        "real_execution": False,
        "selection_digest": "a" * 64,
        "source_index_sha256": "b" * 64,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 6,
        "unique_books": 6,
        "data_complete": True,
    }), encoding="utf-8")

    day_ms = 86_400_000
    metaorders = [
        {"signal_ts_ms": day * day_ms + 10_000, "action": "ADD", "coin": "BTC"}
        for day in range(1, 7)
    ]
    books = {
        "BTC": [{"ts_ms": row["signal_ts_ms"] - 1_000} for row in metaorders],
    }
    lock_path = tmp_path / "isolated" / ".active.lock"
    canonical_campaign_lock = local_lab._campaign_lock

    monkeypatch.setattr(local_lab, "_verify_materialized_tapes", lambda *_args: None)
    monkeypatch.setattr(local_lab, "_bounds", lambda _timestamps: (0, 1))
    monkeypatch.setattr(local_lab, "_campaign_lock", lambda _path: canonical_campaign_lock(lock_path))
    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: type("Pipeline", (), {
        "charger_entrees_alpha_notional_fixe_avec_audit": staticmethod(lambda _workspace: ([], {})),
    })())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", lambda *_args, **_kwargs: (books, {}))

    def fail_after_lock_is_held(*_args, **_kwargs):
        with pytest.raises(RuntimeError, match="COPY_VAULT_CAMPAIGN_ALREADY_RUNNING"):
            canonical_campaign_lock(lock_path)
        raise RuntimeError("FORCED_TEST_FAILURE_AFTER_LOCK_ACQUISITION")

    monkeypatch.setattr(local_lab, "_prior_copy_vault_trial_count", fail_after_lock_is_held)

    result = local_lab.run_local_campaign(
        workspace,
        campaign_root=tmp_path / "campaign",
    )

    assert result["status"] == "TECHNICAL_FAILURE"
    assert "FORCED_TEST_FAILURE_AFTER_LOCK_ACQUISITION" in result["reason"]
    assert lock_path.is_file(), "the lock file must remain stable after campaign failure"
    recovered_lock = canonical_campaign_lock(lock_path)
    recovered_lock.release()


def test_safe_catalog_audit_discloses_copy_vault_snapshots_outside_replay_inputs() -> None:
    rows = [
        {"family": "copy_vault_fills", "quality_status": "SAFE"},
        {"family": "copy_vault_l2", "quality_status": "SAFE"},
        {"family": "copy_vault_positions", "quality_status": "SAFE"},
        {"family": "copy_vault_selection", "quality_status": "SAFE"},
        {"family": "copy_vault_positions", "quality_status": "PARTIAL"},
        {"family": "bbo", "quality_status": "SAFE"},
    ]

    audit = local_lab._copy_vault_catalog_audit(rows)

    assert audit["copy_vault_safe_catalog_shards"] == 4
    assert audit["copy_vault_safe_catalog_by_family"] == {
        "copy_vault_fills": 1,
        "copy_vault_l2": 1,
        "copy_vault_positions": 1,
        "copy_vault_selection": 1,
    }
    assert audit["safe_copy_vault_shards_not_used_for_pnl"] == 2
    assert audit["safe_copy_vault_shards_not_used_for_pnl_by_family"] == {
        "copy_vault_positions": 1,
        "copy_vault_selection": 1,
    }


def test_auxiliary_safe_inventory_distinguishes_local_presence_from_hash_verification(
    tmp_path: Path,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    present = recovery / "usable" / "shards" / "release" / "positions.jsonl.gz"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"not hash verified by the replay audit")
    rows = [
        {
            "family": "copy_vault_positions", "quality_status": "SAFE",
            "release_tag": "release", "release_asset": "positions.jsonl.gz",
        },
        {
            "family": "copy_vault_selection", "quality_status": "SAFE",
            "release_tag": "release", "release_asset": "selection.jsonl.gz",
        },
    ]

    inventory = local_lab._copy_vault_auxiliary_inventory(rows, recovery)

    assert inventory == {
        "copy_vault_positions": {
            "catalogue_shards": 1,
            "local_files_present_unverified": 1,
            "local_files_missing": 0,
            "local_files_unsafe": 0,
        },
        "copy_vault_selection": {
            "catalogue_shards": 1,
            "local_files_present_unverified": 0,
            "local_files_missing": 1,
            "local_files_unsafe": 0,
        },
    }


@pytest.mark.skipif(os.name != "nt", reason="regresses Win32 MAX_PATH handling")
def test_auxiliary_safe_inventory_finds_long_local_paths(tmp_path: Path) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    tag = "release-" + "r" * 105
    asset_name = "positions-" + "p" * 105 + ".jsonl.gz"
    present = recovery / "usable" / "shards" / tag / asset_name
    assert len(str(present.absolute())) >= 260
    io_path = local_lab._windows_io_path(present)
    io_path.parent.mkdir(parents=True)
    io_path.write_bytes(b"verified by the main SAFE audit")
    rows = [{
        "family": "copy_vault_positions", "quality_status": "SAFE",
        "release_tag": tag, "release_asset": asset_name,
    }]

    inventory = local_lab._copy_vault_auxiliary_inventory(rows, recovery)

    assert inventory["copy_vault_positions"]["local_files_present_unverified"] == 1
    assert inventory["copy_vault_positions"]["local_files_missing"] == 0


@pytest.mark.parametrize(
    ("family", "source_id", "summary", "selection_causal"),
    [
        ("copy_vault_positions", "hyperliquid_public_info", {
            "position_count": 2, "data_gate_ready": False,
        }, None),
        ("copy_vault_selection", "hyperliquid_public_vaults", {
            "observation_only": True, "data_gate_ready": False,
        }, True),
    ],
)
def test_context_rows_are_observation_only_and_never_pnl(
    family: str, source_id: str, summary: dict, selection_causal: bool | None,
) -> None:
    provenance = {
        "access": "read_only", "authenticated": False, "transport": "https",
        "timestamp_semantics": "receive_observation_time_only",
    }
    if selection_causal is not None:
        provenance["selection_causal"] = selection_causal
    wrapper = {
        "channel": family, "source_id": source_id, "instrument": "0xabc",
        "received_ts_ms": 1_700_000_000_000,
        "provenance": provenance, "parsed_summary": summary,
        "raw_payload": "{}", "raw_sha256": hashlib.sha256(b"{}").hexdigest(),
        "_raw": {"marginSummary": {"accountValue": "25.50"}},
    }

    row = local_lab._context_row(wrapper, family=family)

    assert row is not None
    assert row["observed_at_ms"] == wrapper["received_ts_ms"]
    assert row["event_ts_ms"] is row["exchange_ts_ms"] is None
    assert row["pnl_eligible"] is False
    assert row["forward_evidence_allowed"] is False
    assert row["observation_only"] is True
    if family == "copy_vault_positions":
        assert row["nav_snapshot"]["nav_usd"] == 25.5
        assert row["nav_snapshot"]["pnl_eligible"] is False
    else:
        assert row["nav_snapshot"] is None


def test_selection_context_without_causal_selection_provenance_is_rejected() -> None:
    wrapper = {
        "channel": "copy_vault_selection", "source_id": "hyperliquid_public_vaults",
        "instrument": "0xabc", "received_ts_ms": 1_700_000_000_000,
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "https",
            "timestamp_semantics": "receive_observation_time_only",
            "selection_causal": False,
        },
        "parsed_summary": {"observation_only": True, "data_gate_ready": False},
        "raw_payload": "{}", "raw_sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    audit = Counter()

    assert local_lab._context_row(wrapper, family="copy_vault_selection", audit=audit) is None
    assert audit["CONTEXT_PROVENANCE_INVALID_REJECTED"] == 1


def test_unclassified_safe_fill_is_preserved_without_becoming_a_fill() -> None:
    raw_payload = json.dumps({
        "channel": "userFills",
        "data": {"user": "0xabc", "fills": [{"coin": "BTC", "px": "10"}]},
    }, separators=(",", ":"))
    wrapper = {
        "channel": "copy_vault_fills", "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc", "received_ts_ms": 1_700_000_000_000,
        "event_kind": "UNCLASSIFIED",
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "websocket",
        },
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
        "_raw": json.loads(raw_payload),
    }

    archived = local_lab._unclassified_fill_observation(wrapper, family="copy_vault_fills")
    normalized = local_lab._fill_rows(wrapper, family="copy_vault_fills", audit=Counter())

    assert archived is not None
    assert archived["snapshot_flag"] is None
    assert archived["event_ts_ms"] is None
    assert archived["executable"] is False and archived["pnl_eligible"] is False
    assert archived["raw_payload"] == raw_payload
    assert normalized == []


def test_fill_normalizer_preserves_native_symbol_casing() -> None:
    raw = {
        "channel": "userFills",
        "data": {
            "user": "0xabc", "isSnapshot": False,
            "fills": [{
                "coin": "kPEPE", "px": "0.001", "sz": "10", "side": "B",
                "time": 1_700_000_000_000, "fee": "0.01", "dir": "Open Long",
            }],
        },
    }
    wrapper = {
        "channel": "copy_vault_fills", "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc", "received_ts_ms": 1_700_000_000_001,
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "websocket",
        },
        "_raw": raw,
    }

    rows = local_lab._fill_rows(wrapper, family="copy_vault_fills", audit=Counter())

    assert len(rows) == 1
    assert rows[0]["coin"] == "kPEPE"


def test_valid_empty_l2_is_preserved_as_non_executable_observation() -> None:
    raw_payload = json.dumps({
        "channel": "l2Book", "data": {"coin": "BTC", "time": 1_700_000_000_000, "levels": [[], []]},
    }, separators=(",", ":"))
    wrapper = {
        "channel": "copy_vault_l2", "source_id": "hyperliquid_public_copy_l2",
        "instrument": "BTC", "received_ts_ms": 1_700_000_000_010,
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "websocket",
            "copy_vault_execution_evidence": True,
        },
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
        "_raw": json.loads(raw_payload),
    }
    rejected = Counter()

    assert local_lab._book_row(wrapper, rejection_audit=rejected) is None
    observation = local_lab._l2_unexecutable_observation(wrapper, reason="EMPTY_BOOK_SIDE")

    assert rejected["EMPTY_BOOK_SIDE"] == 1
    assert observation is not None
    assert observation["executable"] is False and observation["pnl_eligible"] is False
    assert observation["raw_payload"] == raw_payload
    assert observation["received_at_ms"] == 1_700_000_000_010


def test_l2_symbol_identity_is_case_sensitive_and_mismatch_is_rejected() -> None:
    wrapper = {
        "channel": "copy_vault_l2", "source_id": "hyperliquid_public_copy_l2",
        "instrument": "kPEPE", "received_ts_ms": 1_700_000_000_010,
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "websocket",
            "copy_vault_execution_evidence": True,
        },
        "_raw": {"channel": "l2Book", "data": {
            "coin": "KPEPE", "time": 1_700_000_000_000,
            "levels": [[{"px": "1", "sz": "10"}], [{"px": "1.01", "sz": "10"}]],
        }},
    }
    rejection_audit = Counter()

    assert local_lab._book_row(wrapper, rejection_audit=rejection_audit) is None
    assert rejection_audit["L2_INSTRUMENT_IDENTITY_MISMATCH"] == 1


def test_local_campaign_explains_insufficient_signal_days_before_search(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in (
        "vault_fills.jsonl", "vault_snapshots.jsonl",
        "copy_vault_l2_tape.jsonl", "copy_vault_context.jsonl",
        "copy_vault_l2_unexecutable.jsonl", "copy_vault_unclassified_fills.jsonl",
        "copy_vault_funding_rates.jsonl", "copy_vault_accounting_context.jsonl",
        "copy_vault_market_context.jsonl",
        "external_venue_safe_inventory.jsonl",
    ):
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = {
        "paper_read_only": True,
        "real_execution": False,
        "selection_digest": "a" * 64,
        "source_index_sha256": "b" * 64,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 2,
        "unique_books": 2,
        "data_complete": True,
        "materialized_tapes": tape_manifest,
    }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    signal_times = [10 * 86_400_000 + 10_000, 11 * 86_400_000 + 10_000]
    metaorders = [
        {"signal_ts_ms": timestamp, "action": "ADD", "coin": "BTC"}
        for timestamp in signal_times
    ]
    books = {"BTC": [{"ts_ms": timestamp - 1_000} for timestamp in signal_times]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(
        local_lab.cv,
        "load_observed_books",
        lambda *_args, **_kwargs: (books, {}),
    )

    result = local_lab.run_local_campaign(workspace)

    assert result["status"] == "MORE_DATA"
    assert result["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"
    assert result["signal_coverage"]["distinct_utc_days"] == 2
    assert result["signal_coverage"]["minimum_utc_days_required"] == 6
    assert result["temporally_aligned_add_signals"] == 2
    assert result["candidates_tested"] == 0


def test_local_campaign_identifies_absent_live_forward_fills(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in (
        "vault_fills.jsonl", "vault_snapshots.jsonl",
        "copy_vault_l2_tape.jsonl", "copy_vault_context.jsonl",
        "copy_vault_l2_unexecutable.jsonl", "copy_vault_unclassified_fills.jsonl",
        "copy_vault_funding_rates.jsonl", "copy_vault_accounting_context.jsonl",
        "copy_vault_market_context.jsonl",
        "external_venue_safe_inventory.jsonl",
    ):
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(json.dumps({
        "paper_read_only": True,
        "real_execution": False,
        "selection_digest": "a" * 64,
        "source_index_sha256": "b" * 64,
        "status": "MORE_DATA",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 1,
        "unique_books": 1,
        "data_complete": False,
        "materialized_tapes": tape_manifest,
    }), encoding="utf-8")
    signal_ms = 10 * 86_400_000 + 10_000
    metaorders = [{"signal_ts_ms": signal_ms, "action": "ADD", "coin": "BTC"}]
    books = {"BTC": [{"ts_ms": signal_ms - 31_000}]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {"live_fill_rows": 0, "causal_live_fill_rows": 0, "historical_fill_rows": 1}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", lambda *_args, **_kwargs: (books, {}))

    result = local_lab.run_local_campaign(workspace)

    assert result["status"] == "MORE_DATA"
    assert result["reason"] == "NO_SAFE_LIVE_FORWARD_FILLS"
    assert result["alignment_reason"] == "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS"
    assert result["live_fill_rows"] == 0
    assert result["historical_fill_rows"] == 1
    assert result["candidates_tested"] == 0


@pytest.mark.parametrize(
    ("report_status", "gaps", "expected_status", "expected_complete"),
    [
        ("COMPLETE", [], "READY", True),
        (
            "PARTIAL",
            [{"start_ms": 500, "end_ms": 999, "reason": "LOOKBACK_LIMIT"}],
            "MORE_DATA",
            False,
        ),
    ],
)
def test_materialize_safe_workspace_unwraps_verified_copy_vault_assets(
    tmp_path: Path, report_status: str, gaps: list[dict],
    expected_status: str, expected_complete: bool,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    tag = "data-v2-campaign-copy-vault-test"
    fills_payload = json.dumps({
        "channel": "userFills",
        "data": {"user": "0xabc", "isSnapshot": True, "fills": [{
            "time": 1_000, "coin": "BTC", "px": "100", "sz": "2",
            "side": "B", "dir": "Open Long", "startPosition": "0",
            "oid": 7, "tid": 8, "hash": "0xfill", "fee": "0.1",
        }]},
    }, separators=(",", ":"))
    fill_wrapper = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_public_userfills_backfill",
        "channel": "copy_vault_snapshot",
        "instrument": "0xabc", "received_ts_ms": 1_010,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "historical_only": True,
            "forward_evidence_allowed": False,
        },
        "raw_payload": fills_payload,
        "raw_sha256": hashlib.sha256(fills_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    levels = [[{"px": "99", "sz": "3"}], [{"px": "101", "sz": "4"}]]
    l2_payload = json.dumps({
        "channel": "l2Book", "data": {"coin": "BTC", "time": 2_000, "levels": levels},
    }, separators=(",", ":"))
    l2_wrapper = {
        "schema_version": "hypersmart.tick.v1", "channel": "copy_vault_l2",
        "source_id": "hyperliquid_public_copy_l2",
        "instrument": "BTC", "exchange_ts_ms": 2_000, "received_ts_ms": 2_010,
        "provenance": {
            "access": "read_only", "authenticated": False, "transport": "websocket",
            "copy_vault_execution_evidence": True,
        },
        "raw_payload": l2_payload,
        "raw_sha256": hashlib.sha256(l2_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    context_payload = json.dumps({
        "assetPositions": [], "user": "0xabc",
        "marginSummary": {"accountValue": "1250.75"},
    }, separators=(",", ":"))
    context_wrapper = {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_public_info",
        "channel": "copy_vault_positions",
        "instrument": "0xabc", "received_ts_ms": 2_020,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "timestamp_semantics": "receive_observation_time_only",
        },
        "parsed_summary": {"position_count": 0, "data_gate_ready": False},
        "raw_payload": context_payload,
        "raw_sha256": hashlib.sha256(context_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    market_asset_specs = []
    market_records = (
        ("copy_vault_bbo", "bbo", {
            "coin": "BTC", "time": 2_000,
            "bbo": [{"px": "99", "sz": "3"}, {"px": "101", "sz": "4"}],
        }, 2_000, 2_010, "causal_event_availability"),
        ("copy_vault_trades", "trades", [{
            "coin": "BTC", "time": 2_000, "px": "100", "sz": "1",
            "side": "B", "hash": "0xmarket-trade", "tid": 17,
        }], 2_000, 2_010, "causal_event_availability"),
        ("copy_vault_active_asset_ctx", "activeAssetCtx", {
            "coin": "BTC", "ctx": {"markPx": "100", "funding": "0.001"},
        }, None, 2_020, "receive_observation_time_only"),
        ("copy_vault_instrument_metadata", "instrument_metadata", {
            "coin": "BTC", "metadata": {"name": "BTC", "szDecimals": 5},
        }, None, 2_030, "receive_observation_time_only"),
    )
    for family, raw_channel, data, exchange_ts, received_ts, semantics in market_records:
        payload = json.dumps({"channel": raw_channel, "data": data}, separators=(",", ":"))
        wrapper = {
            "schema_version": "hypersmart.tick.v1",
            "source_id": "hyperliquid_public_copy_vault_market_ws"
            if family != "copy_vault_instrument_metadata"
            else "hyperliquid_public_copy_vault_instrument_metadata",
            "channel": family, "instrument": "BTC",
            "exchange_ts_ms": exchange_ts, "received_ts_ms": received_ts,
            "provenance": {
                "venue": "hyperliquid", "access": "read_only",
                "authenticated": False,
                "transport": "https" if raw_channel == "instrument_metadata" else "websocket",
                "timestamp_semantics": semantics,
            },
            "parsed_summary": {"data_gate_ready": False},
            "raw_payload": payload,
            "raw_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "read_only": True, "real_execution": False,
        }
        name = f"hyperliquid-{family}-test.jsonl.gz"
        size, sha = _write_gzip(recovery / "usable" / "shards" / tag / name, wrapper)
        market_asset_specs.append((f"cv-{family}-test", family, name, size, sha))
    fill_name = "hyperliquid-public-userfills-copy-vault-snapshot-test.jsonl.gz"
    l2_name = "hyperliquid-public-copy-l2-copy-vault-l2-btc-test.jsonl.gz"
    context_name = "hyperliquid-public-info-copy-vault-positions-test.jsonl.gz"
    fill_size, fill_sha = _write_gzip(recovery / "usable" / "shards" / tag / fill_name, fill_wrapper)
    l2_size, l2_sha = _write_gzip(recovery / "usable" / "shards" / tag / l2_name, l2_wrapper)
    context_size, context_sha = _write_gzip(
        recovery / "usable" / "shards" / tag / context_name, context_wrapper,
    )
    index_rows = []
    asset_specs = [
        ("cv-fill-test", "copy_vault_snapshot", fill_name, fill_size, fill_sha, None),
        ("cv-l2-test", "copy_vault_l2", l2_name, l2_size, l2_sha, None),
        ("cv-positions-test", "copy_vault_positions", context_name, context_size, context_sha, None),
        *((*spec, "hyperliquid") for spec in market_asset_specs),
    ]
    for dataset_id, family, asset_name, size, sha, venue in asset_specs:
        manifest_path = f"datasets/sharded/safe/aa/bb/{dataset_id}.manifest.json"
        manifest = {
            "schema": "alina.shard_manifest.v2", "quality_status": "SAFE",
            "replay_compatible": True, "asset_verified": True,
            "proof_of_pnl_allowed": False, "dataset_id": dataset_id,
            "family": family, "release_tag": tag, "release_asset": asset_name,
            "bytes": size, "sha256": sha,
            **({"venue": venue} if venue else {}),
            **({
                "historical_fill_observation_count": 1,
                "historical_fill_observation_count_exact": True,
            } if family == "copy_vault_snapshot" else {}),
        }
        manifest_file = tmp_path / manifest_path
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        index_rows.append({
            "dataset_id": dataset_id, "family": family, "quality_status": "SAFE",
            "replay_compatible": True, "release_tag": tag,
            "release_asset": asset_name, "manifest_path": manifest_path,
            "bytes": size, "sha256": sha,
            **({"venue": venue} if venue else {}),
        })
    # Multi-venue market data is inventoried by reference only. The lab must
    # not require or decompress this local payload for a Copy-Vault replay.
    index_rows.append({
        "dataset_id": "binance-bbo-catalog-only", "family": "bbo", "venue": "binance",
        "quality_status": "SAFE", "replay_compatible": True,
        "validation_allowed": True, "bytes": 400, "event_count": 3,
        "start_ts_ms": 1_900, "end_ts_ms": 2_000,
        "trade_count": 0, "trade_count_exact": True,
        "unique_trade_count": 0, "unique_trade_count_exact": True,
    })
    catalog = {
        "schema": "alina.data_index.v2",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "shards": index_rows,
    }
    catalog_file = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    report = {
        "status": report_status,
        "request_audit_status": "COMPLETE",
        "checkpoint_advance_allowed": True,
        "retention_cap_reached": False,
        "requested_start_ms": 100,
        "requested_end_ms": 2_000,
        "rows": 1,
        "request_budget_exhausted": False,
        "pending_windows": 0,
        "invalid_fill_count": 0,
        "failed_windows": [],
        "cap_blocked_windows": [],
        "unresolved_gaps": gaps,
    }
    result_payload = {
        "durable_persisted": True,
        "release_tag": tag,
        "stdout": json.dumps({"historical_backfill": {"0xabc": report}}),
    }
    result_sha = hashlib.sha256(
        json.dumps(
            result_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    campaign_dir = tmp_path / "catalog" / "campaigns"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "copy-vault-e1-test.json").write_text(
        json.dumps({
            "campaign_id": "copy-vault-e1-test",
            "kind": "copy_vault_collection",
            "status": "COMPLETE",
            "completed_units": {
                "unit-0": {"sha256": result_sha, "result": result_payload},
            },
        }),
        encoding="utf-8",
    )

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == expected_status
    assert result["data_complete"] is expected_complete
    assert result["historical_coverage_audit"]["status"] == report_status
    assert len(result["historical_coverage_audit"]["unresolved_gaps"]) == len(gaps)
    assert result["unique_fills"] == 1
    assert result["unique_books"] == 1
    assert result["safe_context_observations"] == 1
    assert result["safe_context_by_family"] == {"copy_vault_positions": 1}
    assert result["safe_context_expected_by_family"] == {
        "copy_vault_active_asset_ctx": 1,
        "copy_vault_bbo": 1,
        "copy_vault_instrument_metadata": 1,
        "copy_vault_positions": 1,
        "copy_vault_trades": 1,
    }
    assert result["safe_context_verified_by_family"] == result["safe_context_expected_by_family"]
    assert result["safe_market_context_coverage"]["status"] == "REQUIRED_FAMILIES_PRESENT"
    assert result["safe_market_context_coverage"]["family_presence_complete"] is True
    assert result["safe_market_context_coverage"]["temporal_alignment_status"] == (
        "NOT_PROVEN_BY_FAMILY_PRESENCE"
    )
    assert result["safe_external_market_inventory_coverage"]["status"] == "CATALOG_INVENTORY_ONLY"
    assert result["safe_external_market_inventory_coverage"]["catalog_safe_shards"] == 1
    assert result["safe_external_market_inventory_by_venue"] == {"binance": 1}
    external_market_row = json.loads(
        (tmp_path / "workspace/runtime/data/external_venue_safe_inventory.jsonl")
        .read_text(encoding="utf-8")
    )
    assert external_market_row["venue"] == "binance"
    assert external_market_row["pnl_eligible"] is False
    assert external_market_row["replay_eligible"] is False
    assert external_market_row["loaded_payload_rows"] == 0
    assert result["nav_snapshot_observations"] == 1
    assert result["historical_snapshot_shards"] == 1
    assert result["historical_fill_observations"] == 1
    assert result["historical_unique_fills"] == 1
    assert result["historical_fills_train_only"] is True
    assert result["snapshots_forward_evidence_allowed"] is False
    assert result["source_recovery_root"] == str(recovery.resolve())
    assert result["active_data_index"] == str((tmp_path / "catalog" / "DATA_INDEX.json").resolve())
    assert result["workspace_root"] == str((tmp_path / "workspace").resolve())
    assert result["materialized_data_root"] == str((tmp_path / "workspace" / "runtime" / "data").resolve())
    fill = json.loads((tmp_path / "workspace/runtime/data/vault_fills.jsonl").read_text())
    assert fill["vault"] == "0xabc" and fill["signe"] == 1 and fill["source"] == "REST_BACKFILL"
    book = json.loads((tmp_path / "workspace/runtime/data/copy_vault_l2_tape.jsonl").read_text())
    assert book["causal_observation"] is True
    assert book["bid"] == 99.0 and book["ask"] == 101.0
    assert result["unexecutable_l2_observations"] == 0
    assert result["unclassified_fill_observations"] == 0
    assert set(result["materialized_tapes"]) == set(local_lab._MATERIALIZED_TAPE_NAMES)
    context_path = tmp_path / "workspace/runtime/data/copy_vault_context.jsonl"
    context_row = json.loads(context_path.read_text(encoding="utf-8"))
    assert context_row["family"] == "copy_vault_positions"
    assert context_row["observed_at_ms"] == 2_020
    assert context_row["event_ts_ms"] is None and context_row["exchange_ts_ms"] is None
    assert context_row["pnl_eligible"] is False
    assert context_row["raw_payload"] == context_payload
    nav_snapshot = json.loads(
        (tmp_path / "workspace/runtime/data/vault_snapshots.jsonl").read_text(encoding="utf-8")
    )
    assert nav_snapshot["vault"] == "0xabc"
    assert nav_snapshot["ts_ms"] == nav_snapshot["received_at_ms"] == 2_020
    assert nav_snapshot["nav_usd"] == 1_250.75
    assert nav_snapshot["pnl_eligible"] is False


def test_materialize_safe_workspace_rejects_unverified_asset(tmp_path: Path) -> None:
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    (recovery / "RESTORE_REPORT.json").write_text(json.dumps({
        "catalog_verification": {"profile": "replay-ready", "safe_catalog_shards": 1},
        "classification": {"missing_or_corrupt_rows": 0, "quarantined_shards": 0},
        "releases": [{"tag": "data-v2-campaign-copy-vault-x", "assets": [{
            "name": "bad.jsonl.gz", "size_bytes": 1, "sha256": "0" * 64,
            "status": "FAILED", "verification_status": "FAILED",
        }]}],
    }), encoding="utf-8")

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "UNMEASURABLE"
    assert result["verified_assets"] == 0


def test_websocket_snapshot_does_not_require_a_rest_backfill_receipt(
    tmp_path: Path, monkeypatch,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    tag = "copy-vault-ws-bootstrap"
    raw_payload = json.dumps({
        "channel": "userFills",
        "data": {"user": "0xabc", "isSnapshot": True, "fills": []},
    }, separators=(",", ":"))
    wrapper = {
        "channel": "copy_vault_snapshot", "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc", "received_ts_ms": 1_700_000_000_010,
        "provenance": {"access": "read_only", "authenticated": False, "transport": "websocket"},
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    shard = recovery / "usable" / "shards" / tag / "snapshot.jsonl.gz"
    size, sha = _write_gzip(shard, wrapper)
    audit = {
        "status": "SAFE_COMPLETE", "expected_safe_shards": 1,
        "missing_count": 0, "rejected_count": 0, "partial_rows_excluded": 0,
        "copy_vault_release_tags": [tag], "verified_safe_shards": 1,
    }
    monkeypatch.setattr(local_lab, "_verified_assets", lambda *_a, **_kw: (
        [(shard, {"family": "copy_vault_snapshot", "release_tag": tag, "bytes": size, "sha256": sha})],
        audit,
    ))

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["historical_coverage_audit"]["status"] == "NOT_APPLICABLE"
    assert result["historical_coverage_audit"]["expected_release_count"] == 0
    assert result["data_complete"] is False
    assert result["source_observations_by_family"] == {
        "copy_vault_snapshot:hyperliquid_public_userfills": 1,
    }


def test_materialize_distinguishes_verified_shards_from_rejected_payload_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    shard = recovery / "usable" / "shards" / "release" / "l2.jsonl.gz"
    raw_payload = json.dumps({"channel": "unexpected", "data": {}}, separators=(",", ":"))
    wrapper = {
        "read_only": True,
        "real_execution": False,
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
    }
    _write_gzip(shard, wrapper)
    audit = {
        "status": "SAFE_COMPLETE",
        "reason": None,
        "expected_safe_shards": 1,
        "missing_count": 0,
        "partial_rows_excluded": 0,
        "rejected_count": 0,
    }
    monkeypatch.setattr(
        local_lab,
        "_verified_assets",
        lambda _root, progress=None: ([(shard, {"family": "copy_vault_l2"})], audit),
    )

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "UNMEASURABLE"
    assert result["safe_catalog_status"] == "SAFE_COMPLETE"
    assert result["verified_assets"] == result["expected_safe_shards"] == 1
    assert result["missing_shards"] == 0
    assert result["reason"] == "SAFE_PAYLOAD_ROWS_REJECTED"
    assert result["payload_rejected_records"] == 1


def test_frozen_candidate_history_is_append_only_and_idempotent(tmp_path: Path) -> None:
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "status": "PROMISING",
        "selected_candidate": {"freeze": {"campaign_id": "candidate-1"}},
        "validation": {"daily_mean_net_pnl_usd": 2.5},
    }
    current = {"validation": {"daily_mean_net_pnl_usd": 1.0}}

    first = record_frozen_candidate(tmp_path, "run-1", economic, current)
    second = record_frozen_candidate(tmp_path, "run-1", economic, current)

    assert first == second
    history = load_improvement_history(tmp_path)
    assert len(history) == 1
    assert history[0]["candidate_daily_net_usd"] == 2.5
    assert history[0]["baseline_daily_net_usd"] == 1.0
    assert history[0]["improvement_usd_per_day"] == 1.5
    assert history[0]["classification"] == "CANDIDATE_FROZEN_IMPROVEMENT_MEASURED"
    immutable = tmp_path / "runtime/codex_research/copy_vault_improvements/entries/run-1.json"
    assert immutable.is_file()


def test_frozen_candidate_records_missing_restoration_snapshot_fields_fail_closed(
    tmp_path: Path,
) -> None:
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "status": "PROMISING",
        "selected_candidate": {"freeze": {"campaign_id": "candidate-1"}},
        "validation": {"daily_mean_net_pnl_usd": 2.5},
        "reproducibility_snapshot": {"code_sha": "a" * 40},
    }

    record = record_frozen_candidate(
        tmp_path,
        "run-incomplete-snapshot",
        economic,
        {"validation": {"daily_mean_net_pnl_usd": 1.0}},
    )

    assert record is not None
    snapshot = record["restoration_snapshot"]
    assert snapshot["complete"] is False
    assert "restore_receipt" in snapshot["missing_fields"]
    assert "ledger" in snapshot["missing_fields"]


def test_frozen_candidate_accepts_only_explicit_complete_restoration_snapshot(
    tmp_path: Path,
) -> None:
    required = {
        "code_sha": "a" * 40,
        "config_sha": "b" * 64,
        "data_manifest_sha256": "c" * 64,
        "seed": 17,
        "parameters": {"horizon_ms": 300_000},
        "windows": {"train": [1, 2], "oos": [3, 4]},
        "capital_usd": 200.0,
        "ledger": {"sha256": "d" * 64},
        "equity": {"sha256": "e" * 64},
        "costs": {"fees_usd": 1.0},
        "metrics": {"daily_mean_net_pnl_usd": 2.5},
        "trial_count": 3,
        "tests": {"passed": 4},
        "report": {"sha256": "f" * 64},
        "restore_receipt": {"sha256": "0" * 64},
    }
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "status": "PROMISING",
        "selected_candidate": {"freeze": {"campaign_id": "candidate-1"}},
        "validation": {"daily_mean_net_pnl_usd": 2.5},
        "reproducibility_snapshot": required,
    }

    record = record_frozen_candidate(
        tmp_path,
        "run-complete-snapshot",
        economic,
        {"validation": {"daily_mean_net_pnl_usd": 1.0}},
    )

    assert record is not None
    assert record["restoration_snapshot"]["complete"] is True
    assert record["restoration_snapshot"]["missing_fields"] == []


def test_historical_train_proxy_scales_to_200_usd_without_claiming_proof(tmp_path: Path) -> None:
    relative = "runtime/reports/train.json"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "paper_read_only": True,
        "real_execution": False,
        "selected": {
            "core_maximum_notional_usd": 600.0,
            "probe_notional_usd": 75.0,
            "daily_mean_net_pnl_usd": 6.75,
            "statistics": {
                "daily_mean_lcb_usd": 3.375,
                "sample_count": 8,
                "distinct_days": 4,
            },
        },
    }), encoding="utf-8")

    proxy = _historical_train_proxy(tmp_path, {"train_report": relative})

    assert proxy is not None
    assert proxy["daily_net_usd"] == 2.0
    assert proxy["conservative_lcb_usd_per_day"] == 1.0
    assert proxy["economically_proven"] is False


def test_historical_trade_replay_runs_deep_stress_matrix(tmp_path: Path) -> None:
    target = tmp_path / "runtime/reports/economic_campaigns/research_vnext/copy_vault_v21_entry_capacity_daily_lock_train.json"
    target.parent.mkdir(parents=True)
    trades = []
    for index in range(8):
        trades.append({
            "trade_id": f"t{index}", "exit_ts_ms": (index // 2 + 1) * 86_400_000,
            "net_pnl_usd": 1.0 + index, "gross_pnl_usd": 2.0 + index,
            "fees_usd": 0.2, "spread_cost_usd": 0.1,
            "slippage_cost_usd": 0.05, "latency_cost_usd": 0.05,
            "regime_reference_spread_bps": float(index + 1),
            "signed_reference_depth_imbalance": index / 10,
            "observed_latency_ms": 60_000 + index,
            "first_fill_leader_notional_usd": 100 + index,
            "entry_capacity_usd": 200 + index * 25,
            "liquidatable_net": True,
        })
    target.write_text(json.dumps({
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE", "heldout_evaluated": False,
        "paper_read_only": True, "real_execution": False,
        "selected": {
            "eligible": True, "core_maximum_notional_usd": 600.0,
            "probe_notional_usd": 75.0, "trades": trades,
            "statistics": {"sample_count": 8, "distinct_days": 4},
        },
    }), encoding="utf-8")

    result = run_historical_trade_replay(tmp_path, bootstrap_samples=100)

    assert result["status"] == "COMPLETED_EXPLORATORY"
    assert result["trial_count"] >= 10_000
    assert result["mechanism_count"] >= 5
    assert result["source_trade_count"] == 8
    assert result["baseline"]["daily_net_pnl_usd"] is not None
    assert result["economically_proven"] is False
