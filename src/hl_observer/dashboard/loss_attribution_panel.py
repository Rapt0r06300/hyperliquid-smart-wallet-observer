from __future__ import annotations

from typing import Any

from hl_observer.analysis.negative_pnl_auditor import V19NegativePnlAudit, audit_to_dict


def build_loss_attribution_panel(audit: V19NegativePnlAudit) -> dict[str, Any]:
    payload = audit_to_dict(audit)
    return {
        "title": "Loss attribution",
        "pnl_snapshot": {
            "net_pnl_usdc": audit.net_pnl_usdc,
            "snapshot_net_pnl_usdc": audit.snapshot_net_pnl_usdc,
            "snapshot_current_equity_usdt": audit.snapshot_current_equity_usdt,
            "snapshot_status": audit.snapshot_status,
        },
        "loss_attribution": {
            "coins": payload["losing_coins"],
            "wallets": payload["losing_wallets"],
            "actions": payload["losing_actions"],
            "reasons": payload["losing_reasons"],
        },
        "risk_decision": payload["risk_decision"],
        "recommendations": payload["recommendations"],
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["build_loss_attribution_panel"]
