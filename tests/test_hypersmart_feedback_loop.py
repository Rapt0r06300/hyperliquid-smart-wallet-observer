from __future__ import annotations

from hyper_smart_observer.intelligence.feedback_loop import SimulationFeedback, apply_simulation_feedback
from hyper_smart_observer.wallet_universe.wallet_universe import WalletUniverseEntry


def test_feedback_promotes_positive_simulation_wallet() -> None:
    entry = WalletUniverseEntry(wallet_address="0x" + "1" * 40, scan_priority=10.0)

    updated = apply_simulation_feedback(entry, SimulationFeedback(entry.wallet_address, virtual_net_pnl=12.0, accepted_signals=3, rejected_signals=1))

    assert updated.scan_priority > 10.0
    assert updated.copyability_score == 10.0
    assert updated.status == "WARM_SCAN"
    assert "positive_virtual_pnl" in updated.simulation_result_summary


def test_feedback_retrogrades_negative_simulation_wallet_and_marks_late() -> None:
    entry = WalletUniverseEntry(wallet_address="0x" + "2" * 40, scan_priority=10.0)

    updated = apply_simulation_feedback(
        entry,
        SimulationFeedback(entry.wallet_address, virtual_net_pnl=-8.0, accepted_signals=2, rejected_signals=3, detected_late_count=2),
    )

    assert updated.status == "WATCH_ONLY"
    assert "NEGATIVE_SIMULATION_RESULT" in updated.risk_flags
    assert "DETECTED_TOO_LATE" in updated.risk_flags
    assert "negative_virtual_pnl" in updated.simulation_result_summary
