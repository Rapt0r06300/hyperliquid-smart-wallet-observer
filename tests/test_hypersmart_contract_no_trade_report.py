import pytest
import json
from pathlib import Path
from hyper_smart_observer.copy_mode.no_trade_report import generate_markdown_report, decision_from_reason
from hyper_smart_observer.copy_mode.copy_models import NoTradeDecision, NoTradeReason

def test_generate_markdown_report():
    decisions = [
        decision_from_reason(
            reason=NoTradeReason.EDGE_REMAINING_TOO_LOW,
            observed="Edge de 4 bps < 8 bps",
            leader_wallet="0x1111111111111111111111111111111111111111",
            coin="BTC"
        )
    ]
    report = generate_markdown_report(decisions)
    assert "# Rapport No-Trade" in report
    assert "EDGE_REMAINING_TOO_LOW" in report
    assert "0x1111111111111111111111111111111111111111" in report
