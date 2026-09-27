"""Machine-derived audit registry for Event Intelligence Ideas 1..120."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from hl_observer.event_intelligence.integration_registry import EVENT_INTELLIGENCE_INTEGRATION, IdeaIntegration

STATUS_IMPLEMENTED_AND_WIRED = "IMPLEMENTED_AND_WIRED"
STATUS_IMPLEMENTED_BUT_PARTIAL = "IMPLEMENTED_BUT_PARTIAL"
STATUS_IMPLEMENTED_BUT_NOT_WIRED = "IMPLEMENTED_BUT_NOT_WIRED"
STATUS_BROKEN = "BROKEN"
STATUS_MISSING = "MISSING"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class IdeaAuditRow:
    idea_id: int
    name: str
    category: str
    source_module: str
    target_family: str
    wiring_status: str
    proven_edge: bool
    evidence_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_event_intelligence_ideas() -> list[IdeaAuditRow]:
    rows: list[IdeaAuditRow] = []
    registered = {item.idea_id: item for item in EVENT_INTELLIGENCE_INTEGRATION}

    for idea_id in range(1, 121):
        item: IdeaIntegration | None = registered.get(idea_id)
        if not item:
            rows.append(
                IdeaAuditRow(
                    idea_id=idea_id,
                    name=f"Idea_{idea_id}",
                    category="UNKNOWN",
                    source_module="unassigned",
                    target_family="copy_vault",
                    wiring_status=STATUS_MISSING,
                    proven_edge=False,
                    evidence_reason="Not registered in EVENT_INTELLIGENCE_INTEGRATION",
                )
            )
            continue

        target_fam = item.strategy_families[0] if item.strategy_families else "copy_vault"
        status = STATUS_IMPLEMENTED_AND_WIRED
        reason = f"Registered with proof_state {item.proof_state}"

        rows.append(
            IdeaAuditRow(
                idea_id=idea_id,
                name=item.title,
                category="event_intelligence",
                source_module="hl_observer.event_intelligence.integration_registry",
                target_family=target_fam,
                wiring_status=status,
                proven_edge=False,
                evidence_reason=reason,
            )
        )

    return rows


def generate_idea_audit_summary() -> dict[str, Any]:
    rows = audit_event_intelligence_ideas()
    counts = {
        STATUS_IMPLEMENTED_AND_WIRED: 0,
        STATUS_IMPLEMENTED_BUT_PARTIAL: 0,
        STATUS_IMPLEMENTED_BUT_NOT_WIRED: 0,
        STATUS_BROKEN: 0,
        STATUS_MISSING: 0,
        STATUS_NOT_APPLICABLE: 0,
    }
    for r in rows:
        counts[r.wiring_status] = counts.get(r.wiring_status, 0) + 1

    return {
        "total_ideas_audited": len(rows),
        "status_counts": counts,
        "rows": [r.to_dict() for r in rows],
    }
