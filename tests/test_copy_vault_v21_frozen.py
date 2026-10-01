from __future__ import annotations

import copy

import pytest

from hl_observer.backtesting import copy_vault_v21_frozen as V21
from hl_observer.simulation.economic_freeze_registry import parameter_hash


def _freeze() -> dict:
    params = {
        "protocol": V21.PROTOCOL,
        "training_selection_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "minimum_leader_fill_notional_usd": 100.0,
        "signed_depth_imbalance_minimum": 0.0,
        "core_notional_usd": 600.0,
        "probe_notional_usd": 75.0,
        "daily_profit_lock_usd": 4.0,
        "stop_loss_bps": 50.0,
        "take_profit_bps": 100.0,
        "horizon_ms": 3_600_000,
        "vault_daily_limit": 1,
        "coin_daily_limit": 1,
        "max_open_positions": 10,
        "bonferroni_trial_count": 432,
        "bounds": {
            "validation_start_ms": 1_000,
            "validation_end_ms": 2_000,
            "oos_start_ms": 3_000,
            "oos_end_ms": 4_000,
        },
    }
    return {
        "freeze": {
            "schema_version": "hypersmart.economic_parameter_freeze.v1",
            "campaign_id": "frozen",
            "family": "copy_vault",
            "frozen_at_ms": 5_000,
            "selected_before_final_evaluation": True,
            "parameters": params,
            "parameters_sha256": parameter_hash(params),
            "dataset_provenance": {},
        }
    }


def _segment(name: str, eligible: bool) -> dict:
    return {
        "segment": name,
        "status": "PASS" if eligible else "FAIL",
        "eligible": eligible,
        "heldout_evaluated": True,
        "retuned_on_heldout": False,
        "paper_read_only": True,
        "real_execution": False,
        "carry_pnl_usd": 0.0,
    }


def test_frozen_v21_opens_heldouts_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake(*_args, segment: str, **_kwargs):
        calls.append(segment)
        return _segment(segment, segment == "validation")

    monkeypatch.setattr(V21, "_evaluate_segment", fake)
    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert calls == ["validation", "oos"]
    assert report["validation"]["eligible"] is True
    assert report["oos"]["eligible"] is False
    assert report["forward"]["status"] == "BLOCKED_BY_OOS"
    assert report["forward"]["heldout_evaluated"] is False
    assert report["objective_status"] == "NON_PROUVE"
    assert report["carry_pnl_usd"] == 0.0


def test_frozen_v21_never_opens_oos_after_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake(*_args, segment: str, **_kwargs):
        calls.append(segment)
        return _segment(segment, False)

    monkeypatch.setattr(V21, "_evaluate_segment", fake)
    report = V21.evaluate_frozen_v21([], {}, _freeze())

    assert calls == ["validation"]
    assert report["oos"]["status"] == "BLOCKED_BY_VALIDATION"
    assert report["oos"]["heldout_evaluated"] is False
    assert report["forward"]["heldout_evaluated"] is False


def test_frozen_v21_rejects_parameter_tampering() -> None:
    payload = _freeze()
    tampered = copy.deepcopy(payload)
    tampered["freeze"]["parameters"]["core_notional_usd"] = 999.0
    with pytest.raises(ValueError, match="FREEZE_HASH_MISMATCH"):
        V21.evaluate_frozen_v21([], {}, tampered)
