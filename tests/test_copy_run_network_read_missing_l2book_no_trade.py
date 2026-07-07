"""Runtime: missing/empty l2Book => degraded features => NoTrade, never a paper trade."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.storage.database import get_connection
from hyper_smart_observer.storage.repositories import paper_trades_repo
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, runtime_config, write_leader_shortlist


def test_runtime_missing_l2book_produces_no_trade(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(l2_book={})  # l2Book returns empty/invalid

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert run.signal_candidates
    assert all(s.decision.value == "REJECT_NO_TRADE" for s in run.signal_candidates)
    reasons = set().union(*[set(s.refusal_reasons) for s in run.signal_candidates])
    assert reasons & {"LIQUIDITY_TOO_LOW", "EDGE_UNMEASURABLE", "EDGE_REMAINING_TOO_LOW"}
    with get_connection(config) as conn:
        assert not paper_trades_repo.list_open_paper_trades(conn)


def test_runtime_missing_l2book_method_degrades_safely(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(with_l2_method=False)  # client has no l2Book at all

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    with get_connection(config) as conn:
        assert not paper_trades_repo.list_open_paper_trades(conn)
    assert any("l2Book_unavailable" in f for f in run.source_failures)
