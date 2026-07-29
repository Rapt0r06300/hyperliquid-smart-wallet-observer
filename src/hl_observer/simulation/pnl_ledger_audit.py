"""Semantic audit for canonical local paper-ledger events.

Hash integrity proves that rows were not silently changed.  This module proves
the complementary property: the rows describe a coherent position lifecycle
and one unambiguous PnL equation.  It never rewrites historical evidence.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from hl_observer.simulation.ledger_integrity import verify_chain

TRUSTED = "TRUSTED"
CONTAMINATED = "CONTAMINATED"
UNMEASURABLE = "UNMEASURABLE"


@dataclass(frozen=True, slots=True)
class PnlAuditIssue:
    code: str
    event_seq: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class PnlLedgerAudit:
    status: str
    pnl_valid: bool
    events_checked: int
    realized_pnl_usdc: float | None
    fees_paid_usdc: float | None
    funding_net_usdc: float | None
    unrealized_pnl_usdc: float | None
    recalculated_equity_usdc: float | None
    recalculated_net_pnl_usdc: float | None
    open_positions: dict[str, float]
    issues: tuple[PnlAuditIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def audit_paper_ledger(
    events: Iterable[Mapping[str, Any]],
    *,
    snapshot: Mapping[str, Any] | None = None,
    tolerance_usdc: float = 0.0001,
) -> PnlLedgerAudit:
    """Validate OPEN/ADD/REDUCE/CLOSE, costs, funding and position identity.

    A contaminated history returns ``None`` for recalculated PnL.  Callers must
    not publish the former value as audited PnL, but the raw evidence remains
    untouched for diagnosis.
    """

    rows = [dict(row) for row in events]
    issues: list[PnlAuditIssue] = []
    if not rows:
        if snapshot is not None:
            starting = _snapshot_number(snapshot, "starting_balance_usdc")
            realized = _snapshot_number(snapshot, "realized_pnl_usdc")
            unrealized = _snapshot_number(snapshot, "unrealized_pnl_usdc")
            fees = _snapshot_number(snapshot, "fees_paid_usdc")
            funding = _snapshot_number(snapshot, "funding_net_usdc")
            equity = _snapshot_number(snapshot, "equity_usdc")
            if None not in (starting, realized, unrealized, fees, funding, equity):
                assert starting is not None
                assert realized is not None
                assert unrealized is not None
                assert fees is not None
                assert funding is not None
                assert equity is not None
                expected = starting + realized + unrealized - fees + funding
                if abs(equity - expected) <= tolerance_usdc:
                    return PnlLedgerAudit(
                        status=TRUSTED,
                        pnl_valid=True,
                        events_checked=0,
                        realized_pnl_usdc=realized,
                        fees_paid_usdc=fees,
                        funding_net_usdc=funding,
                        unrealized_pnl_usdc=unrealized,
                        recalculated_equity_usdc=round(expected, 10),
                        recalculated_net_pnl_usdc=round(expected - starting, 10),
                        open_positions={},
                        issues=(),
                    )
        return PnlLedgerAudit(
            status=UNMEASURABLE,
            pnl_valid=False,
            events_checked=0,
            realized_pnl_usdc=None,
            fees_paid_usdc=None,
            funding_net_usdc=None,
            unrealized_pnl_usdc=None,
            recalculated_equity_usdc=None,
            recalculated_net_pnl_usdc=None,
            open_positions={},
            issues=(PnlAuditIssue("NO_LEDGER_EVENTS", None, "Aucun événement canonique disponible."),),
        )

    try:
        verify_chain(rows)
    except (TypeError, ValueError) as exc:
        issues.append(PnlAuditIssue("LEDGER_CHAIN_INVALID", None, str(exc)))

    positions: dict[str, float] = {}
    fee_ids: set[str] = set()
    realized = 0.0
    fees = 0.0
    funding = 0.0

    for index, row in enumerate(rows, start=1):
        seq = _optional_int(row.get("event_seq")) or index
        event_type = _token(row.get("event_type"))
        quantity = _finite(row.get("quantity"))
        refs = row.get("refs") if isinstance(row.get("refs"), dict) else {}
        position_id = str(refs.get("position_id") or _position_key(row.get("coin"), row.get("side")))

        if event_type == "PAPERFEECHARGED":
            fee = _finite(row.get("fee_usdc"))
            if fee is None or fee < 0:
                issues.append(PnlAuditIssue("FEE_INVALID", seq, "Frais absents, négatifs ou non finis."))
            else:
                fees += fee
                fee_ids.add(str(row.get("event_id") or ""))
            continue

        if event_type in {"PAPERFUNDINGCHARGED", "PAPERFUNDINGRECEIVED"}:
            amount = _finite(row.get("funding_usdc"))
            if amount is None:
                issues.append(PnlAuditIssue("FUNDING_INVALID", seq, "Funding absent ou non fini."))
            elif event_type == "PAPERFUNDINGCHARGED" and amount > 0:
                issues.append(PnlAuditIssue("FUNDING_SIGN_CONTRADICTION", seq, "Funding charged positif."))
            elif event_type == "PAPERFUNDINGRECEIVED" and amount < 0:
                issues.append(PnlAuditIssue("FUNDING_SIGN_CONTRADICTION", seq, "Funding received négatif."))
            else:
                funding += amount
            continue

        if event_type in {"PAPERPARTIALFILL", "PAPERFILLSIMULATED"}:
            if quantity is None or quantity <= 0:
                issues.append(PnlAuditIssue("FILL_QUANTITY_INVALID", seq, "Fill sans quantité positive."))
            requested = _finite(refs.get("requested_quantity"))
            if requested is not None and quantity is not None and quantity > requested + 1e-12:
                issues.append(
                    PnlAuditIssue("PARTIAL_FILL_EXCEEDS_REQUEST", seq, "Fill supérieur à la demande.")
                )
            continue

        if event_type not in {
            "PAPERPOSITIONOPENED",
            "PAPERPOSITIONINCREASED",
            "PAPERPOSITIONREDUCED",
            "PAPERPOSITIONCLOSED",
        }:
            continue

        if quantity is None or quantity <= 0:
            issues.append(
                PnlAuditIssue("POSITION_QUANTITY_INVALID", seq, "Quantité de position non positive.")
            )
            continue
        if not row.get("coin") or _token(row.get("side")) not in {"LONG", "SHORT"}:
            issues.append(PnlAuditIssue("POSITION_IDENTITY_INVALID", seq, "Coin ou sens absent/invalide."))
            continue

        event_fee = _finite(row.get("fee_usdc"))
        if event_fee is not None and event_fee > 0:
            fee_event_id = str(refs.get("fee_event_id") or "")
            if refs.get("fee_accounting") != "SEPARATE_EVENT" or fee_event_id not in fee_ids:
                issues.append(
                    PnlAuditIssue(
                        "AMBIGUOUS_FEE_ATTRIBUTION",
                        seq,
                        "Le frais de position n'est pas relié à un événement de frais autoritaire.",
                    )
                )

        current = positions.get(position_id)
        if event_type == "PAPERPOSITIONOPENED":
            if current is not None:
                issues.append(PnlAuditIssue("DUPLICATE_OPEN", seq, f"Position déjà ouverte: {position_id}."))
            else:
                positions[position_id] = quantity
        elif event_type == "PAPERPOSITIONINCREASED":
            if current is None:
                issues.append(PnlAuditIssue("ADD_WITHOUT_OPEN", seq, f"ADD sans OPEN: {position_id}."))
            else:
                positions[position_id] = current + quantity
        else:
            pnl = _finite(row.get("realized_pnl_usdc"))
            if pnl is None:
                issues.append(PnlAuditIssue("REALIZED_PNL_MISSING", seq, "PnL réalisé absent/non fini."))
            else:
                realized += pnl
            if current is None:
                issues.append(
                    PnlAuditIssue("CLOSE_WITHOUT_OPEN", seq, f"Sortie sans position: {position_id}.")
                )
                continue
            if quantity > current + 1e-12:
                issues.append(
                    PnlAuditIssue("REDUCE_EXCEEDS_POSITION", seq, f"Sortie > position: {position_id}.")
                )
                continue
            remaining = current - quantity
            if event_type == "PAPERPOSITIONCLOSED":
                if remaining > 1e-12:
                    issues.append(
                        PnlAuditIssue("CLOSE_QUANTITY_MISMATCH", seq, f"CLOSE partiel: {position_id}.")
                    )
                positions.pop(position_id, None)
            elif remaining <= 1e-12:
                issues.append(
                    PnlAuditIssue(
                        "REDUCE_EMPTIES_POSITION", seq, f"REDUCE aurait dû être CLOSE: {position_id}."
                    )
                )
                positions.pop(position_id, None)
            else:
                positions[position_id] = remaining

    unrealized = _snapshot_number(snapshot, "unrealized_pnl_usdc")
    starting = _snapshot_number(snapshot, "starting_balance_usdc")
    actual_equity = _snapshot_number(snapshot, "equity_usdc")
    if snapshot is not None:
        _compare_snapshot(issues, snapshot, "realized_pnl_usdc", realized, tolerance_usdc)
        _compare_snapshot(issues, snapshot, "fees_paid_usdc", fees, tolerance_usdc)
        _compare_snapshot(issues, snapshot, "funding_net_usdc", funding, tolerance_usdc)
    recalculated_equity = None
    recalculated_net = None
    if starting is not None and unrealized is not None:
        recalculated_equity = starting + realized + unrealized - fees + funding
        recalculated_net = recalculated_equity - starting
        if actual_equity is not None and abs(actual_equity - recalculated_equity) > tolerance_usdc:
            issues.append(
                PnlAuditIssue(
                    "EQUITY_RECONCILIATION_MISMATCH",
                    None,
                    f"equity={actual_equity:.10f}, attendu={recalculated_equity:.10f}",
                )
            )

    if issues:
        return PnlLedgerAudit(
            status=CONTAMINATED,
            pnl_valid=False,
            events_checked=len(rows),
            realized_pnl_usdc=None,
            fees_paid_usdc=None,
            funding_net_usdc=None,
            unrealized_pnl_usdc=None,
            recalculated_equity_usdc=None,
            recalculated_net_pnl_usdc=None,
            open_positions=dict(sorted(positions.items())),
            issues=tuple(issues),
        )
    return PnlLedgerAudit(
        status=TRUSTED,
        pnl_valid=True,
        events_checked=len(rows),
        realized_pnl_usdc=round(realized, 10),
        fees_paid_usdc=round(fees, 10),
        funding_net_usdc=round(funding, 10),
        unrealized_pnl_usdc=unrealized,
        recalculated_equity_usdc=None if recalculated_equity is None else round(recalculated_equity, 10),
        recalculated_net_pnl_usdc=None if recalculated_net is None else round(recalculated_net, 10),
        open_positions=dict(sorted(positions.items())),
        issues=(),
    )


def _compare_snapshot(
    issues: list[PnlAuditIssue],
    snapshot: Mapping[str, Any],
    field: str,
    expected: float,
    tolerance: float,
) -> None:
    actual = _snapshot_number(snapshot, field)
    if actual is None:
        issues.append(PnlAuditIssue("SNAPSHOT_FIELD_MISSING", None, f"Champ absent/non fini: {field}."))
    elif abs(actual - expected) > tolerance:
        issues.append(
            PnlAuditIssue(
                "SNAPSHOT_COMPONENT_MISMATCH",
                None,
                f"{field}={actual:.10f}, attendu={expected:.10f}",
            )
        )


def _snapshot_number(snapshot: Mapping[str, Any] | None, field: str) -> float | None:
    if snapshot is None:
        return None
    return _finite(snapshot.get(field))


def _position_key(coin: object, side: object) -> str:
    return f"{str(coin or '').upper()}:{str(side or '').upper()}"


def _token(value: object) -> str:
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "CONTAMINATED",
    "TRUSTED",
    "UNMEASURABLE",
    "PnlAuditIssue",
    "PnlLedgerAudit",
    "audit_paper_ledger",
]
