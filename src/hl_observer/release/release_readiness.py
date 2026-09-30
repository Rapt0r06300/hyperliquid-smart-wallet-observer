"""Release readiness go/no-go (V12 capability M/U).

Single verdict composing the existing safety checks into one report:
  * NO FAKE — fake_data_scanner finds zero fabricated-data generators in the runtime;
  * SAFETY — run_safety_audit passes (no real-order surface, mainnet disabled, etc.);
  * DOCS — the V12 state docs are present.
Pure / read-only: reads the repo and aggregates booleans; never an order, never a fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.security.fake_data_scanner import scan_for_fake_data
from hl_observer.security.safety_audit import run_safety_audit

# CORRIGE (audit 2026-07-11) : les docs V12 ont ete SUPPRIMES volontairement lors de la
# consolidation documentaire (640 fichiers -> 7, commit 35703aa). Exiger des fichiers morts
# rendait le repo eternellement "non pret". On exige desormais les docs qui existent VRAIMENT
# et qui portent la doctrine.
_REQUIRED_DOCS = (
    "CLAUDE.md",                          # les regles (no-real-trade, verite des donnees)
    "OBJECTIF.md",                        # l'objectif
    "docs/ETAT_ET_FEUILLE_DE_ROUTE.md",   # le document maitre
    "docs/ARCHITECTURE.md",               # l'architecture + installation
)


@dataclass(frozen=True, slots=True)
class ReleaseReadiness:
    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    fake_findings: int = 0

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": dict(self.checks),
            "blockers": list(self.blockers),
            "fake_findings": self.fake_findings,
        }


def check_release_readiness(root: str | Path = ".") -> ReleaseReadiness:
    root = Path(root)
    checks: dict[str, bool] = {}
    blockers: list[str] = []

    fake = scan_for_fake_data()
    checks["no_fake_data"] = len(fake) == 0
    if fake:
        blockers.append(f"fake-data generators detected: {len(fake)}")

    audit = run_safety_audit(root)
    checks["safety_audit_ok"] = bool(audit.ok)
    if not audit.ok:
        blockers.extend(f"safety: {f}" for f in audit.findings)

    missing_docs = [d for d in _REQUIRED_DOCS if not (root / d).exists()]
    checks["required_docs_present"] = not missing_docs
    blockers.extend(f"missing doc: {d}" for d in missing_docs)

    return ReleaseReadiness(
        ready=all(checks.values()),
        checks=checks,
        blockers=tuple(blockers),
        fake_findings=len(fake),
    )


__all__ = ["ReleaseReadiness", "check_release_readiness"]
