from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.utils.math import clamp
from hl_observer.wallets.leaderboard_models import LeaderboardCandidate
from hl_observer.wallets.leaderboard_validation import is_full_wallet_address


class CopyLeaderAutoSelectConfig(BaseModel):
    top_n: int = 50
    min_history_days: int = 7
    min_score: float = 60.0
    max_drawdown_pct: float = 35.0
    min_consistency_score: float = 55.0
    max_pnl_concentration: float = 0.65
    require_positive_pnl: bool = True
    require_positive_roi: bool = False


class CopyLeaderSelection(BaseModel):
    wallet_address: str
    rank: int | None = None
    source: str = "leaderboard"
    accepted: bool
    score: float
    history_days: float | None = None
    consistency_score: float
    execution_quality_score: float
    pnl_concentration: float | None = None
    max_drawdown_pct: float | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CopyLeaderAutoSelectReport(BaseModel):
    target_leaders: int
    candidates_seen: int
    accepted: list[CopyLeaderSelection] = Field(default_factory=list)
    rejected: list[CopyLeaderSelection] = Field(default_factory=list)
    dry_run: bool = True
    mode: str = "PAPER_MOCK_USDC_ONLY"

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)


def select_copy_leaders(
    candidates: list[LeaderboardCandidate],
    *,
    config: CopyLeaderAutoSelectConfig | None = None,
) -> CopyLeaderAutoSelectReport:
    cfg = config or CopyLeaderAutoSelectConfig()
    accepted: list[CopyLeaderSelection] = []
    rejected: list[CopyLeaderSelection] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: item.leaderboard_score, reverse=True):
        address = candidate.wallet_address.lower()
        if address in seen:
            continue
        seen.add(address)
        selection = evaluate_copy_leader_candidate(candidate, config=cfg)
        if selection.accepted and len(accepted) < cfg.top_n:
            accepted.append(selection)
        else:
            if selection.accepted:
                selection = selection.model_copy(
                    update={"accepted": False, "reasons": [*selection.reasons, "outside_top_n"]}
                )
            rejected.append(selection)
    return CopyLeaderAutoSelectReport(
        target_leaders=cfg.top_n,
        candidates_seen=len(candidates),
        accepted=accepted,
        rejected=rejected,
    )


def evaluate_copy_leader_candidate(
    candidate: LeaderboardCandidate,
    *,
    config: CopyLeaderAutoSelectConfig | None = None,
    max_drawdown_pct: float | None = None,
    pnl_concentration: float | None = None,
    consistency_score: float | None = None,
    execution_quality_score: float | None = None,
) -> CopyLeaderSelection:
    cfg = config or CopyLeaderAutoSelectConfig()
    reasons: list[str] = []
    warnings: list[str] = []
    address = candidate.wallet_address.lower()
    if not is_full_wallet_address(address):
        return _selection(candidate, address, False, 0.0, 0.0, 0.0, None, None, ["invalid_or_truncated_address"], warnings)

    history_days = infer_history_days(candidate.period)
    if history_days is None:
        warnings.append("history_days_unknown")
    elif history_days < cfg.min_history_days:
        reasons.append("history_window_too_short")

    if cfg.require_positive_pnl and candidate.pnl_usdc is not None and candidate.pnl_usdc <= 0:
        reasons.append("leaderboard_pnl_not_positive")
    if cfg.require_positive_roi and candidate.roi_pct is not None and candidate.roi_pct <= 0:
        reasons.append("leaderboard_roi_not_positive")

    if max_drawdown_pct is not None and max_drawdown_pct > cfg.max_drawdown_pct:
        reasons.append("drawdown_too_high")
    if pnl_concentration is not None and pnl_concentration > cfg.max_pnl_concentration:
        reasons.append("pnl_too_concentrated")
    if pnl_concentration is None:
        warnings.append("pnl_concentration_unverified")
    if max_drawdown_pct is None:
        warnings.append("drawdown_unverified")

    consistency = consistency_score if consistency_score is not None else estimate_consistency_score(candidate)
    execution_quality = execution_quality_score if execution_quality_score is not None else estimate_execution_quality(candidate)
    if consistency < cfg.min_consistency_score:
        reasons.append("consistency_score_too_low")

    final_score = clamp(
        0.40 * candidate.leaderboard_score
        + 0.25 * consistency
        + 0.15 * execution_quality
        + 0.10 * (candidate.source_confidence or 50.0)
        + 0.10 * _history_score(history_days, cfg.min_history_days),
        0.0,
        100.0,
    )
    if final_score < cfg.min_score:
        reasons.append("copy_leader_score_below_minimum")

    accepted = not reasons
    if accepted:
        reasons.append("accepted_for_paper_copy_research")
    return _selection(
        candidate,
        address,
        accepted,
        final_score,
        consistency,
        execution_quality,
        pnl_concentration,
        max_drawdown_pct,
        reasons,
        warnings,
        history_days=history_days,
    )


def infer_history_days(period: str | None) -> float | None:
    normalized = (period or "").strip().upper()
    if normalized.endswith("D"):
        try:
            return float(normalized[:-1])
        except ValueError:
            return None
    if normalized in {"ALL", "TOTAL"}:
        return None
    return None


def estimate_consistency_score(candidate: LeaderboardCandidate) -> float:
    roi_component = 50.0 if candidate.roi_pct is None else clamp(50.0 + candidate.roi_pct, 0.0, 100.0)
    pnl_component = 50.0 if candidate.pnl_usdc is None else clamp(50.0 + candidate.pnl_usdc / 100_000.0 * 30.0, 0.0, 100.0)
    score_component = clamp(candidate.leaderboard_score, 0.0, 100.0)
    return clamp(0.35 * score_component + 0.35 * roi_component + 0.30 * pnl_component, 0.0, 100.0)


def estimate_execution_quality(candidate: LeaderboardCandidate) -> float:
    if candidate.volume_usdc is None:
        return 55.0
    return clamp(45.0 + candidate.volume_usdc / 5_000_000.0 * 55.0, 0.0, 100.0)


def _history_score(history_days: float | None, min_history_days: int) -> float:
    if history_days is None:
        return 55.0
    return clamp(history_days / max(1, min_history_days) * 100.0, 0.0, 100.0)


def _selection(
    candidate: LeaderboardCandidate,
    address: str,
    accepted: bool,
    score: float,
    consistency_score: float,
    execution_quality_score: float,
    pnl_concentration: float | None,
    max_drawdown_pct: float | None,
    reasons: list[str],
    warnings: list[str],
    *,
    history_days: float | None = None,
) -> CopyLeaderSelection:
    return CopyLeaderSelection(
        wallet_address=address,
        rank=candidate.rank,
        accepted=accepted,
        score=score,
        history_days=history_days,
        consistency_score=consistency_score,
        execution_quality_score=execution_quality_score,
        pnl_concentration=pnl_concentration,
        max_drawdown_pct=max_drawdown_pct,
        reasons=reasons,
        warnings=warnings,
    )
