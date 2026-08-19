from __future__ import annotations

import importlib
import json

import pytest

import hl_observer.ops.lead_lag_evidence as lead_lag_evidence
from hl_observer.funding.funding_reconciliation import (
    cumulative_drift_alert,
    funding_drift_exit,
    reconcile_funding,
)


@pytest.mark.parametrize(
    "module_name",
    [
        "hl_observer.analysis.opening_profitability",
        "hl_observer.optimization.grid_search",
        "hl_observer.optimization.hypothesis_engine",
        "hl_observer.optimization.profit_report",
        "hl_observer.optimization.random_search",
        "hl_observer.optimization.strategy_tournament",
        "hl_observer.optimization.walk_forward_validator",
        "hl_observer.simulation.action_loss_diagnostics",
        "hl_observer.simulation.coin_loss_diagnostics",
        "hl_observer.simulation.cost_drag_diagnostics",
        "hl_observer.simulation.edge_distribution_diagnostics",
        "hl_observer.simulation.logs_analyzer",
        "hl_observer.simulation.position_matching_diagnostics",
        "hl_observer.simulation.profitability_diagnostics",
        "hl_observer.simulation.refusal_breakdown",
        "hl_observer.simulation.root_cause_from_logs",
        "hl_observer.simulation.stale_signal_diagnostics",
        "hl_observer.simulation.timing_distribution_diagnostics",
        "hl_observer.simulation.wallet_loss_diagnostics",
        "hl_observer.gateway",
        "hl_observer.monitoring",
        "hl_observer.universe",
        "hl_observer.signals.decisions",
    ],
)
def test_compatibility_modules_import_without_side_effect(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module is not None
    assert module.__name__ == module_name


def test_reconcile_funding_requires_actual_and_aggregates_pairs() -> None:
    assert reconcile_funding([{"pair_id": "a", "amount_usdc": 1}], []) == {
        "status": "INSUFFICIENT_ACTUAL_PAYMENTS",
        "pairs": 0,
    }

    result = reconcile_funding(
        [
            {"pair_id": "a", "amount_usdc": 1.0},
            {"pair_id": "a", "amount_usdc": 2.0},
            {"pair_id": "b", "amount_usdc": 1.0},
            {"amount_usdc": 999},
            "ignored",
        ],
        [
            {"pair_id": "a", "amount_usdc": 2.5},
            {"pair_id": "c", "amount_usdc": 0.5},
            None,
        ],
    )
    assert result["status"] == "OK"
    assert result["pairs"] == 3
    assert result["total_predicted_usdc"] == 4.0
    assert result["total_actual_usdc"] == 3.0
    assert result["total_abs_error_usdc"] == 2.0
    assert result["mean_abs_pct_error"] == 0.5
    assert [row["pair_id"] for row in result["rows"]] == ["a", "b", "c"]

    no_prediction = reconcile_funding([], [{"pair_id": "a", "amount_usdc": 1.0}])
    assert no_prediction["mean_abs_pct_error"] is None


def test_funding_drift_exit_reversal_collapse_and_still_pays() -> None:
    assert funding_drift_exit(2.0, -1.0) == {"exit": True, "reason": "FUNDING_REVERSED"}
    assert funding_drift_exit(2.0, -1.0, reversal_guard=False) == {
        "exit": False,
        "reason": "FUNDING_STILL_PAYS",
    }
    assert funding_drift_exit(2.0, 0.1) == {"exit": True, "reason": "FUNDING_EDGE_COLLAPSED"}
    assert funding_drift_exit(2.0, 1.0) == {"exit": False, "reason": "FUNDING_STILL_PAYS"}
    assert funding_drift_exit(0.0, 1.0) == {"exit": False, "reason": "FUNDING_STILL_PAYS"}


def test_cumulative_funding_drift_alert_all_branches() -> None:
    assert cumulative_drift_alert(None) == {"alert": False, "reason": "NO_RECONCILIATION"}
    assert cumulative_drift_alert({"status": "NOPE"}) == {"alert": False, "reason": "NO_RECONCILIATION"}

    bad = cumulative_drift_alert(
        {"status": "OK", "total_abs_error_usdc": 1.0, "mean_abs_pct_error": 0.1},
        max_abs_error_usdc=0.5,
    )
    assert bad["alert"] is True and bad["reason"] == "FUNDING_MODEL_DRIFT"

    bad_mape = cumulative_drift_alert(
        {"status": "OK", "total_abs_error_usdc": 0.1, "mean_abs_pct_error": 0.8},
        max_mape=0.5,
    )
    assert bad_mape["alert"] is True

    good = cumulative_drift_alert(
        {"status": "OK", "total_abs_error_usdc": 0.1, "mean_abs_pct_error": None},
    )
    assert good == {
        "alert": False,
        "reason": "WITHIN_TOLERANCE",
        "abs_error_usdc": 0.1,
        "mape": None,
    }


def test_lead_lag_coin_parser_is_normalized_and_deduplicated() -> None:
    assert lead_lag_evidence._coins(" eth, BTC,eth ,, sol ") == ["BTC", "ETH", "SOL"]


def test_lead_lag_main_without_freeze_writes_public_evidence(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(lead_lag_evidence, "charger_tape", lambda root: {"BTC": [], "ETH": [], "DOGE": []})
    monkeypatch.setattr(
        lead_lag_evidence,
        "backtest",
        lambda *args, **kwargs: {"statut": "MORE_DATA", "events": 12},
    )
    freeze_called = {"value": False}

    def _freeze(*args, **kwargs):
        freeze_called["value"] = True
        return {"promotion_status": "PROMOTED"}

    monkeypatch.setattr(lead_lag_evidence, "geler_config", _freeze)
    output = tmp_path / "nested" / "evidence.json"
    rc = lead_lag_evidence.main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--control-coins",
            "DOGE",
            "--minimum-events",
            "0",
        ]
    )
    assert rc == 0
    assert freeze_called["value"] is False
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["analysis"]["statut"] == "MORE_DATA"
    assert payload["frozen_evidence"] is None
    assert payload["coins"] == ["BTC", "ETH"]
    assert payload["control_coins"] == ["DOGE"]
    assert payload["local_data_only"] is True
    assert payload["real_execution"] is False
    assert "status=MORE_DATA" in capsys.readouterr().out


def test_lead_lag_main_freeze_uses_requested_coins_and_minimum_one(tmp_path, monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(lead_lag_evidence, "charger_tape", lambda root: {"BTC": []})

    def _backtest(root, **kwargs):
        captured["backtest"] = kwargs
        return {"statut": "READY"}

    def _freeze(root, **kwargs):
        captured["freeze"] = kwargs
        return {"promotion_status": "PROMOTED"}

    monkeypatch.setattr(lead_lag_evidence, "backtest", _backtest)
    monkeypatch.setattr(lead_lag_evidence, "geler_config", _freeze)
    output = tmp_path / "evidence.json"
    assert lead_lag_evidence.main(
        [
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--coins",
            "ETH,BTC,ETH",
            "--control-coins",
            "XRP,DOGE",
            "--minimum-events",
            "0",
            "--shock-bps",
            "3.5",
            "--cost-bps",
            "4.5",
            "--freeze",
        ]
    ) == 0
    assert captured["backtest"]["min_chocs"] == 1
    assert captured["freeze"]["minimum_events"] == 1
    assert captured["freeze"]["coins"] == ["BTC", "ETH"]
    assert captured["freeze"]["coins_controle"] == ["DOGE", "XRP"]
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["frozen_evidence"]["promotion_status"] == "PROMOTED"
