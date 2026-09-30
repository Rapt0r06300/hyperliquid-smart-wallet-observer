from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import pytest

from hl_observer.explorer import explorer_importer
from hl_observer.explorer.explorer_models import ExplorerSourceStatus, ExplorerTransaction
from hl_observer.scanner.opportunity_detector import detect_missed_opportunity
from hl_observer.scanner.scanner_models import MissedOpportunityReason, SignalObservation
from hl_observer.wallets import leaderboard_full_address_extractor as address_extractor
from hl_observer.wallets import snapshot_service


WALLET = "0x" + "a" * 40


def test_leaderboard_address_extractor_walks_nested_values_and_dedupes() -> None:
    truncated = "0x12...abcd"
    payload = {
        WALLET.upper(): [WALLET, truncated, "noise 0x1234"],
        "nested": ({"again": WALLET.lower()},),
        "number": 7,
    }
    result = address_extractor.extract_wallet_address_values(payload)
    assert result.full_addresses == [WALLET]
    assert result.truncated_addresses == [truncated]
    assert result.rejected_values == ["0x1234"]
    assert address_extractor._walk_strings("x") == ["x"]
    assert address_extractor._walk_strings(123) == []
    assert address_extractor._dedupe(["A", "a", "B"]) == ["A", "B"]


def test_explorer_importer_reads_json_csv_text_and_missing(tmp_path, monkeypatch) -> None:
    json_list = tmp_path / "rows.json"
    json_list.write_text(json.dumps([{"a": 1}, "bad", {"b": 2}]), encoding="utf-8")
    assert explorer_importer._read_records(json_list) == [{"a": 1}, {"b": 2}]

    json_map = tmp_path / "map.json"
    json_map.write_text(json.dumps({"transactions": [{"x": 1}, "bad"]}), encoding="utf-8")
    assert explorer_importer._read_records(json_map) == [{"x": 1}]
    json_map.write_text(json.dumps({"events": [{"e": 1}]}), encoding="utf-8")
    assert explorer_importer._read_records(json_map) == [{"e": 1}]
    json_map.write_text(json.dumps({"rows": [{"r": 1}]}), encoding="utf-8")
    assert explorer_importer._read_records(json_map) == [{"r": 1}]

    csv_path = tmp_path / "rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["address", "coin"])
        writer.writeheader()
        writer.writerow({"address": WALLET, "coin": "BTC"})
    assert explorer_importer._read_records(csv_path) == [{"address": WALLET, "coin": "BTC"}]

    txt = tmp_path / "rows.txt"
    txt.write_text(f"\n{WALLET}\n  second  \n", encoding="utf-8")
    assert explorer_importer._read_records(txt) == [{"address": WALLET}, {"address": "second"}]

    with pytest.raises(FileNotFoundError):
        explorer_importer._read_records(tmp_path / "missing.json")

    tx = ExplorerTransaction(wallet_address=WALLET)
    monkeypatch.setattr(explorer_importer, "parse_explorer_records", lambda records, source_url: ([tx], 2))
    result = explorer_importer.import_explorer_file(txt)
    assert result.status == ExplorerSourceStatus.OK
    assert result.full_addresses_found == 1
    assert result.truncated_addresses_rejected == 2
    assert result.candidates_created == 1
    assert result.finished_at_ms is not None

    monkeypatch.setattr(explorer_importer, "parse_explorer_records", lambda records, source_url: ([], 0))
    result = explorer_importer.import_explorer_file(txt)
    assert result.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert result.full_addresses_found == 0


def _obs(**overrides) -> SignalObservation:
    values = dict(
        signal_id="s",
        wallet_address=WALLET,
        coin="BTC",
        action_type="OPEN_LONG",
        observed_at_ms=1_000,
        now_ms=1_100,
        current_mid=100.0,
        edge_remaining_bps=20.0,
        liquidity_score=1.0,
        copy_degradation_bps=0.0,
        has_matching_paper_position=True,
        open_positions_count=0,
        max_open_positions=3,
        source="unit",
    )
    values.update(overrides)
    return SignalObservation(**values)


@pytest.mark.parametrize(
    "observation,reason,severity",
    [
        (_obs(observed_at_ms=0, now_ms=100_000), MissedOpportunityReason.STALE_SIGNAL.value, "INFO"),
        (_obs(current_mid=None), MissedOpportunityReason.MISSING_CURRENT_MID.value, "WARN"),
        (_obs(current_mid=0), MissedOpportunityReason.MISSING_CURRENT_MID.value, "WARN"),
        (_obs(edge_remaining_bps=None), MissedOpportunityReason.EDGE_UNMEASURABLE.value, "WARN"),
        (_obs(edge_remaining_bps=2.0), MissedOpportunityReason.EDGE_REMAINING_TOO_LOW.value, "INFO"),
        (_obs(liquidity_score=0.1), MissedOpportunityReason.LIQUIDITY_TOO_LOW.value, "INFO"),
        (_obs(copy_degradation_bps=99.0), MissedOpportunityReason.COPY_DEGRADATION_TOO_HIGH.value, "INFO"),
        (_obs(action_type="REDUCE", has_matching_paper_position=False), MissedOpportunityReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value, "INFO"),
        (_obs(action_type="close_long", has_matching_paper_position=False), MissedOpportunityReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE.value, "INFO"),
        (_obs(open_positions_count=3, max_open_positions=3), MissedOpportunityReason.MAX_OPEN_PAPER_TRADES_REACHED.value, "INFO"),
    ],
)
def test_opportunity_detector_all_refusal_reasons(observation, reason, severity) -> None:
    result = detect_missed_opportunity(observation)
    assert result is not None
    assert result.reason == reason
    assert result.severity == severity
    assert result.component == "opportunity_detector"
    assert result.details["source"] == "unit"
    assert result.message
    assert result.next_action


def test_opportunity_detector_accepts_clean_signal_and_clamps_negative_age() -> None:
    assert detect_missed_opportunity(_obs()) is None
    assert detect_missed_opportunity(_obs(observed_at_ms=2_000, now_ms=1_000)) is None


class _Query:
    def __init__(self, *, first=None, rows=None) -> None:
        self._first = first
        self._rows = list(rows or [])

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, value):
        self._rows = self._rows[:value]
        return self

    def first(self):
        return self._first

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, queries) -> None:
        self.queries = list(queries)
        self.flushed = 0

    def query(self, model):
        assert self.queries
        return self.queries.pop(0)

    def flush(self):
        self.flushed += 1


class _Comparison:
    def __init__(self, deltas) -> None:
        self.errors = ["compare-warning"]
        self.warnings = ["watch"]
        self.deltas = deltas
        self.current_snapshot_id = None
        self.previous_snapshot_id = None

    def summary(self):
        return "summary"


class _Repo:
    def __init__(self, previous=None) -> None:
        self.previous = previous
        self.stored_kwargs = None
        self.deltas = None
        self.current = SimpleNamespace(id=10, summary=None)

    def get_latest_wallet_snapshot(self, wallet):
        return self.previous

    def store_wallet_snapshot(self, **kwargs):
        self.stored_kwargs = kwargs
        return self.current

    def store_position_deltas(self, deltas):
        self.deltas = deltas


class _SnapshotEngine:
    def __init__(self, comparison) -> None:
        self.comparison = comparison
        self.from_model_calls = []
        self.compare_calls = []

    def from_model(self, model):
        self.from_model_calls.append(model)
        return "previous-snapshot"

    def compare_snapshots(self, current, previous):
        self.compare_calls.append((current, previous))
        return self.comparison


def test_positions_payload_prefers_clearinghouse_then_local_positions() -> None:
    raw = SimpleNamespace(response_payload_json={"assetPositions": [{"position": 1}, "bad"]})
    session = _Session([])
    assert snapshot_service._positions_payload(session, WALLET, raw) == [{"position": 1}]

    rows = [SimpleNamespace(coin="BTC", size="1", entry_price=None, entry_px_estimated="99", raw_json={"x": 1})]
    session = _Session([_Query(rows=rows)])
    payload = snapshot_service._positions_payload(session, WALLET, SimpleNamespace(response_payload_json={"assetPositions": "bad"}))
    assert payload == [{"coin": "BTC", "szi": "1", "entryPx": "99", "raw": {"x": 1}}]


def test_record_robust_snapshot_persists_comparison_and_deltas(monkeypatch) -> None:
    raw_event = SimpleNamespace(exchange_ts=123)
    clearinghouse = SimpleNamespace(response_payload_json={"assetPositions": [{"coin": "BTC"}]})
    mids = SimpleNamespace(raw_json={"BTC": "100"})
    order = SimpleNamespace(raw_json={"oid": 1})
    fill = SimpleNamespace(raw_json={"fid": 1})
    session = _Session([
        _Query(first=raw_event),
        _Query(first=clearinghouse),
        _Query(first=mids),
        _Query(rows=[order]),
        _Query(rows=[fill]),
    ])
    previous = SimpleNamespace(id=5)
    delta = SimpleNamespace(snapshot_id=None)
    comparison = _Comparison([delta])
    repo = _Repo(previous)
    engine = _SnapshotEngine(comparison)
    monkeypatch.setattr(snapshot_service, "CollectionRepository", lambda value: repo)
    monkeypatch.setattr(snapshot_service, "SnapshotEngine", lambda: engine)
    monkeypatch.setattr(snapshot_service, "now_ms", lambda: 999)
    echoes = []

    snapshot_service.record_robust_snapshot(
        session,
        WALLET,
        run_id=7,
        source="unit",
        stopped_reason="done",
        errors=["input-error"],
        echo_func=echoes.append,
    )
    assert session.flushed == 1
    assert engine.from_model_calls == [previous]
    assert engine.compare_calls[0][1] == "previous-snapshot"
    assert repo.current.summary == "summary"
    assert comparison.current_snapshot_id == 10
    assert comparison.previous_snapshot_id == 5
    assert delta.snapshot_id == 10
    assert repo.deltas == [delta]
    assert repo.stored_kwargs["errors"] == ["input-error", "compare-warning"]
    assert repo.stored_kwargs["exchange_ts"] == 123
    assert repo.stored_kwargs["all_mids"] == {"BTC": "100"}
    assert any("snapshot" in line for line in echoes)
    assert any("warning" in line for line in echoes)


def test_record_snapshot_without_previous_or_deltas_uses_safe_defaults(monkeypatch) -> None:
    raw_event = SimpleNamespace(exchange_ts=None)
    session = _Session([
        _Query(first=raw_event),
        _Query(first=None),
        _Query(first=SimpleNamespace(raw_json=[])),
        _Query(rows=[]),
        _Query(rows=[]),
        _Query(rows=[]),
    ])
    comparison = _Comparison([])
    comparison.errors = []
    comparison.warnings = []
    repo = _Repo(previous=None)
    engine = _SnapshotEngine(comparison)
    monkeypatch.setattr(snapshot_service, "CollectionRepository", lambda value: repo)
    monkeypatch.setattr(snapshot_service, "SnapshotEngine", lambda: engine)
    monkeypatch.setattr(snapshot_service, "now_ms", lambda: 500)

    snapshot_service.record_robust_snapshot(session, WALLET)
    assert engine.from_model_calls == []
    assert engine.compare_calls[0][1] is None
    assert repo.deltas is None
    assert repo.stored_kwargs["exchange_ts"] == 500
    assert repo.stored_kwargs["all_mids"] == {}
    assert repo.stored_kwargs["positions"] == []
