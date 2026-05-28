import pytest
from hyper_smart_observer.copy_mode.no_trade_report import decision_from_reason
from hyper_smart_observer.copy_mode.copy_models import NoTradeReason

@pytest.mark.contract
def test_contract_no_trade_report_french_explanations():
    """
    Contract: Each refusal reason must have a French explanation.
    """
    # Test a few key reasons
    reasons = [
        NoTradeReason.STALE_SIGNAL,
        NoTradeReason.EDGE_REMAINING_TOO_LOW,
        NoTradeReason.LIQUIDITY_TOO_LOW
    ]

    for reason in reasons:
        decision = decision_from_reason(reason, observed="test")
        # Check why_not_simulable and next_action as they contain the human readable parts
        assert decision.why_not_simulable, f"Contract: Reason {reason} must have a 'why_not_simulable' explanation"

        # Check if it looks like French (basic check on a few words)
        french_words = ["le", "la", "est", "pas", "de", "du", "pour", "ne", "que"]
        combined_text = (decision.why_not_simulable + " " + decision.next_action).lower()
        assert any(word in combined_text for word in french_words), \
            f"Contract: Explanation for {reason} should be in French"
