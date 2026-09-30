from __future__ import annotations

import importlib.util
from pathlib import Path

from hl_observer.experimental.runner import LEAD_LAG_EXPERIMENTAL_LANE
from hl_observer.runtime.lead_lag_event_runtime import LANE_ID


ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("collecter_bbo_final", ROOT / "tools" / "collecter_bbo.py")
BBO = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(BBO)


def test_strict_event_and_experimental_calibration_lead_lag_lanes_are_never_merged():
    assert LANE_ID == "LEAD_LAG_STRICT_EVENT"
    assert LEAD_LAG_EXPERIMENTAL_LANE == "LEAD_LAG_EXP_CALIBRATION"
    assert LANE_ID != LEAD_LAG_EXPERIMENTAL_LANE


def test_bbo_coverage_includes_every_coin_from_valid_frozen_lead_lag_config(tmp_path, monkeypatch):
    config = tmp_path / BBO.LEAD_LAG_CONFIG_REL
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{}", encoding="utf-8")

    import hl_observer.backtesting.lead_lag_evidence as evidence

    monkeypatch.setattr(
        evidence,
        "load_frozen_evidence",
        lambda path: {"coins": ["DOGE", "XRP", "doge"]},
    )
    coins = BBO.coins_couverture(tmp_path, k=0)

    assert set(BBO.MAJORS_BBO).issubset(coins)
    assert "DOGE" in coins
    assert "XRP" in coins
    assert coins.count("DOGE") == 1


def test_invalid_frozen_lead_lag_config_never_expands_bbo_coverage(tmp_path, monkeypatch):
    config = tmp_path / BBO.LEAD_LAG_CONFIG_REL
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("{}", encoding="utf-8")

    import hl_observer.backtesting.lead_lag_evidence as evidence

    def invalid(_path):
        raise ValueError("invalid frozen evidence")

    monkeypatch.setattr(evidence, "load_frozen_evidence", invalid)
    assert BBO.coins_couverture(tmp_path, k=0) == list(BBO.MAJORS_BBO)
