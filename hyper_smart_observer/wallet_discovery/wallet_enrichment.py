from __future__ import annotations

from dataclasses import replace

from hyper_smart_observer.wallet_discovery.candidate_sources import WalletCandidate, WalletCandidateStatus


def enrich_candidate(candidate: WalletCandidate, *, observed_notional: float | None = None, observed_closed_pnl: float | None = None) -> WalletCandidate:
    score = candidate.candidate_score
    if observed_notional:
        score += min(30.0, observed_notional / 10_000.0)
    if observed_closed_pnl and observed_closed_pnl > 0:
        score += min(40.0, observed_closed_pnl / 1_000.0)
    return replace(
        candidate,
        observed_notional=observed_notional,
        observed_closed_pnl=observed_closed_pnl,
        candidate_score=min(100.0, score),
        status=WalletCandidateStatus.ENRICHED,
    )
