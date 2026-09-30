from __future__ import annotations

from datetime import datetime, timezone

try:  # Python 3.11+
    from datetime import UTC
except ImportError:  # Python 3.10 compat
    UTC = timezone.utc
from typing import Any


def build_refactor_fusion_dashboard_payload(
    *,
    loss_panel: dict[str, Any],
    copy_wallet_panel: dict[str, Any],
    arbitrage_panel: dict[str, Any],
    funding_panel: dict[str, Any],
    source_labels: list[str],
    extra_panels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk_blocks = []
    no_trade_reasons: list[str] = []
    for row in copy_wallet_panel.get("rows", []):
        no_trade_reasons.extend(row.get("no_trade_reasons", []) or [])
        risk_blocks.extend((row.get("risk_decision") or {}).get("blocking_codes", []) or [])
    for row in arbitrage_panel.get("rows", []):
        no_trade_reasons.extend(row.get("reason_codes", []) or [])
        risk_blocks.extend(((row.get("risk_decision") or {}).get("blocking_codes", []) or []))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pnl_snapshot": loss_panel.get("pnl_snapshot", {}),
        "loss_attribution": loss_panel.get("loss_attribution", {}),
        "wallet_copy_candidates": copy_wallet_panel.get("rows", []),
        "arbitrage_opportunities": arbitrage_panel.get("rows", []),
        "funding_signals": funding_panel.get("rows", []),
        "risk_blocks": list(dict.fromkeys(str(item) for item in risk_blocks if item)),
        "no_trade_reasons": list(dict.fromkeys(str(item) for item in no_trade_reasons if item)),
        "paper_intents": [
            row.get("paper_intent")
            for row in copy_wallet_panel.get("rows", [])
            if row.get("paper_intent") is not None
        ],
        "source_labels": source_labels,
        "safety_status": {
            "paper_only": True,
            "real_execution": False,
            "external_order": False,
            "signature": False,
            "private_key": False,
        },
    }
    if extra_panels:
        payload["extra_panels"] = dict(extra_panels)
    return payload


__all__ = ["build_refactor_fusion_dashboard_payload"]
