from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hl_observer.edge.cost_validation import (
    categorize_cost_level,
    estimate_total_costs,
    suggest_cost_reduction_actions,
    validate_edge_remaining,
)
from hl_observer.explorer import explorer_source as source
from hl_observer.explorer.explorer_models import (
    ExplorerEndpointProbe,
    ExplorerResult,
    ExplorerSourceStatus,
    ExplorerTransaction,
)


WALLET = "0x" + "b" * 40


def test_edge_validation_all_fail_closed_and_success_branches() -> None:
    zero = validate_edge_remaining(0.0, 5.0)
    assert zero.passed is False
    assert "NEGATIVE_OR_ZERO" in zero.reason

    low = validate_edge_remaining(20.0, 5.0, min_edge_required_bps=30.0)
    assert low.passed is False
    assert "BELOW_MINIMUM" in low.reason

    costly = validate_edge_remaining(40.0, 91.0, min_edge_required_bps=30.0)
    assert costly.passed is False
    assert "EXCEED_SAFETY_LIMIT" in costly.reason
    assert costly.cost_to_edge_ratio == pytest.approx(91.0 / 30.0)

    infinite = validate_edge_remaining(1.0, 1.0, min_edge_required_bps=0.0)
    assert infinite.passed is False
    assert infinite.cost_to_edge_ratio == float("inf")

    good = validate_edge_remaining(60.0, 20.0, min_edge_required_bps=30.0)
    assert good.passed is True
    assert good.cost_to_edge_ratio == pytest.approx(1 / 3)
    assert "EDGE_SUFFICIENT" in good.reason


def test_cost_estimation_categories_and_reduction_suggestions() -> None:
    assert estimate_total_costs(1, 2, 3, 4, 5, 6) == 21
    for value, expected in (
        (5, "VERY_LOW"),
        (6, "LOW"),
        (15, "LOW"),
        (16, "MODERATE"),
        (30, "MODERATE"),
        (31, "HIGH"),
        (60, "HIGH"),
        (61, "VERY_HIGH"),
        (100, "VERY_HIGH"),
        (101, "PROHIBITIVE"),
    ):
        assert categorize_cost_level(value) == expected

    actions = suggest_cost_reduction_actions(120.0, -1.0)
    assert "REJECT_ILLIQUID_COINS_HIGH_SPREAD" in actions
    assert "REQUIRE_MINIMUM_NOTIONAL_SIZE_TO_AMORTIZE_FEES" in actions
    assert "INCREASE_WALLET_SCORE_THRESHOLD" in actions
    assert "REJECT_SIGNAL_EDGE_DESTROYED_BY_COSTS" in actions
    assert "STRENGTHEN_EDGE_DETECTION_SIGNAL_FILTERING" in actions
    assert "INCREASE_MIN_EDGE_REQUIRED_TO_2X_COSTS_MINIMUM" in actions
    assert suggest_cost_reduction_actions(5.0, 50.0) == []


def _result(*, full: bool = True) -> ExplorerResult:
    wallet = WALLET if full else None
    status = ExplorerSourceStatus.OK if full else ExplorerSourceStatus.IMPORT_REQUIRED
    return ExplorerResult(
        method="network",
        status=status,
        started_at_ms=10,
        finished_at_ms=20,
        endpoints_found=[
            ExplorerEndpointProbe(
                endpoint_url="https://unit.invalid",
                method="POST",
                status=ExplorerSourceStatus.OK,
                http_status=200,
                notes=["unit"],
            )
        ],
        events_seen=1,
        transactions=[
            ExplorerTransaction(
                tx_hash="0xtx",
                block=7,
                timestamp_ms=11,
                action_type="fill",
                wallet_address=wallet,
                coin="BTC",
                side="B",
                size=1.0,
                price=100.0,
                value_usdc=100.0,
                source_url="unit",
                confidence_score=0.9,
                validation_status=(
                    ExplorerSourceStatus.FULL_ADDRESS_OK
                    if full
                    else ExplorerSourceStatus.EVENT_WITHOUT_ADDRESS
                ),
                raw_payload={"x": 1},
            )
        ],
        full_addresses_found=1 if full else 0,
        candidates_created=1 if full else 0,
        notes=["n1", "n2"],
    )


def test_scrape_explorer_all_methods_and_store_gate(monkeypatch) -> None:
    settings = SimpleNamespace(wallet_discovery=SimpleNamespace(source_timeout_seconds=3.0))
    expected = _result()
    calls = []

    async def network(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(source, "probe_explorer_network", network)
    stored = []
    monkeypatch.setattr(source, "store_explorer_result", lambda session, result: stored.append((session, result)))
    session = object()

    assert asyncio.run(source.scrape_explorer(settings, method="network", dry_run=False, store=True, max_events=9, session=session)) is expected
    assert calls[0] == {"timeout_seconds": 3.0, "dry_run": False, "max_events": 9}
    assert stored == [(session, expected)]

    stored.clear()
    assert asyncio.run(source.scrape_explorer(settings, method="AUTO", dry_run=True, store=True, session=session)) is expected
    assert stored == []

    dom = asyncio.run(source.scrape_explorer(settings, method="dom"))
    assert dom.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert dom.method == "dom"
    other = asyncio.run(source.scrape_explorer(settings, method="something"))
    assert other.status == ExplorerSourceStatus.IMPORT_REQUIRED
    assert "unsupported_method" in other.notes[0]


def test_import_and_store_requires_session_and_delegates(monkeypatch, tmp_path) -> None:
    expected = _result()
    monkeypatch.setattr(source, "import_explorer_file", lambda path: expected)
    calls = []
    monkeypatch.setattr(source, "store_explorer_result", lambda session, result: calls.append((session, result)))

    assert source.import_and_store_explorer(tmp_path / "x.json", store=False) is expected
    assert calls == []
    with pytest.raises(ValueError, match="session is required"):
        source.import_and_store_explorer(tmp_path / "x.json", store=True)
    session = object()
    assert source.import_and_store_explorer(tmp_path / "x.json", store=True, session=session) is expected
    assert calls == [(session, expected)]


class _StoreSession:
    def __init__(self) -> None:
        self.added = []
        self.flushes = 0
        self._next_tx_id = 100

    def add(self, obj) -> None:
        self.added.append(obj)
        name = type(obj).__name__
        if name == "ExplorerRun" and getattr(obj, "id", None) is None:
            obj.id = 1
        if name == "ExplorerTransaction" and getattr(obj, "id", None) is None:
            obj.id = self._next_tx_id
            self._next_tx_id += 1

    def flush(self) -> None:
        self.flushes += 1


def test_store_explorer_result_persists_endpoint_tape_events_and_candidate(monkeypatch) -> None:
    session = _StoreSession()
    monkeypatch.setattr(source, "now_ms", lambda: 999)
    result = _result(full=True)
    run = source.store_explorer_result(session, result)
    assert run.id == 1
    names = [type(obj).__name__ for obj in session.added]
    assert "ExplorerRun" in names
    assert "ExplorerEndpoint" in names
    assert "ExplorerTransaction" in names
    assert "ExplorerEvent" in names
    assert "ExplorerTransactionTape" in names
    assert "ExplorerWalletCandidate" in names
    candidate = next(obj for obj in session.added if type(obj).__name__ == "ExplorerWalletCandidate")
    assert candidate.wallet_address == WALLET
    assert candidate.events_count == 1
    assert candidate.coins_json == ["BTC"]
    tape = next(obj for obj in session.added if type(obj).__name__ == "ExplorerTransactionTape")
    assert tape.candidate_created is True
    assert tape.reason is None

    session2 = _StoreSession()
    no_wallet = _result(full=False)
    source.store_explorer_result(session2, no_wallet)
    assert not any(type(obj).__name__ == "ExplorerWalletCandidate" for obj in session2.added)
    tape2 = next(obj for obj in session2.added if type(obj).__name__ == "ExplorerTransactionTape")
    assert tape2.candidate_created is False
    assert tape2.reason == ExplorerSourceStatus.EVENT_WITHOUT_ADDRESS.value


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _CandidateSession:
    def __init__(self, rows, existing=()) -> None:
        self.rows = list(rows)
        self.existing = list(existing)
        self.added = []

    def scalars(self, statement):
        return _ScalarRows(self.rows)

    def query(self, model):
        return SimpleNamespace(all=lambda: [(value,) for value in self.existing])

    def add(self, obj):
        self.added.append(obj)


def test_create_explorer_candidates_groups_skips_existing_and_caps_score(monkeypatch) -> None:
    rows = [
        SimpleNamespace(wallet_address="w1", tx_hash="a", coin="BTC"),
        SimpleNamespace(wallet_address="w1", tx_hash="b", coin="ETH"),
        SimpleNamespace(wallet_address="w2", tx_hash="c", coin=None),
        SimpleNamespace(wallet_address=None, tx_hash="d", coin="SOL"),
    ]
    monkeypatch.setattr(source, "now_ms", lambda: 123)
    session = _CandidateSession(rows, existing=["w2"])
    assert source.create_explorer_candidates(session) == 1
    assert len(session.added) == 1
    candidate = session.added[0]
    assert candidate.wallet_address == "w1"
    assert candidate.events_count == 2
    assert candidate.coins_json == ["BTC", "ETH"]
    assert candidate.activity_score == 60.0


def test_explorer_status_with_and_without_run() -> None:
    class Session:
        def __init__(self, values):
            self.values = iter(values)

        def scalar(self, statement):
            return next(self.values)

    run = SimpleNamespace(
        status="OK",
        method="network",
        endpoints_found=2,
        events_seen=3,
        full_addresses_found=4,
        truncated_addresses_rejected=5,
        error_message=None,
    )
    status = source.explorer_status(Session([run, 6, 7, 8]))
    assert status["status"] == "OK"
    assert status["transactions_stored"] == 7
    assert status["candidates_created"] == 6
    assert status["truncated_addresses_rejected"] == 5
    assert status["next_action"] == "revalidate_explorer_wallets"

    empty = source.explorer_status(Session([None, 0, 0, 9]))
    assert empty["status"] == "IMPORT_REQUIRED"
    assert empty["truncated_addresses_rejected"] == 9
    assert empty["next_action"] == "import_explorer_csv"


def test_format_explorer_report_success_and_empty() -> None:
    success = source.format_explorer_report(_result(full=True))
    assert "statut: OK" in success
    assert "notes: n1; n2" in success
    assert "aucune adresse complete" not in success

    empty = _result(full=False)
    empty.error_message = "offline"
    report = source.format_explorer_report(empty)
    assert "erreur: offline" in report
    assert "aucune adresse complete" in report
    assert "Aucun wallet n'a ete invente" in report
