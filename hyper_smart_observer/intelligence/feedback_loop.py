from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.wallet_universe.wallet_universe import WalletUniverseEntry


@dataclass(slots=True)
class SimulationFeedback:
    wallet_address: str
    virtual_net_pnl: float
    accepted_signals: int
    rejected_signals: int
    detected_late_count: int = 0


def apply_simulation_feedback(entry: WalletUniverseEntry, feedback: SimulationFeedback) -> WalletUniverseEntry:
    if feedback.virtual_net_pnl > 0 and feedback.accepted_signals > 0:
        entry.scan_priority += min(25.0, feedback.virtual_net_pnl / 2.0)
        entry.copyability_score = min(100.0, entry.copyability_score + 10.0)
        entry.status = "WARM_SCAN"
        entry.simulation_result_summary = f"positive_virtual_pnl={feedback.virtual_net_pnl:.4f}"
    elif feedback.virtual_net_pnl < 0:
        entry.scan_priority = max(0.0, entry.scan_priority - min(25.0, abs(feedback.virtual_net_pnl) / 2.0))
        entry.risk_flags.append("NEGATIVE_SIMULATION_RESULT")
        entry.status = "WATCH_ONLY"
        entry.simulation_result_summary = f"negative_virtual_pnl={feedback.virtual_net_pnl:.4f}"
    if feedback.detected_late_count > 0:
        entry.risk_flags.append("DETECTED_TOO_LATE")
        entry.scan_priority += min(10.0, feedback.detected_late_count * 2.0)
    return entry
