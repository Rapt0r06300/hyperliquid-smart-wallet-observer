from hl_observer.agent_tools.schemas import SCHEMAS, validate
from hl_observer.agent_tools.jsonl_adapter import from_jsonl, to_jsonl
from hl_observer.screeners.presets import get_preset, list_presets
from hl_observer.clitools.tui_status import render_status


def test_schema_validates_decision_and_rejects_bad_type():
    ok, errs = validate({"accepted": True, "reason": "x", "context_only": True}, SCHEMAS["decision"])
    assert ok and errs == []
    ok2, errs2 = validate({"accepted": "yes", "reason": "x"}, SCHEMAS["decision"])
    assert not ok2 and "missing:context_only" in errs2 and "type:accepted" in errs2


def test_jsonl_roundtrip():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    assert from_jsonl(to_jsonl(rows)) == rows


def test_screener_presets_are_threshold_only():
    assert "fresh_liquid" in list_presets()
    p = get_preset("conservative")
    assert p["min_edge_bps"] == 22.0 and "order" not in p


def test_tui_status_is_readonly_and_shows_zero_real_orders():
    out = render_status({"mode": "LIVE", "ws_connected": True, "open_positions": 3, "paper_pnl_usdc": 12.5})
    assert "real orders     : 0" in out
    assert "ON" in out
