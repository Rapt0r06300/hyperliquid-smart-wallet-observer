"""Runtime: a thin l2Book (liquidity_score < 0.5) => LIQUIDITY_TOO_LOW, no paper trade."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.storage.database import get_connection
from hyper_smart_observer.storage.repositories import paper_trades_repo
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, runtime_config, thin_l2, write_leader_shortlist


def test_runtime_low_liquidity_blocks_signal(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(l2_book=thin_l2())

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert run.signal_candidates
    assert all(s.decision.value == "REJECT_NO_TRADE" for s in run.signal_candidates)
    assert any("LIQUIDITY_TOO_LOW" in s.refusal_reasons for s in run.signal_candidates)
    with get_connection(config) as conn:
        assert not paper_trades_repo.list_open_paper_trades(conn)
