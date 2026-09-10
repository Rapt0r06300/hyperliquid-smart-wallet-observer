import json
from pathlib import Path

from hl_observer.research.research_context import build_research_context


def test_context_auto_selects_underworked_family_and_stays_compact(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    memory = tmp_path / "memory.jsonl"
    memory.write_text("", encoding="utf-8")
    context = build_research_context(tmp_path, family=None, ledger_path=ledger, process_memory_path=memory)
    assert context["family"] in {"copy_vault", "lead_lag", "cross_venue_dislocation_v2"}
    assert context["head"] == "UNKNOWN"
    assert context["next_actions"]
    assert len(json.dumps(context, separators=(",", ":"))) < 8000
    assert context["network_io"] is False
