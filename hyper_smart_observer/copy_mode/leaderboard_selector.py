from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_models import (
    LeaderCandidateInput,
    LeaderRejectReason,
    LeaderShortlistEntry,
    LeaderStatus,
    LeaderboardShortlistReport,
    to_jsonable,
    utc_now,
)

FULL_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class LeaderboardSelectionConfig:
    target_count: int = 5
    min_history_days: float = 7.0
    min_closed_pnl_points: int = 10
    max_drawdown_pct: float = 35.0
    max_pnl_concentration: float = 0.65
    one_big_win_threshold: float = 0.75
    min_consistency_score: float = 60.0
    min_score: float = 65.0


def is_full_wallet_address(address: str) -> bool:
    return bool(FULL_ADDRESS_RE.fullmatch((address or "").strip()))


def select_leaderboard_shortlist(
    candidates: list[LeaderCandidateInput],
    *,
    config: LeaderboardSelectionConfig | None = None,
) -> LeaderboardShortlistReport:
    cfg = config or LeaderboardSelectionConfig()
    entries = [evaluate_leader_candidate(candidate, config=cfg) for candidate in candidates]
    shortlisted = [entry for entry in entries if entry.status == LeaderStatus.SHORTLISTED]
    shortlisted = sorted(shortlisted, key=lambda entry: entry.score, reverse=True)
    accepted_addresses = {entry.wallet_address for entry in shortlisted[: cfg.target_count]}
    normalized_entries: list[LeaderShortlistEntry] = []
    for entry in entries:
        if entry.status == LeaderStatus.SHORTLISTED and entry.wallet_address not in accepted_addresses:
            normalized_entries.append(
                LeaderShortlistEntry(
                    **{
                        **entry.__dict__,
                        "status": LeaderStatus.WATCH_ONLY,
                        "warnings": [*entry.warnings, "outside_target_count_watch_only"],
                    }
                )
            )
        else:
            normalized_entries.append(entry)
    normalized_entries.sort(key=lambda item: (item.status != LeaderStatus.SHORTLISTED, -item.score))
    return LeaderboardShortlistReport(
        generated_at=utc_now(),
        target_count=cfg.target_count,
        candidates_seen=len(candidates),
        entries=normalized_entries,
    )


def evaluate_leader_candidate(
    candidate: LeaderCandidateInput,
    *,
    config: LeaderboardSelectionConfig | None = None,
) -> LeaderShortlistEntry:
    cfg = config or LeaderboardSelectionConfig()
    address = (candidate.wallet_address or "").strip().lower()
    reasons: list[str] = []
    warnings = list(candidate.warnings)
    if "..." in address:
        reasons.append(LeaderRejectReason.TRUNCATED_ADDRESS_REJECTED.value)
    elif not is_full_wallet_address(address):
        reasons.append(LeaderRejectReason.INVALID_ADDRESS_REJECTED.value)

    if candidate.history_days is None or candidate.history_days < cfg.min_history_days:
        reasons.append(LeaderRejectReason.INSUFFICIENT_HISTORY.value)
    if candidate.closed_pnl_points < cfg.min_closed_pnl_points:
        reasons.append(LeaderRejectReason.INSUFFICIENT_CLOSED_PNL.value)

    pnl_concentration = calculate_pnl_concentration(
        candidate.max_single_trade_pnl,
        candidate.total_closed_pnl,
    )
    if pnl_concentration is None:
        warnings.append("pnl_concentration_unmeasured")
    elif pnl_concentration > cfg.max_pnl_concentration:
        reasons.append(LeaderRejectReason.PNL_CONCENTRATION_TOO_HIGH.value)
    if pnl_concentration is not None and pnl_concentration > cfg.one_big_win_threshold:
        reasons.append(LeaderRejectReason.ONE_BIG_WIN_RISK.value)

    consistency = candidate.consistency_score if candidate.consistency_score is not None else 0.0
    if consistency < cfg.min_consistency_score:
        reasons.append(LeaderRejectReason.LOW_CONSISTENCY.value)
    if candidate.max_drawdown_pct is not None and candidate.max_drawdown_pct > cfg.max_drawdown_pct:
        reasons.append(LeaderRejectReason.MAX_DRAWDOWN_TOO_HIGH.value)
    elif candidate.max_drawdown_pct is None:
        warnings.append("drawdown_unmeasured")

    score = _candidate_score(candidate, pnl_concentration)
    status = LeaderStatus.SHORTLISTED if not reasons and score >= cfg.min_score else LeaderStatus.REJECTED
    if not reasons and score < cfg.min_score:
        reasons.append("LEADER_SCORE_TOO_LOW")
    if candidate.closed_pnl_points == 0 or candidate.history_days is None:
        status = LeaderStatus.INSUFFICIENT_DATA if reasons else status
    return LeaderShortlistEntry(
        wallet_address=address,
        status=status,
        score=score,
        source=candidate.source,
        rank=candidate.rank,
        history_days=candidate.history_days,
        closed_pnl_points=candidate.closed_pnl_points,
        pnl_concentration=pnl_concentration,
        consistency_score=candidate.consistency_score,
        max_drawdown_pct=candidate.max_drawdown_pct,
        refusal_reasons=reasons,
        warnings=warnings,
    )


def calculate_pnl_concentration(max_single_trade_pnl: float | None, total_closed_pnl: float | None) -> float | None:
    if max_single_trade_pnl is None or total_closed_pnl is None or total_closed_pnl == 0:
        return None
    return min(1.0, abs(max_single_trade_pnl) / abs(total_closed_pnl))


def write_shortlist_report(report: LeaderboardShortlistReport, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def load_shortlist_entries(path: Path) -> list[LeaderShortlistEntry]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    return [
        LeaderShortlistEntry(
            wallet_address=item["wallet_address"],
            status=LeaderStatus(item["status"]),
            score=float(item["score"]),
            source=item.get("source", "leaderboard"),
            rank=item.get("rank"),
            history_days=item.get("history_days"),
            closed_pnl_points=int(item.get("closed_pnl_points") or 0),
            pnl_concentration=item.get("pnl_concentration"),
            consistency_score=item.get("consistency_score"),
            max_drawdown_pct=item.get("max_drawdown_pct"),
            refusal_reasons=list(item.get("refusal_reasons") or []),
            warnings=list(item.get("warnings") or []),
        )
        for item in entries
    ]


def _candidate_score(candidate: LeaderCandidateInput, pnl_concentration: float | None) -> float:
    consistency = candidate.consistency_score or 0.0
    stability = candidate.per_coin_stability_score or 50.0
    execution = candidate.execution_quality_score or 50.0
    confidence = candidate.sample_confidence or 0.0
    copyability = candidate.copyability_score or 50.0
    concentration_penalty = 0.0 if pnl_concentration is None else pnl_concentration * 30.0
    drawdown_penalty = 0.0 if candidate.max_drawdown_pct is None else min(30.0, candidate.max_drawdown_pct * 0.4)
    return max(
        0.0,
        min(
            100.0,
            0.28 * consistency
            + 0.18 * stability
            + 0.18 * execution
            + 0.20 * confidence
            + 0.16 * copyability
            - concentration_penalty
            - drawdown_penalty,
        ),
    )
