"""Runtime: a wide-spread l2Book => SPREAD_TOO_WIDE / degraded edge, no paper trade."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.storage.database import get_connection
from hyper_smart_observer.storage.repositories import paper_trades_repo
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, runtime_config, wide_spread_l2, write_leader_shortlist


def test_runtime_wide_spread_blocks_or_degrades(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(l2_book=wide_spread_l2())

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert run.signal_candidates
    reasons = set().union(*[set(s.refusal_reasons) for s in run.signal_candidates])
    assert reasons & {"SPREAD_TOO_WIDE", "EDGE_REMAINING_TOO_LOW", "COPY_DEGRADATION_TOO_HIGH"}
    assert all(s.decision.value == "REJECT_NO_TRADE" for s in run.signal_candidates)
    with get_connection(config) as conn:
        assert not paper_trades_repo.list_open_paper_trades(conn)
