"""Compact monitor output for launcher/dashboard status."""

from __future__ import annotations


def build_monitor_output(*, status: str, wallets: int, signals: int, accepted: int, rejected: int, pnl_usdt: float) -> dict[str, object]:
    return {
        "status": str(status),
        "wallets": int(wallets),
        "signals": int(signals),
        "accepted": int(accepted),
        "rejected": int(rejected),
        "pnl_usdt": round(float(pnl_usdt or 0.0), 8),
        "paper_only": True,
        "external_action": False,
    }


__all__ = ["build_monitor_output"]
