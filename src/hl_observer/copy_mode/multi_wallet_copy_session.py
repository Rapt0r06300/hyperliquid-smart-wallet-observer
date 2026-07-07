"""Multi-wallet mirror session orchestrator for local paper simulation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from hl_observer.copy_mode.wallet_mirror_runtime import MirrorCandidate
from hl_observer.paper_trading.mirror_paper_executor import MirrorPaperExecutionConfig, MirrorPaperExecutionResult, execute_mirror_candidate_paper
from hl_observer.paper_trading.paper_connector import PaperSimConnector
from hl_observer.signals.copy_conflict_resolver import resolve_copy_conflicts


@dataclass(frozen=True, slots=True)
class MultiWalletSessionConfig:
    min_same_side_leaders: int = 2
    max_positions_per_run: int = 4
    execution: MirrorPaperExecutionConfig = field(default_factory=MirrorPaperExecutionConfig)


@dataclass(frozen=True, slots=True)
class MultiWalletSessionResult:
    accepted: tuple[MirrorPaperExecutionResult, ...]
    rejected: tuple[dict[str, object], ...]
    groups_seen: int
    paper_only: bool = True
    external_action: bool = False


def run_multi_wallet_copy_session(
    candidates: list[MirrorCandidate],
    *,
    equity_usdt: float,
    mids: dict[str, float],
    books: dict[str, dict[str, tuple[tuple[float, float], ...]]] | None = None,
    observed_at_ms: int,
    connector: PaperSimConnector | None = None,
    config: MultiWalletSessionConfig | None = None,
) -> MultiWalletSessionResult:
    cfg = config or MultiWalletSessionConfig()
    paper_connector = connector or PaperSimConnector()
    books = books or {}
    grouped: dict[tuple[str, str], list[MirrorCandidate]] = defaultdict(list)
    rejected: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.reason_codes:
            rejected.append({"candidate_id": candidate.candidate_id, "reason_codes": list(candidate.reason_codes)})
            continue
        grouped[(candidate.coin, candidate.side)].append(candidate)

    accepted: list[MirrorPaperExecutionResult] = []
    for (_coin, _side), rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(accepted) >= cfg.max_positions_per_run:
            for candidate in rows:
                rejected.append({"candidate_id": candidate.candidate_id, "reason_codes": ["MAX_POSITIONS_PER_RUN"]})
            continue
        conflict = resolve_copy_conflicts(rows, min_same_side_leaders=cfg.min_same_side_leaders)
        if not conflict.accepted:
            for candidate in rows:
                rejected.append({"candidate_id": candidate.candidate_id, "reason_codes": list(conflict.reason_codes)})
            continue
        leader = max(rows, key=lambda item: (item.wallet_score, item.copyability_score, item.confidence))
        mid = float(mids.get(leader.coin, leader.leader_price) or leader.leader_price)
        book = books.get(leader.coin, {})
        result = execute_mirror_candidate_paper(
            leader,
            equity_usdt=equity_usdt,
            mid_price=mid,
            top_depth_usdt=None,
            asks=tuple(book.get("asks", ())),
            bids=tuple(book.get("bids", ())),
            observed_at_ms=observed_at_ms,
            connector=paper_connector,
            config=cfg.execution,
        )
        if result.accepted:
            accepted.append(result)
        else:
            rejected.append({"candidate_id": leader.candidate_id, "reason_codes": list(result.reason_codes)})
    return MultiWalletSessionResult(
        accepted=tuple(accepted),
        rejected=tuple(rejected),
        groups_seen=len(grouped),
    )


__all__ = ["MultiWalletSessionConfig", "MultiWalletSessionResult", "run_multi_wallet_copy_session"]
