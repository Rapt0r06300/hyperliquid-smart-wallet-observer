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
        context("replay", workspace_root=str(tmp_path), families="trades,bbo")
    )
    assert "hl_observer.ops.v2_dataset_bridge" in cmd
    assert "materialize" in cmd
    assert "--families" in cmd
    assert "trades,bbo" in cmd
    assert output == tmp_path


def test_backtest_command_targets_economic_runner(tmp_path):
    cmd, output = build_command(
        context("backtest", workspace_root=str(tmp_path))
    )
    assert cmd[1].endswith("tools/run_economic_objective_campaigns.py")
    assert "--no-start-collection" in cmd
    assert output == tmp_path


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


def test_economic_run_materializes_then_backtests_in_same_unit(tmp_path):
    calls = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    out = run_one_unit(
        context(
            "backtest",
            workspace_root=str(tmp_path),
            start_ts_ms=1,
            end_ts_ms=2,
        ),
        runner=runner,
    )
    assert out.status == "COMPLETE"
    assert out.progressed is True
    assert len(calls) == 2
    assert "hl_observer.ops.v2_dataset_bridge" in calls[0]
    assert calls[1][1].endswith("tools/run_economic_objective_campaigns.py")
    assert out.payload["safe_workspace"] == str(tmp_path)


def test_materialization_failure_blocks_economic_run(tmp_path):
    calls = []

    class Result:
        returncode = 2
        stdout = ""
        stderr = "DATASET_V2_NO_GO"

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        return Result()

    out = run_one_unit(
        context("module_pnl_proof", workspace_root=str(tmp_path)),
        runner=runner,
    )
    assert out.status == "FAILED"
    assert out.payload["reason"] == "dataset_materialization_failed"
    assert len(calls) == 1def test_economic_materialization_and_backtest_run_in_same_unit(tmp_path):
    calls=[]
    class Result:
        returncode=0
        stdout='ok'
        stderr=''
    def runner(cmd, **kwargs):
        calls.append(cmd)
        return Result()
    workspace=tmp_path/'economic'
    out=run_one_unit(
        context('backtest', workspace_root=str(workspace)),
        runner=runner,
    )
    assert out.status=='COMPLETE'
    assert out.progressed is True
    assert len(calls)==2
    assert "hl_observer.ops.v2_dataset_bridge" in calls[0]
    assert calls[1][1].endswith("tools/run_economic_objective_campaigns.py")
    assert (workspace/'.alina_campaign_materialized').is_file()
