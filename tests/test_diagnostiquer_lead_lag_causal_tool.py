from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "diagnostiquer_lead_lag_causal.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("diagnostiquer_lead_lag_causal_tested", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_rest_read_only_and_keeps_8bps_diagnostic_separate_from_20bps_economic() -> None:
    module = _load_tool()

    assert module.DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert module.ECONOMIC_SHOCK_THRESHOLD_BPS == 20.0
    text = TOOL.read_text(encoding="utf-8")
    assert "SOURCE_COVERAGE_AUTOPSY_NOT_ECONOMIC_SELECTION" in text
    assert "threshold_bps=DIAGNOSTIC_SHOCK_THRESHOLD_BPS" in text
    assert "threshold_bps=ECONOMIC_SHOCK_THRESHOLD_BPS" in text
    assert "real_execution" not in text or "False" in text


def test_markdown_explicitly_refuses_absence_equals_gap() -> None:
    module = _load_tool()
    payload = {
        "diagnostic_only": True,
        "diagnostic_shock_threshold_bps": 8.0,
        "economic_shock_threshold_bps_unchanged": 20.0,
        "max_executable_book_delay_ms": 750,
        "event_count": 1,
        "conclusive_event_count": 1,
        "executable_event_count": 0,
        "first_book_delay_p50_ms": 2295.0,
        "first_book_delay_p95_ms": 2295.0,
        "classification_counts": {"CAUSAL_BOOK_TOO_LATE": 1},
        "events": [
            {
                "trigger_ts_ms": 1_800_000_000_000,
                "lead_shock_bps": 8.5,
                "classification": "CAUSAL_BOOK_TOO_LATE",
                "first_causal_book_ts_ms": 1_800_000_002_295,
                "first_causal_book_delay_ms": 2295.0,
                "explicit_gap_evidence": False,
            }
        ],
    }

    markdown = module._render_markdown(payload)
    assert "une absence de carnet ne prouve jamais à elle seule un gap collecteur" in markdown
    assert "CAUSAL_BOOK_TOO_LATE" in markdown
    assert "2295.0" in markdown
