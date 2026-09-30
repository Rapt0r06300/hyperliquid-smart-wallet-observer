from __future__ import annotations

from types import SimpleNamespace

import pytest

import hl_observer.collection.run_collect_all as collect_all
import hl_observer.copy_mode.multi_wallet_copy_session as multi_session
from hl_observer.copy_mode.multi_wallet_copy_session import MultiWalletSessionConfig, run_multi_wallet_copy_session
from hl_observer.copy_mode.wallet_mirror_runtime import MirrorCandidate
from hl_observer.scoring.live_wallet_scoring_loop import score_live_wallets


def _candidate(
    candidate_id: str,
    *,
    coin: str = "BTC",
    side: str = "LONG",
    wallet_score: float = 0.9,
    copyability: float = 0.8,
    confidence: float = 0.7,
    reasons: tuple[str, ...] = (),
) -> MirrorCandidate:
    return MirrorCandidate(
        candidate_id=candidate_id,
        leader_wallet=f"0x{candidate_id}",
        coin=coin,
        leader_action="OPEN_LONG",
        side=side,
        leader_size=1.0,
        leader_price=100.0,
        leader_time=1000,
        observed_time=1100,
        copy_ratio=0.05,
        wallet_score=wallet_score,
        copyability_score=copyability,
        slippage_budget_bps=10.0,
        source_fill_refs=("fill-1",),
        confidence=confidence,
        reason_codes=reasons,
    )


def test_live_wallet_scoring_empty_insufficient_positive_negative_and_bounds() -> None:
    assert score_live_wallets([]) == ()
    rows = score_live_wallets(
        [
            {"wallet": "0xA", "events": 1, "wins": 1, "paper_pnl": 2, "recency_score": 2},
            {"wallet": "0xB", "fill_count": 10, "positive_events": 0, "realized_pnl": -5, "recency_score": -2},
            {"wallet": "0xC", "events": 20, "wins": 10, "paper_pnl": 0, "recency_score": 0.5},
        ],
        min_events=3,
    )
    assert rows[0].wallet == "0xa"
    assert rows[0].reason_codes == ("INSUFFICIENT_LIVE_EVENTS",)
    assert rows[0].wallet_score <= 1.0 and rows[0].copyability_score <= 1.0
    assert rows[1].wallet == "0xb"
    assert rows[1].wallet_score >= 0.0 and rows[1].copyability_score >= 0.0
    assert rows[2].reason_codes == ()


def test_multi_wallet_session_rejects_preinvalid_and_conflicts(monkeypatch) -> None:
    invalid = _candidate("bad", reasons=("STALE",))
    valid_a = _candidate("a")
    valid_b = _candidate("b")

    monkeypatch.setattr(
        multi_session,
        "resolve_copy_conflicts",
        lambda rows, min_same_side_leaders: SimpleNamespace(accepted=False, reason_codes=("NO_CONSENSUS",)),
    )
    result = run_multi_wallet_copy_session(
        [invalid, valid_a, valid_b],
        equity_usdt=1000.0,
        mids={"BTC": 101.0},
        observed_at_ms=1200,
    )
    assert result.accepted == ()
    assert result.groups_seen == 1
    reasons = {row["candidate_id"]: row["reason_codes"] for row in result.rejected}
    assert reasons["bad"] == ["STALE"]
    assert reasons["a"] == ["NO_CONSENSUS"]
    assert reasons["b"] == ["NO_CONSENSUS"]
    assert result.paper_only and not result.external_action


def test_multi_wallet_session_selects_best_executes_accept_and_reject(monkeypatch) -> None:
    a = _candidate("a", wallet_score=0.7, copyability=0.7, confidence=0.7)
    b = _candidate("b", wallet_score=0.9, copyability=0.8, confidence=0.8)
    c = _candidate("c", coin="ETH", wallet_score=0.8)
    d = _candidate("d", coin="ETH", wallet_score=0.7)
    seen = []

    monkeypatch.setattr(
        multi_session,
        "resolve_copy_conflicts",
        lambda rows, min_same_side_leaders: SimpleNamespace(accepted=True, reason_codes=()),
    )

    def _execute(candidate, **kwargs):
        seen.append((candidate.candidate_id, kwargs["mid_price"], kwargs["asks"], kwargs["bids"]))
        if candidate.coin == "BTC":
            return SimpleNamespace(accepted=True, reason_codes=())
        return SimpleNamespace(accepted=False, reason_codes=("PAPER_REJECT",))

    monkeypatch.setattr(multi_session, "execute_mirror_candidate_paper", _execute)
    result = run_multi_wallet_copy_session(
        [a, b, c, d],
        equity_usdt=1000.0,
        mids={"BTC": 101.0},
        books={"BTC": {"asks": ((101.0, 1.0),), "bids": ((99.0, 1.0),)}},
        observed_at_ms=1200,
    )
    assert len(result.accepted) == 1
    assert seen[0][0] == "b"
    assert seen[0][1] == 101.0
    assert seen[0][2] == ((101.0, 1.0),)
    assert seen[0][3] == ((99.0, 1.0),)
    assert seen[1][0] == "c"
    assert seen[1][1] == 100.0
    assert any(row["candidate_id"] == "c" and row["reason_codes"] == ["PAPER_REJECT"] for row in result.rejected)


def test_multi_wallet_session_honors_max_positions(monkeypatch) -> None:
    btc = [_candidate("a"), _candidate("b")]
    eth = [_candidate("c", coin="ETH"), _candidate("d", coin="ETH")]
    monkeypatch.setattr(
        multi_session,
        "resolve_copy_conflicts",
        lambda rows, min_same_side_leaders: SimpleNamespace(accepted=True, reason_codes=()),
    )
    monkeypatch.setattr(
        multi_session,
        "execute_mirror_candidate_paper",
        lambda candidate, **kwargs: SimpleNamespace(accepted=True, reason_codes=()),
    )
    result = run_multi_wallet_copy_session(
        btc + eth,
        equity_usdt=1000.0,
        mids={},
        observed_at_ms=1200,
        config=MultiWalletSessionConfig(max_positions_per_run=1),
    )
    assert len(result.accepted) == 1
    limited = [row for row in result.rejected if row["reason_codes"] == ["MAX_POSITIONS_PER_RUN"]]
    assert len(limited) == 2


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self) -> None:
        self.commits += 1


class _Report:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def summary(self) -> str:
        return "COLLECT_ALL_TEST_SUMMARY"


def _install_collect_all_fakes(monkeypatch, *, report_ok: bool):
    settings = SimpleNamespace(
        database_url="sqlite://",
        wallet_scanner=SimpleNamespace(scan_max_wallets_per_run=12, scan_batch_size=3),
    )
    sessions = []
    calls = []
    monkeypatch.setattr(collect_all, "load_settings", lambda: settings)
    monkeypatch.setattr(collect_all, "create_sqlite_engine", lambda url: ("engine", url))

    def _factory(engine):
        def _make():
            session = _FakeSession()
            sessions.append(session)
            return session
        return _make

    monkeypatch.setattr(collect_all, "create_session_factory", _factory)
    monkeypatch.setattr(
        collect_all,
        "MarketDiscoveryPlan",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    async def _markets(plan, passed_settings):
        calls.append(("markets", plan.max_coins, plan.store, plan.dry_run))
        return SimpleNamespace(coins_discovered=7)

    monkeypatch.setattr(collect_all, "run_discover_markets", _markets)
    monkeypatch.setattr(
        collect_all,
        "build_wallet_discovery_plan",
        lambda passed_settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        collect_all,
        "run_wallet_discovery",
        lambda plan, passed_settings: (calls.append(("wallets", plan.store, plan.dry_run)) or SimpleNamespace(candidates_found=9)),
    )
    monkeypatch.setattr(
        collect_all,
        "bootstrap_top_wallets",
        lambda passed_settings, **kwargs: calls.append(("bootstrap", kwargs["target"], kwargs["source"], kwargs["store"])),
    )
    monkeypatch.setattr(
        collect_all,
        "scan_wallet_queue",
        lambda session, **kwargs: calls.append(("scan", kwargs["max_wallets"], kwargs["batch_size"], kwargs["dry_run"])),
    )

    def _run_steps(steps):
        names = []
        for name, callback in steps:
            names.append(name)
            value = callback()
            assert isinstance(value, str)
        calls.append(("steps", tuple(names)))
        return _Report(report_ok)

    monkeypatch.setattr(collect_all, "run_steps", _run_steps)
    return calls, sessions


def test_collect_all_main_executes_all_read_only_collection_steps(monkeypatch, capsys) -> None:
    calls, sessions = _install_collect_all_fakes(monkeypatch, report_ok=True)
    rc = collect_all.main(["--max-coins", "25", "--target", "42"])
    assert rc == 0
    assert ("markets", 25, True, False) in calls
    assert ("wallets", True, False) in calls
    assert ("bootstrap", 42, "all", True) in calls
    assert ("scan", 12, 3, False) in calls
    assert any(row[0] == "steps" for row in calls)
    assert len(sessions) == 2 and all(session.commits == 1 for session in sessions)
    assert "COLLECT_ALL_TEST_SUMMARY" in capsys.readouterr().out


def test_collect_all_main_propagates_report_failure(monkeypatch) -> None:
    _install_collect_all_fakes(monkeypatch, report_ok=False)
    assert collect_all.main([]) == 1
