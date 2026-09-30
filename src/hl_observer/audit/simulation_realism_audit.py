from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


REQUIRED_LEDGER_FIELDS = {
    "starting_balance_usdc",
    "cash_balance_usdc",
    "realized_pnl_usdc",
    "unrealized_pnl_usdc",
    "fees_paid_usdc",
    "funding_net_usdc",
    "equity_usdc",
    "drawdown_usdc",
    "positions",
    "event_count",
    "reconciliation",
}


@dataclass(frozen=True, slots=True)
class SimulationRealismAuditResult:
    ok: bool
    findings: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def audit_paper_ledger_snapshot(snapshot: dict[str, Any]) -> SimulationRealismAuditResult:
    findings: list[str] = []
    warnings: list[str] = []

    missing = sorted(REQUIRED_LEDGER_FIELDS.difference(snapshot))
    if missing:
        findings.append("MISSING_LEDGER_FIELDS:" + ",".join(missing))

    reconciliation = snapshot.get("reconciliation")
    if not isinstance(reconciliation, dict):
        findings.append("MISSING_RECONCILIATION_OBJECT")
    elif not reconciliation.get("ok", False):
        findings.append("PNL_RECONCILIATION_FAILED")

    if "positions" in snapshot and not isinstance(snapshot["positions"], dict):
        findings.append("POSITIONS_NOT_STRUCTURED")

    event_count = int(snapshot.get("event_count") or 0)
    if event_count <= 0:
        warnings.append("NO_PAPER_EVENTS_YET")

    for numeric_field in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "funding_net_usdc",
        "equity_usdc",
        "drawdown_usdc",
    ):
        try:
            float(snapshot.get(numeric_field))
        except (TypeError, ValueError):
            findings.append(f"NON_NUMERIC_FIELD:{numeric_field}")

    return SimulationRealismAuditResult(
        ok=not findings,
        findings=tuple(findings),
        warnings=tuple(warnings),
    )


__all__ = ["REQUIRED_LEDGER_FIELDS", "SimulationRealismAuditResult", "audit_paper_ledger_snapshot"]
