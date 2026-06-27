from __future__ import annotations

from dataclasses import dataclass

from hl_observer.scanner.scanner_models import ScanTier


@dataclass(slots=True)
class ScanJobPlan:
    tier: ScanTier
    interval_seconds: int
    max_wallets: int
    network_read_required: bool
    description: str


def default_scan_schedule() -> list[ScanJobPlan]:
    return [
        ScanJobPlan(
            tier=ScanTier.COLD,
            interval_seconds=24 * 60 * 60,
            max_wallets=500,
            network_read_required=False,
            description="Discovery/import/scoring pass. Builds candidate pool and shortlist.",
        ),
        ScanJobPlan(
            tier=ScanTier.WARM,
            interval_seconds=300,
            max_wallets=3,
            network_read_required=True,
            description="Bounded /info read-only snapshot pass for top prioritized leaders.",
        ),
        ScanJobPlan(
            tier=ScanTier.HOT,
            interval_seconds=15,
            max_wallets=10,
            network_read_required=True,
            description="Read-only WebSocket watch for shortlist users and public trade discovery.",
        ),
    ]

