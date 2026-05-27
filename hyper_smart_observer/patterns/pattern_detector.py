from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class PatternResult:
    wallet: str
    pattern_type: str
    confidence: float
    evidence_count: int
    pnl_association: float | None
    risk_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pattern_id: str = field(default_factory=lambda: str(uuid4()))
    research_only_message: str = "research only; historical pattern is not future profit"


class PatternDetector:
    def __init__(self, min_evidence: int = 10) -> None:
        self.min_evidence = min_evidence

    def detect_from_pnls(self, wallet: str, pnls: list[float], *, min_evidence: int | None = None) -> list[PatternResult]:
        min_evidence = min_evidence or self.min_evidence
        if len(pnls) < min_evidence:
            return [
                PatternResult(
                    wallet=wallet,
                    pattern_type="INSUFFICIENT_DATA",
                    confidence=0.0,
                    evidence_count=len(pnls),
                    pnl_association=None,
                    warnings=["not enough evidence for pattern detection"],
                )
            ]
        wins = [value for value in pnls if value > 0]
        winrate = len(wins) / len(pnls)
        pattern_type = "POSITIVE_CLOSED_PNL_CLUSTER" if winrate > 0.55 else "MIXED_RESULTS"
        return [
            PatternResult(
                wallet=wallet,
                pattern_type=pattern_type,
                confidence=min(0.95, len(pnls) / (min_evidence * 2)),
                evidence_count=len(pnls),
                pnl_association=sum(pnls),
                risk_flags=[] if winrate > 0.55 else ["weak_pnl_association"],
            )
        ]
