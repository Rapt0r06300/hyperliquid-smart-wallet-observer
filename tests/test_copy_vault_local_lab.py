from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from hl_observer.backtesting import copy_vault_local_lab as local_lab
from hl_observer.backtesting.copy_vault_local_lab import (
    _campaign_search_config,
    _campaign_trial_chain,
    _checkpoint_resume_state,
    _historical_train_proxy,
    _signal_coverage,
    _trial_with_receipt_chain,
    load_improvement_history,
    materialize_safe_workspace,
    record_frozen_candidate,
    run_historical_trade_replay,
)


def _bind_fixture_safe_asset(manifest: dict) -> dict:
    assets = [{
        "dataset_id": "fixture-safe-l2",
        "family": "copy_vault_l2",
        "release_tag": "fixture-release",
        "release_asset": "fixture-l2.jsonl.gz",
        "manifest_path": "catalog/manifests/fixture-safe-l2.json",
        "bytes": 1,
        "sha256": "c" * 64,
    }]
    manifest.update({
        "verified_source_assets": assets,
        "source_asset_inventory_count": len(assets),
        "source_asset_inventory_sha256": local_lab._source_asset_inventory_sha256(assets),
        "source_asset_inventory_complete": True,
    })
    manifest["selection_digest"] = local_lab._source_selection_digest(
        manifest["source_index_sha256"], assets,
    )
    return manifest


def test_campaign_trial_receipt_chain_detects_rewrite_and_reconciles_legacy_prefix() -> None:
    legacy = {
        "schema": "hypersmart.copy_vault_local_trial.v1",
        "selection_digest": "a" * 64,
        "sequence_index": 1,
        "trial_number": 1,
        "parameter_signature": "b" * 64,
        "parameters": {"stop_loss_bps": 40},
        "paper_read_only": True,
        "real_execution": False,
    }
    first_chain, prefixes = _campaign_trial_chain([legacy])
    assert first_chain == prefixes[0]

    second = _trial_with_receipt_chain({
        **legacy,
        "schema": "hypersmart.copy_vault_local_trial.v2",
        "sequence_index": 2,
        "trial_number": 2,
        "parameters": {"stop_loss_bps": 60},
        "parameter_signature": "c" * 64,
        "engine_source_sha256": "d" * 64,
        "campaign_config_sha256": "e" * 64,
    }, first_chain)
    final_chain, all_prefixes = _campaign_trial_chain([legacy, second])

    assert all_prefixes[0] == first_chain
    assert all_prefixes[1] == final_chain == second["trial_receipt_sha256"]
    tampered = [{**legacy}, {**second, "trial_number": 99}]
    with pytest.raises(ValueError, match="receipt chain"):
        _campaign_trial_chain(tampered)


def test_campaign_checkpoint_reconciles_durable_trials_and_invalidates_changed_config() -> None:
    selection = "a" * 64
    config, config_digest = _campaign_search_config(
        {"train_start_ms": 1, "train_end_ms": 2, "oos_start_ms": 3}
    )
    assert config["proposal_method"] == "HALTON_RADICAL_INVERSE_V1"
    assert config["proposal_seed"] == 0

    rows = []
    chain = "0" * 64
    attempts = []
    attempt_chain = "0" * 64
    for index in range(1, 3):
        parameters = {"stop_loss_bps": index * 20}
        attempt = local_lab._attempt_with_receipt_chain({
            "schema": "hypersmart.copy_vault_local_attempt.v1",
            "selection_digest": selection,
            "source_catalog_sha256": "b" * 64,
            "source_asset_inventory_sha256": "c" * 64,
            "engine_source_sha256": "f" * 64,
            "campaign_config_sha256": config_digest,
            "proposal_method": "HALTON_RADICAL_INVERSE_V1",
            "proposal_seed": 0,
            "temporal_windows": {"train_start_ms": 1},
            "sequence_index": index,
            "trial_number": index,
            "parameter_signature": str(index) * 64,
            "parameters": parameters,
            "paper_read_only": True,
            "real_execution": False,
        }, attempt_chain)
        attempt_chain = attempt["attempt_receipt_sha256"]
        attempts.append(attempt)
        row = {
            "schema": "hypersmart.copy_vault_local_trial.v2",
            "selection_digest": selection,
            "attempt_receipt_sha256": attempt["attempt_receipt_sha256"],
            "sequence_index": index,
            "trial_number": index,
            "parameter_signature": str(index) * 64,
            "parameters": parameters,
            "engine_source_sha256": "f" * 64,
            "campaign_config_sha256": config_digest,
            "paper_read_only": True,
            "real_execution": False,
        }
        row = _trial_with_receipt_chain(row, chain)
        chain = row["trial_receipt_sha256"]
        rows.append(row)

    checkpoint = {
        "schema": "hypersmart.copy_vault_search_checkpoint.v2",
        "selection_digest": selection,
        "source_catalog_sha256": "b" * 64,
        "source_asset_inventory_sha256": "c" * 64,
        "engine_source_sha256": "f" * 64,
        "campaign_config_sha256": "0" * 64,
        "campaign_trials": 1,
        "campaign_attempts": 1,
        "attempt_receipt_count": 1,
        "next_sequence_index": 2,
        "trial_receipt_chain_sha256": rows[0]["trial_receipt_sha256"],
        "attempt_receipt_chain_sha256": attempts[0]["attempt_receipt_sha256"],
    }
    state = _checkpoint_resume_state(
        checkpoint,
        rows,
        attempts=attempts,
        selection_digest=selection,
        source_catalog_sha256="b" * 64,
        source_asset_inventory_sha256="c" * 64,
        engine_source_sha256="f" * 64,
        campaign_config_sha256=config_digest,
    )

    assert state["campaign_trials"] == 2
    assert state["next_sequence_index"] == 3
    assert state["ledger_reconciled"] is True
    assert state["engine_changed"] is False
    assert state["config_changed"] is True

    checkpoint["campaign_trials"] = 3
    with pytest.raises(ValueError, match="checkpoint is ahead"):
        _checkpoint_resume_state(
            checkpoint,
            rows,
            attempts=attempts,
            selection_digest=selection,
            source_catalog_sha256="b" * 64,
            source_asset_inventory_sha256="c" * 64,
            engine_source_sha256="f" * 64,
            campaign_config_sha256=config_digest,
        )


def test_local_campaign_resume_preserves_reserved_attempt_without_reusing_candidate_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in local_lab._MATERIALIZED_TAPE_NAMES:
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = _bind_fixture_safe_asset({
        "paper_read_only": True,
        "real_execution": False,
        "source_index_sha256": "b" * 64,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 10,
        "unique_books": 10,
        "data_complete": True,
        "materialized_tapes": tape_manifest,
    })
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    signal_times = [
        (10 + day) * 86_400_000 + 60_000 for day in range(10)
    ]
    metaorders = [
        {"signal_ts_ms": timestamp, "action": "ADD", "coin": "BTC"}
        for timestamp in signal_times
    ]
    books = {
        "BTC": [{"ts_ms": timestamp - 1_000} for timestamp in signal_times]
    }

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace):
            return [], {
                "live_fill_rows": 10,
                "causal_live_fill_rows": 10,
                "historical_fill_rows": 0,
            }

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(
        local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {})
    )
    monkeypatch.setattr(
        local_lab.cv, "load_observed_books", lambda *_args, **_kwargs: (books, {})
    )
    ledger = repository_root / "runtime" / "codex_research" / "HYPOTHESIS_LEDGER.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("", encoding="utf-8")
    freeze_path = (
        repository_root / "runtime" / "codex_research"
        / "COPY_V21_PHYSICAL_FREEZE.json"
    )
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_path.write_text(json.dumps({"freeze": {"parameters": {
        "core_notional_usd": 50,
        "probe_notional_usd": 10,
        "daily_profit_lock_usd": 5,
    }}}), encoding="utf-8")

    calls = {"count": 0, "interrupt_trial_once": True}
    evaluated_segments = []
    evaluated_input_counts = []

    def evaluate(_metaorders, _books, _freeze, *, segment):
        evaluated_segments.append(segment)
        evaluated_input_counts.append(len(_metaorders))
        calls["count"] += 1
        if calls["count"] == 2 and calls["interrupt_trial_once"]:
            raise KeyboardInterrupt
        return {
            "eligible": False,
            "reasons": ["fixture only"],
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

    monkeypatch.setattr(local_lab, "evaluate_frozen_v21_segment", evaluate)

    interrupted = local_lab.run_local_campaign(
        workspace, repository_root=repository_root, max_trials=1,
    )
    assert interrupted["status"] == "INTERRUPTED"
    campaign_root = (
        repository_root / "runtime" / "codex_research"
        / "copy_vault_continuous_lab" / manifest["selection_digest"]
    )
    attempts_path = campaign_root / "ATTEMPTS.jsonl"
    checkpoint_path = campaign_root / "CHECKPOINT.json"
    attempts_after_interrupt = local_lab._load_campaign_attempts(
        attempts_path, manifest["selection_digest"]
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(attempts_after_interrupt) == 1
    assert checkpoint["campaign_trials"] == 0
    assert checkpoint["campaign_attempts"] == 1
    assert checkpoint["next_sequence_index"] == 2

    calls["interrupt_trial_once"] = False
    updates = []

    def stop_continuous_search_after_two_trials(update):
        updates.append(update)
        if len(updates) == 2:
            raise KeyboardInterrupt

    resumed = local_lab.run_local_campaign(
        workspace,
        repository_root=repository_root,
        continuous=True,
        on_update=stop_continuous_search_after_two_trials,
    )
    assert resumed["status"] == "INTERRUPTED"
    assert resumed["candidates_tested"] == 2
    assert resumed["campaign_attempts"] == 3
    assert resumed["freeze_created"] is False
    assert [update["campaign_attempts"] for update in updates] == [2, 3]
    assert all(update["last_attempt_receipt_sha256"] for update in updates)
    trials = local_lab._load_campaign_trials(
        campaign_root / "TRIALS.jsonl", manifest["selection_digest"]
    )
    attempts = local_lab._load_campaign_attempts(
        attempts_path, manifest["selection_digest"]
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(trials) == 2
    assert len(attempts) == 3
    assert [row["sequence_index"] for row in trials] == [2, 3]
    assert [row["sequence_index"] for row in attempts] == [1, 2, 3]
    assert [row["trial_number"] for row in trials] == [2, 3]
    assert [
        row["attempt_receipt_sha256"] for row in trials
    ] == [row["attempt_receipt_sha256"] for row in attempts[1:]]
    assert all(
        row["source_catalog_sha256"] == manifest["source_index_sha256"]
        and row["source_asset_inventory_sha256"]
        == manifest["source_asset_inventory_sha256"]
        and len(row["engine_source_sha256"]) == 64
        and len(row["campaign_config_sha256"]) == 64
        and row["proposal_method"] == "HALTON_RADICAL_INVERSE_V1"
        and row["proposal_seed"] == 0
        and row["temporal_windows"]["train_start_ms"]
        < row["temporal_windows"]["train_end_ms"]
        for row in attempts
    )
    assert all(
        trial["source_catalog_sha256"] == attempt["source_catalog_sha256"]
        and trial["source_asset_inventory_sha256"]
        == attempt["source_asset_inventory_sha256"]
        and trial["engine_source_sha256"] == attempt["engine_source_sha256"]
        and trial["campaign_config_sha256"] == attempt["campaign_config_sha256"]
        and trial["proposal_seed"] == attempt["proposal_seed"]
        and trial["temporal_windows"] == attempt["temporal_windows"]
        for trial, attempt in zip(trials, attempts[1:], strict=True)
    )
    assert checkpoint["campaign_trials"] == 2
    assert checkpoint["campaign_attempts"] == 3
    assert evaluated_segments and set(evaluated_segments) == {"train"}
    assert evaluated_input_counts
    assert set(evaluated_input_counts) == {len(metaorders)}


def test_market_context_materializer_rechecks_clock_identity_and_read_only_source() -> None:
    now_ms = 2_000
    common = {
        "source_id": "hyperliquid_public_copy_vault_market_ws",
        "instrument": "xyz:TSLA",
        "received_ts_ms": now_ms + 2,
        "local_monotonic_ns": 12,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "websocket",
        },
    }
    wrappers = [
        (
            "copy_vault_bbo",
            {
                **common, "exchange_ts_ms": now_ms,
                "_raw": {"channel": "bbo", "data": {
                    "coin": "xyz:TSLA", "time": now_ms,
                    "bbo": [{"px": "10", "sz": "2"}, {"px": "11", "sz": "3"}],
                }},
            },
        ),
        (
            "copy_vault_trades",
            {
                **common, "exchange_ts_ms": now_ms,
                "_raw": {"channel": "trades", "data": [{
                    "coin": "xyz:TSLA", "time": now_ms, "px": "10.5", "sz": "1",
                    "side": "B", "hash": "0xt", "tid": 3,
                }]},
            },
        ),
        (
            "copy_vault_active_asset_ctx",
            {
                **common, "exchange_ts_ms": None,
                "provenance": {
                    **common["provenance"],
                    "timestamp_semantics": "receive_observation_time_only",
                },
                "_raw": {"channel": "activeAssetCtx", "data": {
                    "coin": "xyz:TSLA", "ctx": {"markPx": "10.5"},
                }},
            },
        ),
    ]
    audit: Counter[str] = Counter()

    rows = [
        local_lab._market_context_row(wrapper, family=family, audit=audit)
        for family, wrapper in wrappers
    ]

    assert [row["schema_version"] for row in rows if row] == [
        "hypersmart.copy_vault_bbo.v1",
        "hypersmart.copy_vault_market_trade.v1",
        "hypersmart.copy_vault_active_asset_ctx.v1",
    ]
    assert all(row["proof_of_pnl_allowed"] is False for row in rows if row)
    assert rows[1]["coin"] == "xyz:TSLA" and rows[1]["aggressor_side"] == "B"
    assert not audit

    malformed = {
        **wrappers[1][1],
        "_raw": {"channel": "trades", "data": [{
            "coin": "OTHER", "time": now_ms, "px": "10.5", "sz": "1",
            "side": "B", "hash": "0xt", "tid": 3,
        }]},
    }
    assert local_lab._market_context_row(
        malformed, family="copy_vault_trades", audit=audit
    ) is None


def test_accounting_context_tapes_are_causal_but_never_follower_pnl() -> None:
    vault = "0x" + "c" * 40
    common = {
        "instrument": vault,
        "received_ts_ms": 3_002,
        "local_monotonic_ns": 123,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "websocket", "forward_evidence_allowed": False,
        },
    }
    funding = {
        **common,
        "source_id": "hl_public_account",
        "exchange_ts_ms": 3_000,
        "_raw": {"channel": "userFundings", "data": {
            "user": vault, "isSnapshot": False,
            "fundings": [{
                "time": 3_000, "coin": "kPEPE", "usdc": "-0.2",
                "szi": "3", "fundingRate": "0.0001",
            }],
        }},
    }
    ledger = {
        **common,
        "source_id": "hl_public_account",
        "exchange_ts_ms": 3_001,
        "_raw": {"channel": "userNonFundingLedgerUpdates", "data": {
            "user": vault, "isSnapshot": False,
            "nonFundingLedgerUpdates": [{
                "time": 3_001, "hash": "0xledger",
                "delta": {"type": "deposit", "usdc": 10},
            }],
        }},
    }
    audit: Counter[str] = Counter()

    funding_row = local_lab._accounting_context_row(
        funding, family="copy_vault_funding", audit=audit
    )
    ledger_row = local_lab._accounting_context_row(
        ledger, family="copy_vault_ledger", audit=audit
    )

    assert funding_row is not None and funding_row["coin"] == "kPEPE"
    assert ledger_row is not None and ledger_row["delta_type"] == "deposit"
    assert funding_row["proof_of_pnl_allowed"] is False
    assert ledger_row["forward_evidence_allowed"] is False
    assert not audit

    rest_funding = {
        **common,
        "source_id": "hl_public_account_backfill",
        "exchange_ts_ms": 3_000,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "https", "historical_only": True,
            "request_type": "userFunding", "forward_evidence_allowed": False,
        },
        "_raw": {"channel": "userFundings", "data": {
            "user": vault, "isSnapshot": False,
            "fundings": [{
                "time": 3_000, "hash": "0xfunding",
                "delta": {
                    "coin": "kPEPE", "usdc": "-0.2", "szi": "3",
                    "fundingRate": "0.0001", "type": "funding",
                },
            }],
        }},
    }
    rest_row = local_lab._accounting_context_row(
        rest_funding, family="copy_vault_funding", audit=audit
    )
    assert rest_row is not None
    assert rest_row["historical_only"] is True
    assert rest_row["hash"] == "0xfunding"
    assert rest_row["usdc"] == -0.2
    assert rest_row["proof_of_pnl_allowed"] is False
    assert not audit


def _write_gzip(path: Path, row: dict) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "bids,asks",
    [
        ([{"px": "99", "sz": "1"}, {"px": "100", "sz": "2"}],
         [{"px": "101", "sz": "1"}]),
        ([{"px": "100", "sz": "1"}],
         [{"px": "101", "sz": "1"}, {"px": "101", "sz": "2"}]),
    ],
)
def test_materializer_rejette_les_niveaux_l2_invalides_sans_les_trier(bids, asks) -> None:
    wrapper = {
        "received_ts_ms": 2_010,
        "raw_sha256": "a" * 64,
        "_raw": {
            "channel": "l2Book",
            "data": {"coin": "BTC", "time": 2_000, "levels": [bids, asks]},
        },
    }

    assert local_lab._book_row(wrapper) is None


@pytest.mark.parametrize("coin", ["kPEPE", "xyz:TSLA"])
def test_safe_parser_preserves_case_sensitive_native_instrument_identity(coin: str) -> None:
    levels = [[{"px": "0.0001", "sz": "1000"}], [{"px": "0.0002", "sz": "1000"}]]
    book = local_lab._book_row({
        "received_ts_ms": 2_010,
        "raw_sha256": "a" * 64,
        "_raw": {
            "channel": "l2Book",
            "data": {"coin": coin, "time": 2_000, "levels": levels},
        },
    })
    fill_wrapper = {
        "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc",
        "received_ts_ms": 1_010,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "websocket",
        },
        "_raw": {
            "channel": "userFills",
            "data": {
                "user": "0xabc", "isSnapshot": False,
                "fills": [{
                    "time": 1_000, "coin": coin, "px": "0.00015",
                    "sz": "1", "side": "B", "fee": "0",
                    "hash": "0xfill", "tid": 7,
                }],
            },
        },
    }

    fills = local_lab._fill_rows(
        fill_wrapper,
        family="copy_vault_fills",
        source_dataset_id="dataset-live-1",
        source_shard_sha256="a" * 64,
    )

    assert book is not None and book["coin"] == coin
    assert fills and fills[0]["coin"] == coin
    assert fills[0]["source_dataset_id"] == "dataset-live-1"
    assert fills[0]["source_shard_sha256"] == "a" * 64


def test_fill_normalizer_rejects_incomplete_verified_shard_identity() -> None:
    wrapper = {
        "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc",
        "received_ts_ms": 1_010,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "websocket",
        },
        "_raw": {
            "channel": "userFills",
            "data": {
                "user": "0xabc", "isSnapshot": False,
                "fills": [{
                    "time": 1_000, "coin": "BTC", "px": "100", "sz": "1",
                    "side": "B", "fee": "0", "hash": "0xfill", "tid": 7,
                }],
            },
        },
    }
    audit: Counter[str] = Counter()

    rows = local_lab._fill_rows(
        wrapper,
        family="copy_vault_fills",
        audit=audit,
        source_dataset_id="dataset-live-1",
        source_shard_sha256="bad-sha",
    )

    assert rows == []
    assert audit["SAFE_SOURCE_SHARD_PROVENANCE_INVALID"] == 1


@pytest.mark.parametrize(
    ("fill_changes", "expected_rejection"),
    [
        ({"hash": None, "tid": None}, "FILL_NATIVE_ID_MISSING"),
        ({"px": "0"}, "FILL_EXECUTION_VALUE_INVALID"),
        ({"sz": "-1"}, "FILL_EXECUTION_VALUE_INVALID"),
        ({"time": True}, "FILL_CAUSAL_TIMESTAMP_INVALID"),
    ],
)
def test_fill_normalizer_rejects_missing_identity_or_invalid_causal_trade_fields(
    fill_changes: dict, expected_rejection: str,
) -> None:
    fill = {
        "time": 1_000, "coin": "BTC", "px": "100", "sz": "2",
        "side": "B", "fee": "0.1", "hash": "0xfill", "tid": 7,
        **fill_changes,
    }
    wrapper = {
        "source_id": "hyperliquid_public_userfills",
        "instrument": "0xabc", "received_ts_ms": 1_010,
        "provenance": {
            "access": "read_only", "authenticated": False,
            "transport": "websocket",
        },
        "_raw": {
            "channel": "userFills",
            "data": {"user": "0xabc", "isSnapshot": False, "fills": [fill]},
        },
    }
    audit: Counter[str] = Counter()

    rows = local_lab._fill_rows(wrapper, family="copy_vault_fills", audit=audit)

    assert rows == []
    assert audit[expected_rejection] == 1


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


def test_local_campaign_explains_insufficient_signal_days_before_search(
    tmp_path: Path, monkeypatch,
) -> None:
    from hl_observer.backtesting import copy_vault_v9_online_leader_quality_train as v9

    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tape_manifest = {}
    for name in local_lab._MATERIALIZED_TAPE_NAMES:
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = _bind_fixture_safe_asset({
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
    })
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

        @staticmethod
        def charger_evenements_lifecycle_avec_audit(_workspace):
            return [], {}

    analyzer_calls = []
    ledger_calls = []

    def fake_analyzer(metaorders, observed_books, lifecycle_events, *, input_audit):
        analyzer_calls.append((metaorders, observed_books, lifecycle_events, input_audit))
        return {
            "schema_version": v9.SCHEMA_VERSION,
            "status": "MORE_DATA",
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "selection_eligible": False,
            "leader_decision_traces": {
                "schema_version": "copy_vault.leader_quality_decision_trace.v1",
                "scope": "TRAIN_ONLY_PRE_FREEZE",
                "traces": [{
                    "minimum_prior_closed": 1,
                    "history_window": 4,
                    "candidate_decision_count": 1,
                    "decisions": [{
                        "candidate_trade_id": "candidate-1",
                        "leader_id": "leader-1",
                        "as_of_ms": signal_times[0],
                        "outcome": "REJECTED",
                        "reason": "INSUFFICIENT_PRIOR_CLOSED_HISTORY",
                        "prior_count": 0,
                        "prior_mean_net_pnl_usd": None,
                        "evidence_refs": [],
                        "evidence_status": "INCOMPLETE_OR_UNVERIFIED",
                    }],
                }],
            },
        }

    def fake_append(path, analysis, **kwargs):
        ledger_calls.append((path, analysis, kwargs))
        return {
            "status": "PERSISTED", "decision_count": 1,
            "reviewable_count": 0, "unmeasurable_count": 1,
            "consultative_only": True, "can_change_decision": False,
        }

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _entries: (metaorders, {}))
    monkeypatch.setattr(
        local_lab.cv,
        "load_observed_books",
        lambda *_args, **_kwargs: (books, {}),
    )
    monkeypatch.setattr(
        local_lab.cv, "select_causal_protocol_inputs",
        lambda orders, book_rows: (orders, book_rows, {"status": "FIXTURE"}),
    )
    monkeypatch.setattr(v9, "explore_copy_vault_v9_online_leader_quality_train", fake_analyzer)
    monkeypatch.setattr(
        "hl_observer.research.leader_review_ledger.append_copy_vault_v9_leader_reviews",
        fake_append,
    )

    review_path = tmp_path / "runtime" / "reports" / "copy_vault" / "leader_reviews.jsonl"
    result = local_lab.run_local_campaign(
        workspace, leader_review_ledger_path=review_path,
    )

    assert len(analyzer_calls) == 1
    assert analyzer_calls[0][2] == []
    assert len(ledger_calls) == 1
    assert ledger_calls[0][0] == review_path
    assert ledger_calls[0][2]["safe_inventory"] == manifest
    assert result["leader_quality_v9_train"]["decision_count"] == 1
    assert result["leader_review_persistence"]["status"] == "PERSISTED"
    assert result["leader_review_persistence"]["can_change_decision"] is False
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
    for name in local_lab._MATERIALIZED_TAPE_NAMES:
        payload = b"{}\n"
        (data_dir / name).write_bytes(payload)
        tape_manifest[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = _bind_fixture_safe_asset({
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
    })
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
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


def test_local_campaign_fails_closed_when_safe_asset_inventory_digest_is_tampered(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _bind_fixture_safe_asset({
        "paper_read_only": True,
        "real_execution": False,
        "source_index_sha256": "b" * 64,
        "status": "READY",
        "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True,
        "unique_fills": 1,
        "unique_books": 1,
    })
    manifest["source_asset_inventory_sha256"] = "d" * 64
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )

    result = local_lab.run_local_campaign(workspace)

    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "SAFE_SOURCE_ASSET_INVENTORY_DIGEST_MISMATCH"
    assert result["candidates_tested"] == 0
    assert result["freeze_created"] is False


def test_current_policy_evaluation_rejects_unbound_safe_asset_inventory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _bind_fixture_safe_asset({"source_index_sha256": "b" * 64})
    manifest["selection_digest"] = "e" * 64
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8",
    )
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text("{}", encoding="utf-8")

    result = local_lab.evaluate_current_copy_vault(workspace, freeze_path)

    assert result["status"] == "UNMEASURABLE"
    assert result["reason"] == "SAFE_SELECTION_DIGEST_DOES_NOT_BIND_SOURCE_INVENTORY"
    assert result["economically_proven"] is False


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
        "instrument": "BTC", "exchange_ts_ms": 2_000, "received_ts_ms": 2_010,
        "connection_id": "copy-l2-test", "reconnect_count": 0, "gap_count": 0,
        "parsed_summary": {"l2_gap_epoch": 0},
        "raw_payload": l2_payload,
        "raw_sha256": hashlib.sha256(l2_payload.encode()).hexdigest(),
        "read_only": True, "real_execution": False,
    }
    fill_name = "hyperliquid-public-userfills-copy-vault-snapshot-test.jsonl.gz"
    l2_name = "hyperliquid-public-copy-l2-copy-vault-l2-btc-test.jsonl.gz"
    fill_size, fill_sha = _write_gzip(recovery / "usable" / "shards" / tag / fill_name, fill_wrapper)
    l2_size, l2_sha = _write_gzip(recovery / "usable" / "shards" / tag / l2_name, l2_wrapper)
    index_rows = []
    for dataset_id, family, asset_name, size, sha in (
        ("cv-fill-test", "copy_vault_snapshot", fill_name, fill_size, fill_sha),
        ("cv-l2-test", "copy_vault_l2", l2_name, l2_size, l2_sha),
    ):
        manifest_path = f"datasets/sharded/safe/aa/bb/{dataset_id}.manifest.json"
        manifest = {
            "schema": "alina.shard_manifest.v2", "quality_status": "SAFE",
            "replay_compatible": True, "asset_verified": True,
            "validation_allowed": True,
            "proof_of_pnl_allowed": False, "dataset_id": dataset_id,
            "family": family, "release_tag": tag, "release_asset": asset_name,
            "bytes": size, "sha256": sha,
            "event_count": 1, "record_count": 1,
            "integrity": {
                "gap_count": 0, "regression_count": 0, "desync_count": 0,
                "duplicate_count": 0, "missing_timestamp_count": 0,
                "missing_monotonic_count": 0,
            },
            "start_ts_ms": 2_010 if family == "copy_vault_l2" else 1_010,
            "end_ts_ms": 2_010 if family == "copy_vault_l2" else 1_010,
            "provenance": {
                "transports": [
                    "https" if family == "copy_vault_snapshot" else "websocket"
                ]
            },
            **({
                "synchronization": {
                    "connection_ids": ["copy-l2-test"],
                    "connection_count": 1,
                    "reconnect_delta": 0,
                    # This is the collector's cumulative counter baseline,
                    # not evidence that this shard crossed a reconnect.
                    "max_reconnect_count": 6,
                    "receive_minus_exchange_ms": {"count": 1},
                    "heartbeat": {
                        "connection_id": "copy-l2-test",
                        "sent_count": 1,
                        "received_count": 1,
                        "unmatched_pong_count": 0,
                        "first_received_at_ms": 2_010,
                        "last_received_at_ms": 2_010,
                    },
                }
            } if family == "copy_vault_l2" else {}),
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
            "replay_compatible": True, "validation_allowed": True,
            "release_tag": tag,
            "release_asset": asset_name, "manifest_path": manifest_path,
            "bytes": size, "sha256": sha,
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
    assert result["historical_snapshot_shards"] == 1
    assert result["historical_fill_observations"] == 1
    assert result["historical_unique_fills"] == 1
    assert result["historical_fills_train_only"] is True
    assert result["snapshots_forward_evidence_allowed"] is False
    assert result["source_asset_inventory_count"] == 2
    assert result["source_asset_inventory_complete"] is True
    assert len(result["source_asset_inventory_sha256"]) == 64
    fill = json.loads((tmp_path / "workspace/runtime/data/vault_fills.jsonl").read_text())
    assert fill["vault"] == "0xabc" and fill["signe"] == 1 and fill["source"] == "REST_BACKFILL"
    book = json.loads((tmp_path / "workspace/runtime/data/copy_vault_l2_tape.jsonl").read_text())
    assert book["causal_observation"] is True
    assert book["bid"] == 99.0 and book["ask"] == 101.0
    assert book["source_dataset_id"] == "cv-l2-test"
    assert book["source_shard_sha256"] == l2_sha
    assert book["source_raw_sha256"] == hashlib.sha256(l2_payload.encode()).hexdigest()
    assert book["source_catalog_sha256"] == result["source_index_sha256"]
    assert book["source_quality_status"] == "SAFE"
    assert book["source_manifest_verified"] is True
    assert book["source_replay_compatible"] is True
    assert book["connection_id"] == "copy-l2-test"
    assert book["l2_gap_epoch"] == 0
    assert book["source_continuity_proven"] is True
    assert fill["source_catalog_sha256"] == result["source_index_sha256"]
    assert fill["source_quality_status"] == "SAFE"
    assert fill["source_manifest_verified"] is True
    assert fill["source_replay_compatible"] is True

    catalog_file = tmp_path / "catalog" / "DATA_INDEX.json"
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    manifest_file = tmp_path / index_rows[0]["manifest_path"]
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    catalog["shards"][0].pop("validation_allowed")
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    selected, catalog_fallback_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 2
    assert catalog_fallback_audit["rejected_count"] == 0
    assert catalog_fallback_audit["catalog_validation_allowed_manifest_fallbacks"] == 1

    catalog["shards"][0]["validation_allowed"] = False
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    selected, explicit_catalog_denial = local_lab._verified_assets(recovery)
    assert len(selected) == 1
    assert explicit_catalog_denial["rejected_count"] == 1
    assert any(
        "CATALOG_VALIDATION_NOT_ALLOWED" in item["reason"]
        for item in explicit_catalog_denial["rejected_sample"]
    )

    catalog["shards"][0]["validation_allowed"] = True
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    manifest.pop("validation_allowed")
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    selected, rejected_manifest_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 1
    assert rejected_manifest_audit["rejected_count"] == 1
    assert any(
        "SAFE_MANIFEST_VALIDATION_NOT_ALLOWED" in item["reason"]
        for item in rejected_manifest_audit["rejected_sample"]
    )

    catalog["shards"][0]["validation_allowed"] = True
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    manifest["validation_allowed"] = True
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    l2_manifest_file = tmp_path / index_rows[1]["manifest_path"]
    l2_manifest = json.loads(l2_manifest_file.read_text(encoding="utf-8"))
    l2_manifest["synchronization"]["heartbeat"]["received_count"] = 0
    l2_manifest_file.write_text(json.dumps(l2_manifest), encoding="utf-8")
    selected, missing_reply_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 1
    assert missing_reply_audit["rejected_count"] == 1
    assert any(
        "SAFE_MANIFEST_HEARTBEAT_REPLY_MISSING" in item["reason"]
        for item in missing_reply_audit["rejected_sample"]
    )
    l2_manifest["synchronization"]["heartbeat"]["received_count"] = 1
    l2_manifest["synchronization"].pop("heartbeat")
    l2_manifest_file.write_text(json.dumps(l2_manifest), encoding="utf-8")
    selected, rejected_heartbeat_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 2
    assert rejected_heartbeat_audit["rejected_count"] == 0
    assert rejected_heartbeat_audit["heartbeat_evidence_missing_dataset_ids"] == ["cv-l2-test"]

    incomplete_workspace = tmp_path / "workspace-no-heartbeat"
    incomplete = materialize_safe_workspace(recovery, incomplete_workspace)
    assert incomplete["status"] == "MORE_DATA"
    assert incomplete["data_complete"] is False
    assert incomplete["continuity_evidence_status"] == "UNPROVEN"
    assert incomplete["continuity_evidence_missing_shards"] == 1
    incomplete_book = json.loads(
        (incomplete_workspace / "runtime" / "data" / "copy_vault_l2_tape.jsonl")
        .read_text(encoding="utf-8")
    )
    assert incomplete_book["connection_id"] == "copy-l2-test"
    assert incomplete_book["l2_gap_epoch"] == 0
    assert incomplete_book["source_continuity_proven"] is False

    l2_manifest["integrity"]["gap_count"] = 1
    l2_manifest_file.write_text(json.dumps(l2_manifest), encoding="utf-8")
    selected, gap_rejected_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 1
    assert gap_rejected_audit["rejected_count"] == 1
    assert any(
        "HISTORICAL_EXPLORATORY_HEARTBEAT_FALLBACK_INTEGRITY_UNPROVEN" in item["reason"]
        for item in gap_rejected_audit["rejected_sample"]
    )
    l2_manifest["integrity"]["gap_count"] = 0
    l2_manifest["synchronization"]["reconnect_delta"] = 1
    l2_manifest_file.write_text(json.dumps(l2_manifest), encoding="utf-8")
    selected, reconnect_rejected_audit = local_lab._verified_assets(recovery)
    assert len(selected) == 1
    assert reconnect_rejected_audit["rejected_count"] == 1
    assert any(
        "HISTORICAL_EXPLORATORY_HEARTBEAT_FALLBACK_INTEGRITY_UNPROVEN" in item["reason"]
        for item in reconnect_rejected_audit["rejected_sample"]
    )

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


def test_materialize_quarantines_un_l2_safe_mal_ordonne(tmp_path: Path, monkeypatch) -> None:
    recovery = tmp_path / "runtime" / "recovery" / "full"
    shard = recovery / "usable" / "shards" / "release" / "l2.jsonl.gz"
    raw_payload = json.dumps({
        "channel": "l2Book",
        "data": {
            "coin": "BTC", "time": 2_000,
            "levels": [
                [{"px": "99", "sz": "1"}, {"px": "100", "sz": "2"}],
                [{"px": "101", "sz": "1"}],
            ],
        },
    }, separators=(",", ":"))
    wrapper = {
        "read_only": True,
        "real_execution": False,
        "received_ts_ms": 2_010,
        "raw_payload": raw_payload,
        "raw_sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
    }
    _write_gzip(shard, wrapper)
    audit = {
        "status": "SAFE_COMPLETE", "reason": None,
        "expected_safe_shards": 1, "missing_count": 0,
        "partial_rows_excluded": 0, "rejected_count": 0,
    }
    monkeypatch.setattr(
        local_lab, "_verified_assets",
        lambda _root, progress=None: ([(shard, {"family": "copy_vault_l2"})], audit),
    )

    result = materialize_safe_workspace(recovery, tmp_path / "workspace")

    assert result["status"] == "UNMEASURABLE"
    assert result["payload_audit"]["INVALID_OR_NONCAUSAL_L2_REJECTED"] == 1
    assert result["unique_books"] == 0
    assert (tmp_path / "workspace/runtime/data/copy_vault_l2_tape.jsonl").read_text() == ""


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


def test_improvement_history_rejects_malformed_rows_instead_of_hiding_them(tmp_path: Path) -> None:
    ledger = tmp_path / "runtime/codex_research/copy_vault_improvements/HISTORY.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        '{"schema_version":"hypersmart.copy_vault_local_improvement.v1","run_id":"legacy-1"}\n'
        "{bad json}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="HISTORY_JSON_INVALID line 2"):
        load_improvement_history(tmp_path)


def test_improvement_history_chains_new_receipts_and_preserves_legacy_prefix(tmp_path: Path) -> None:
    registry = tmp_path / "runtime/codex_research/copy_vault_improvements"
    registry.mkdir(parents=True)
    legacy = {
        "schema_version": "hypersmart.copy_vault_local_improvement.v1",
        "run_id": "legacy-run",
        "classification": "CANDIDATE_FROZEN_NO_IMPROVEMENT",
    }
    ledger = registry / "HISTORY.jsonl"
    ledger.write_text(json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8")
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "status": "PROMISING",
        "selected_candidate": {"freeze": {"campaign_id": "candidate-2"}},
        "validation": {"daily_mean_net_pnl_usd": 2.5},
        "engine_source_sha256": "a" * 64,
        "campaign_config_sha256": "b" * 64,
        "source_asset_inventory_sha256": "c" * 64,
        "proposal_method": "HALTON_RADICAL_INVERSE_V1",
        "proposal_seed": 0,
        "temporal_windows": {"train_start_ms": 10, "train_end_ms": 20},
        "attempt_receipt_sha256": "d" * 64,
    }

    saved = record_frozen_candidate(
        tmp_path, "run-2", economic, {"validation": {"daily_mean_net_pnl_usd": 1.0}}
    )

    history = load_improvement_history(tmp_path)
    assert len(history) == 2
    assert history[0] == legacy
    assert saved["schema_version"] == "hypersmart.copy_vault_local_improvement.v2"
    assert saved["previous_receipt_sha256"] == local_lab._canonical_json_sha256(legacy)
    assert len(saved["receipt_sha256"]) == 64
    assert saved["engine_source_sha256"] == "a" * 64
    assert saved["campaign_config_sha256"] == "b" * 64
    assert saved["source_asset_inventory_sha256"] == "c" * 64
    assert saved["attempt_receipt_sha256"] == "d" * 64

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[1]["classification"] = "TAMPERED"
    ledger.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COPY_VAULT_IMPROVEMENT_HISTORY_RECEIPT_HASH_MISMATCH line 2"):
        load_improvement_history(tmp_path)


def test_champion_requires_full_proof_and_never_downgrades(tmp_path: Path) -> None:
    def candidate(run_id: str, daily_net: float, *, complete_proof: bool = True) -> dict:
        result = {
            "freeze_created": True,
            "economically_proven": True,
            "status": "PROVEN",
            "heldout_evaluated": True,
            "paper_read_only": True,
            "real_execution": False,
            "data_complete": True,
            "paper_capital_usd": 200.0,
            "selected_candidate": {"freeze": {"campaign_id": run_id}},
            "validation": {"daily_mean_net_pnl_usd": daily_net},
            "oos": {"daily_mean_net_pnl_usd": daily_net},
            "forward": {"daily_mean_net_pnl_usd": daily_net},
        }
        for segment in ("validation", "oos", "forward"):
            result[segment].update({
                "eligible": True,
                "heldout_evaluated": complete_proof,
                "retuned_on_heldout": False,
            })
        return result

    current = {"forward": {"daily_mean_net_pnl_usd": 1.0}}
    first = record_frozen_candidate(tmp_path, "proven-1", candidate("1", 3.0), current)
    champion_path = (
        tmp_path / "runtime/codex_research/copy_vault_improvements/CURRENT_CHAMPION.json"
    )
    assert first is not None
    assert first["classification"] == "ECONOMICALLY_PROVEN_IMPROVEMENT"
    assert json.loads(champion_path.read_text(encoding="utf-8"))["run_id"] == "proven-1"

    record_frozen_candidate(tmp_path, "proven-2", candidate("2", 2.0), current)
    assert json.loads(champion_path.read_text(encoding="utf-8"))["run_id"] == "proven-1"

    forged = candidate("forged", 4.0, complete_proof=False)
    forged.pop("paper_read_only")
    record_frozen_candidate(tmp_path, "forged", forged, current)
    assert json.loads(champion_path.read_text(encoding="utf-8"))["run_id"] == "proven-1"


def test_record_frozen_candidate_rejects_unsafe_run_id_before_writing(tmp_path: Path) -> None:
    economic = {
        "freeze_created": True,
        "economically_proven": False,
        "selected_candidate": {"freeze": {"campaign_id": "candidate-1"}},
    }

    with pytest.raises(ValueError, match="COPY_VAULT_IMPROVEMENT_RUN_ID_INVALID"):
        record_frozen_candidate(tmp_path, "..\\..\\escape", economic, {})

    assert not (tmp_path.parent / "escape.json").exists()


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
            "net_pnl_usd": 1.0 + index, "gross_pnl_usd": 1.4 + index,
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
    repeated = run_historical_trade_replay(tmp_path, bootstrap_samples=100)
    serialized = json.dumps(
        result, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    repeated_serialized = json.dumps(
        repeated, sort_keys=True, separators=(",", ":"), allow_nan=False
    )

    assert result["status"] == "COMPLETED_EXPLORATORY"
    assert result["trial_count"] >= 10_000
    assert result["mechanism_count"] >= 5
    assert result["source_trade_count"] == 8
    assert result["baseline"]["daily_net_pnl_usd"] is not None
    assert result["economically_proven"] is False
    assert serialized == repeated_serialized


def test_historical_replay_does_not_round_a_below_target_net_up(tmp_path: Path) -> None:
    target = tmp_path / "runtime/reports/economic_campaigns/research_vnext/copy_vault_v21_entry_capacity_daily_lock_train.json"
    target.parent.mkdir(parents=True)
    trades = []
    for index in range(8):
        trades.append({
            "trade_id": f"precision-{index}",
            "exit_ts_ms": 86_400_001 + index,
            "net_pnl_usd": "2.1093749999875",
            "gross_pnl_usd": "2.5093749999875",
            "fees_usd": "0.1",
            "spread_cost_usd": "0.1",
            "slippage_cost_usd": "0.1",
            "latency_cost_usd": "0.1",
            "regime_reference_spread_bps": index + 1,
            "signed_reference_depth_imbalance": index / 10,
            "observed_latency_ms": 60_000 + index,
            "first_fill_leader_notional_usd": 100 + index,
            "entry_capacity_usd": 200 + index * 25,
            "liquidatable_net": True,
        })
    target.write_text(json.dumps({
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "paper_read_only": True,
        "real_execution": False,
        "selected": {
            "eligible": True,
            "core_maximum_notional_usd": 600.0,
            "probe_notional_usd": 75.0,
            "trades": trades,
        },
    }), encoding="utf-8")

    result = run_historical_trade_replay(tmp_path, bootstrap_samples=100)

    assert result["baseline"]["daily_net_pnl_usd"] < 5.0
    assert result["baseline"]["total_net_pnl_usd"] < 5.0
    assert result["baseline"]["bootstrap_p05_usd_per_day"] < 5.0
    assert Decimal(result["baseline"]["bootstrap_p05_usd_per_day_exact_decimal"]) < 5
    assert result["improvement_found"] is False
