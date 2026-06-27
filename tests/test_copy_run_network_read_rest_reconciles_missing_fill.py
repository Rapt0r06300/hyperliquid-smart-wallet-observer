"""REST reconciliation: a fill already seen is deduped by hash/tid/time and does
NOT create a second delta nor a duplicate paper intent. No network."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.storage.database import get_connection
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, healthy_l2, runtime_config, write_leader_shortlist


def _counts(config):
    with get_connection(config) as conn:
        deltas = conn.execute("SELECT COUNT(*) FROM leader_deltas").fetchone()[0]
        fills = conn.execute("SELECT COUNT(*) FROM fill_snapshots").fetchone()[0]
    return deltas, fills


def test_repeated_rest_fill_is_deduped_not_double_counted(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    # ONE fake reused => identical fills (same hash + time) on both runs.
    fake = RuntimeFakeInfoClient(l2_book=healthy_l2())

    r1 = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)
    deltas1, fills1 = _counts(config)

    r2 = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)
    deltas2, fills2 = _counts(config)

    assert r1.deltas_seen >= 1
    assert r2.deltas_seen == 0           # repeated fills => no new delta
    assert fills2 == fills1              # fill_dedupe prevents re-insertion
    assert deltas2 == deltas1            # no duplicate leader_deltas
