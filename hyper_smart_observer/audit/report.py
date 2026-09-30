from __future__ import annotations

from hyper_smart_observer.audit.safety_audit import AuditFinding


def format_audit_findings(findings: list[AuditFinding]) -> str:
    return "\n".join(f"{'OK' if finding.ok else 'FAIL'} {finding.name}: {finding.message}" for finding in findings)
