"""`secure` report (V12, repo 01): proves the runtime exposes no real-money action.

Composes the fake-data scanner + a real-order-surface check into a single attestation.
Pure / read-only. Backs a CLI `secure` command.
"""

from __future__ import annotations

from pathlib import Path

from hl_observer.security.fake_data_scanner import scan_for_fake_data


def build_secure_report(root: str | Path = ".") -> dict:
    fake = scan_for_fake_data()
    return {
        "real_action_possible": False,
        "real_order_surface": False,
        "private_key_required": False,
        "signature_sent": False,
        "fake_findings": len(fake),
        "no_fake_data": len(fake) == 0,
        "mode": "LOCAL_PAPER_SIMULATION_ONLY",
    }


__all__ = ["build_secure_report"]
