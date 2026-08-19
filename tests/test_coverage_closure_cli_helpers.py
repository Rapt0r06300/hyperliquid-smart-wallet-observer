from __future__ import annotations

import json
from types import SimpleNamespace

import hl_observer.cli as cli


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def commit(self) -> None:
        self.commits += 1


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self.session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.session


def test_settings_wires_logging_and_execution_guard(monkeypatch) -> None:
    settings = SimpleNamespace(log_level="INFO")
    events: list[object] = []
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda level: events.append(("logging", level)))
    monkeypatch.setattr(cli, "assert_mainnet_execution_disabled", lambda value: events.append(("guard", value)))
    assert cli._settings() is settings
    assert events == [("logging", "INFO"), ("guard", settings)]


def test_read_json_file_handles_missing_invalid_non_mapping_and_mapping(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    assert cli._read_json_file(missing) == {}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert cli._read_json_file(invalid) == {}

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    assert cli._read_json_file(array) == {}

    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"ok": 1}), encoding="utf-8")
    assert cli._read_json_file(mapping) == {"ok": 1}


def test_unique_top_wallet_rows_deduplicates_rotates_and_limits() -> None:
    rows = [
        SimpleNamespace(wallet_address="0xA"),
        SimpleNamespace(wallet_address="0xa"),
        SimpleNamespace(wallet_address=""),
        SimpleNamespace(wallet_address="0xB"),
        SimpleNamespace(wallet_address="0xC"),
    ]
    assert cli._unique_top_wallet_rows(rows, limit=0) == []
    selected = cli._unique_top_wallet_rows(rows, limit=2, offset=1)
    assert [row.wallet_address for row in selected] == ["0xB", "0xC"]
    wrapped = cli._unique_top_wallet_rows(rows, limit=2, offset=4)
    assert [row.wallet_address for row in wrapped] == ["0xB", "0xC"]


def test_top_wallet_sample_limit_uses_default_configured_bounds_and_offset(monkeypatch) -> None:
    monkeypatch.delenv("HYPERSMART_TOP_WALLET_SAMPLE_LIMIT", raising=False)
    assert cli._top_wallet_sample_limit(target=2, offset=0, minimum=10) == 1600

    monkeypatch.setenv("HYPERSMART_TOP_WALLET_SAMPLE_LIMIT", "bad")
    assert cli._top_wallet_sample_limit(target=2, offset=0, minimum=10) == 1600

    monkeypatch.setenv("HYPERSMART_TOP_WALLET_SAMPLE_LIMIT", "12")
    assert cli._top_wallet_sample_limit(target=20, offset=5, minimum=10) == 25

    monkeypatch.setenv("HYPERSMART_TOP_WALLET_SAMPLE_LIMIT", "999999")
    assert cli._top_wallet_sample_limit(target=2, offset=0, minimum=10) == 50_000


def test_leaderboard_model_to_candidate_preserves_fields() -> None:
    row = SimpleNamespace(
        wallet_address="0xabc",
        rank=1,
        period="day",
        account_value_usdc=100.0,
        pnl_usdc=2.0,
        roi_pct=2.0,
        volume_usdc=300.0,
        leaderboard_score=88.0,
        selected_for_revalidation=True,
        selected_for_backfill=False,
        source_confidence="high",
        notes="n",
    )
    candidate = cli._leaderboard_model_to_candidate(row)
    assert candidate.wallet_address == "0xabc"
    assert candidate.rank == 1
    assert candidate.pnl_usdc == 2.0
    assert candidate.selected_for_revalidation is True
    assert candidate.selected_for_backfill is False


def test_store_with_sqlite_retry_success_path(monkeypatch) -> None:
    session = _Session()
    factory = _SessionFactory(session)
    monkeypatch.setattr(cli, "_session_factory", lambda settings: factory)
    stored: list[_Session] = []
    cli._store_with_sqlite_retry(
        SimpleNamespace(),
        label="test",
        store_func=lambda current: stored.append(current),
    )
    assert stored == [session]
    assert session.commits == 1
    assert factory.calls == 1


def test_record_local_snapshots_empty_and_non_empty(monkeypatch) -> None:
    settings = SimpleNamespace()
    monkeypatch.setattr(
        cli,
        "_session_factory",
        lambda value: (_ for _ in ()).throw(AssertionError("empty list must not open DB")),
    )
    cli._record_local_snapshots(settings, [], run_id=None, source="x")

    session = _Session()
    factory = _SessionFactory(session)
    calls: list[tuple[str, int | None, str]] = []
    monkeypatch.setattr(cli, "_session_factory", lambda value: factory)
    monkeypatch.setattr(
        cli,
        "record_robust_snapshot",
        lambda current, wallet, *, run_id, source, echo_func: calls.append((wallet, run_id, source)),
    )
    cli._record_local_snapshots(settings, ["a", "b"], run_id=7, source="unit")
    assert calls == [("a", 7, "unit"), ("b", 7, "unit")]
    assert session.commits == 1


def test_resolve_public_trade_scan_coins_explicit_path_never_opens_database(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_session_factory",
        lambda settings: (_ for _ in ()).throw(AssertionError("explicit coins must not use DB")),
    )
    result = cli._resolve_public_trade_scan_coins(SimpleNamespace(), " btc,ETH,sol ", max_coins=2)
    assert result == ["BTC", "ETH"]


def test_apply_leader_quality_gate_empty_disabled_and_fail_open(monkeypatch) -> None:
    rows = [SimpleNamespace(wallet_address="0xa")]
    assert cli._apply_leader_quality_gate(object(), [], limit=1) == []

    monkeypatch.setenv("HYPERSMART_LEADER_QUALITY_GATE", "0")
    assert cli._apply_leader_quality_gate(object(), rows, limit=1) is rows

    monkeypatch.setenv("HYPERSMART_LEADER_QUALITY_GATE", "1")
    import builtins

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "hl_observer.scoring.leader_realized_history":
            raise RuntimeError("forced import failure")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert cli._apply_leader_quality_gate(object(), rows, limit=1) is rows
