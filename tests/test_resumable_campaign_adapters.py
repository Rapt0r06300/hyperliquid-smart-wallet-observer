from __future__ import annotations

import subprocess
import sys
import time

from hl_observer.control_plane.campaign_adapters import (
    AdapterContext,
    build_command,
    run_one_unit,
)


def context(kind: str, **partition):
    return AdapterContext(
        campaign_id="c1",
        kind=kind,
        unit_id="u1",
        soft_deadline_epoch=time.time() + 60,
        partition={"code_sha": "a" * 40, **partition},
    )


def test_market_command_uses_real_collector_cli(tmp_path):
    cmd, output = build_command(
        context("market_collection", output_root=str(tmp_path), duration_s=10, coins="BTC")
    )
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("tools/collect_cloud_window.py")
    assert "--output" in cmd
    assert "--duration-s" in cmd
    assert "--campaign-unit-json" not in cmd
    assert output is not None


def test_official_archive_uses_existing_backfill_tool(tmp_path):
    cmd, output = build_command(
        context(
            "official_archive_collection",
            output_root=str(tmp_path),
            venue="binance",
            coin="BTC",
            symbol="BTCUSDT",
            start_date="2026-09-24",
        )
    )
    assert cmd[1].endswith("tools/collect_official_archive_backfill.py")
    assert output is not None and output.name == "bundle"


def test_replay_materializes_only_v2_safe_workspace(tmp_path):
    cmd, output = build_command(
        context("replay", output_root=str(tmp_path))
    )
    assert "hl_observer.ops.v2_dataset_bridge" in cmd
    assert "materialize" in cmd
    assert output is not None


def test_soft_deadline_refuses_work():
    ctx = AdapterContext("c1", "market_collection", "u1", time.time() - 1, {})
    out = run_one_unit(ctx)
    assert out.status == "CONTINUATION_REQUIRED"
    assert out.progressed is False


def test_subprocess_failure_is_honest(tmp_path):
    class Result:
        returncode = 2
        stdout = ""
        stderr = "quality mismatch"

    out = run_one_unit(
        context("market_collection", output_root=str(tmp_path), duration_s=1),
        runner=lambda *args, **kwargs: Result(),
    )
    assert out.status == "FAILED"
    assert out.payload["failure_category"] == "QUALITY"


def test_backtest_requires_materialized_safe_workspace(tmp_path):
    ctx=context("backtest", workspace_root=str(tmp_path/"missing"))
    try:
        build_command(ctx)
    except ValueError as exc:
        assert "materialized SAFE Dataset V2 workspace" in str(exc)
    else:
        raise AssertionError("backtest accepted an unmaterialized workspace")

def test_replay_forwards_selection_filters(tmp_path):
    cmd,_=build_command(context("replay", workspace_root=str(tmp_path), families="trades,bbo", venues="hyperliquid"))
    assert "--families" in cmd and "trades,bbo" in cmd
    assert "--venues" in cmd and "hyperliquid" in cmd
