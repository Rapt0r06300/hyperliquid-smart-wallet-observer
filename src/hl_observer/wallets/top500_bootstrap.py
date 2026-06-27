from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from hl_observer.config.settings import Settings
from hl_observer.storage.models import (
    ExplorerWalletCandidate,
    LeaderboardWalletCandidate,
    TopWallet,
    TopWalletSource,
    WalletBootstrapRun,
)
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_models import LeaderboardCandidate
from hl_observer.wallets.top_wallet_ranker import RankedTopWallet, rank_top_wallets


class Top500BootstrapResult(BaseModel):
    target_wallets: int = 500
    candidates_seen: int = 0
    wallets_selected: int = 0
    truncated_rejected: int = 0
    selected_wallets: list[RankedTopWallet] = Field(default_factory=list)
    status: str = "INCOMPLETE"
    dry_run: bool = True
    notes: list[str] = Field(default_factory=list)


def bootstrap_top_wallets(
    settings: Settings,
    *,
    session: Session,
    target: int = 500,
    source: str = "leaderboard",
    store: bool = False,
    dry_run: bool = True,
) -> Top500BootstrapResult:
    session.flush()
    rows = session.query(LeaderboardWalletCandidate).order_by(
        LeaderboardWalletCandidate.leaderboard_score.desc()
    ).limit(settings.wallet_bootstrap.max_candidates_total).all()
    candidates = [
        LeaderboardCandidate(
            wallet_address=row.wallet_address,
            rank=row.rank,
            period=row.period,
            account_value_usdc=row.account_value_usdc,
            pnl_usdc=row.pnl_usdc,
            roi_pct=row.roi_pct,
            volume_usdc=row.volume_usdc,
            leaderboard_score=row.leaderboard_score,
            source_confidence=row.source_confidence,
        )
        for row in rows
    ]
    if source in {"all", "explorer", "hyperliquid_explorer"}:
        known = {candidate.wallet_address for candidate in candidates}
        explorer_rows = session.query(ExplorerWalletCandidate).order_by(
            ExplorerWalletCandidate.activity_score.desc()
        ).limit(settings.wallet_bootstrap.max_candidates_total).all()
        for row in explorer_rows:
            if row.wallet_address in known:
                continue
            known.add(row.wallet_address)
            candidates.append(
                LeaderboardCandidate(
                    wallet_address=row.wallet_address,
                    rank=None,
                    period="EXPLORER",
                    account_value_usdc=None,
                    pnl_usdc=None,
                    roi_pct=None,
                    volume_usdc=None,
                    leaderboard_score=row.activity_score,
                    source_confidence=80.0,
                )
            )
    selected = rank_top_wallets(candidates, target=target, min_score=settings.wallet_bootstrap.min_bootstrap_score)
    status = "COMPLETE" if len(selected) >= target else "INCOMPLETE"
    result = Top500BootstrapResult(
        target_wallets=target,
        candidates_seen=len(candidates),
        wallets_selected=len(selected),
        selected_wallets=selected,
        status=status,
        dry_run=dry_run,
        notes=[
            "leaderboard_prioritaire",
            "top500_honnete_incomplet_si_moins_de_wallets",
        ],
    )
    if not dry_run and store:
        run = WalletBootstrapRun(
            started_at_ms=now_ms(),
            finished_at_ms=now_ms(),
            target_wallets=target,
            source=source,
            status=status,
            candidates_seen=len(candidates),
            wallets_selected=len(selected),
            truncated_rejected=0,
            notes=";".join(result.notes),
        )
        session.add(run)
        for item in selected:
            session.add(
                TopWallet(
                    wallet_address=item.wallet_address,
                    rank=item.rank,
                    source=source,
                    score=item.score,
                    selected_at_ms=now_ms(),
                    status="selected",
                    notes=";".join(item.reasons),
                )
            )
            session.add(
                TopWalletSource(
                    wallet_address=item.wallet_address,
                    source=source,
                    source_rank=item.rank,
                    source_score=item.score,
                    created_at_ms=now_ms(),
                )
            )
    return result


def format_top500_report(result: Top500BootstrapResult) -> str:
    lines = [
        "top 500 bootstrap report",
        f"target: {result.target_wallets}",
        f"candidats vus: {result.candidates_seen}",
        f"wallets selectionnes: {result.wallets_selected}",
        f"statut: {result.status}",
        f"dry-run: {result.dry_run}",
    ]
    if result.wallets_selected < result.target_wallets:
        lines.append("Top 500 incomplet honnetement: moins de wallets complets exploitables disponibles.")
    for wallet in result.selected_wallets[:10]:
        lines.append(f"- {wallet.wallet_address} rank={wallet.rank} score={wallet.score:.1f}")
    return "\n".join(lines)
