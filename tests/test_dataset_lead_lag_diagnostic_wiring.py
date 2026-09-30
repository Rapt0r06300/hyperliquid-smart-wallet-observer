from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "run_dataset_economic_campaigns.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("dataset_economic_diag_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CanonicalFake:
    @staticmethod
    def detect_rolling_shocks(trades, *args, **kwargs):
        del trades, args
        threshold = float(kwargs.get("threshold_bps", 20.0))
        return [
            {
                "trigger_ts_ms": 1_800_000_000_000 + int(threshold),
                "lead_shock_bps": threshold,
                "direction": 1,
            }
        ]

    @staticmethod
    def load_market_microstructure_event_windows(root, event_ts_ms, **kwargs):
        del root, kwargs
        events = list(event_ts_ms)
        trigger = 1_800_000_000_008
        return (
            {
                "ETH": [
                    {
                        "ts_ms": trigger - 50,
                        "connection_id": "same",
                        "sequence": 10,
                        "gap_count": 0,
                        "reconnect_count": 0,
                        "data_gate_ready": True,
                    },
                    {
                        "ts_ms": trigger + 2_295,
                        "connection_id": "same",
                        "sequence": 11,
                        "gap_count": 0,
                        "reconnect_count": 0,
                        "data_gate_ready": True,
                    },
                ]
            },
            {},
            {"requested": events},
        )

    @staticmethod
    def replay_lead_lag_queue_maker(tape, l2_history, public_trade_history, **kwargs):
        del tape, l2_history, public_trade_history, kwargs
        return {
            "parameters": {"shock_threshold_bps": 20.0, "max_book_delay_ms": 750},
            "strong_shocks_seen": 0,
        }


def test_full_cold_diagnostic_expands_windows_without_changing_economic_threshold() -> None:
    tool = _load_tool()
    overrides = tool._lead_lag_diagnostic_overrides(_CanonicalFake)

    economic = overrides["detect_rolling_shocks"]([], threshold_bps=20.0)
    assert economic[0]["lead_shock_bps"] == 20.0

    books, trades, meta = overrides["load_market_microstructure_event_windows"](
        Path("."),
        [economic[0]["trigger_ts_ms"]],
    )
    assert trades == {}
    assert meta["economic_event_count_requested"] == 1
    assert meta["diagnostic_event_count_8bps"] == 1
    assert meta["diagnostic_shock_threshold_bps"] == 8.0
    assert meta["economic_parameters_changed"] is False
    assert 1_800_000_000_008 in meta["requested"]

    replay = overrides["replay_lead_lag_queue_maker"]({}, books, {})
    diagnostic = replay["causal_gap_diagnostic"]
    assert diagnostic["economic_shock_threshold_bps"] == 20.0
    assert diagnostic["economic_shocks_seen"] == 0
    assert diagnostic["diagnostic_shocks_seen"] == 1
    assert diagnostic["events"][0]["classification"] == (
        "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    )
    assert diagnostic["strategy_parameters_changed"] is False
    assert diagnostic["paper_read_only"] is True
    assert diagnostic["real_execution"] is False
