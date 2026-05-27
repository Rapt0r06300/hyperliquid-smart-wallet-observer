from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from hl_observer.config.settings import Settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.repositories import DiscoveryRepository
from hl_observer.wallets.discovery_filters import dedupe_candidates
from hl_observer.wallets.discovery_scoring import (
    WalletCandidateScore,
    WalletDiscoveryDecision,
    score_discovery_candidate,
)
from hl_observer.wallets.discovery_sources import (
    WalletDiscoveryCandidate,
    WalletDiscoverySourceResult,
    build_discovery_sources,
)


class WalletDiscoveryPlan(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["all"])
    coins: list[str] = Field(default_factory=lambda: ["ANY"])
    include_altcoins: bool = True
    max_candidates: int = 200
    max_coins_per_wallet: int = 20
    min_altcoin_liquidity_score: float = 0.0
    max_candidates_per_source: int = 50
    min_discovery_score: float = 55.0
    require_positive_pnl: bool = True
    require_positive_roi: bool = False
    allow_incomplete_external_metrics: bool = True
    store: bool = False
    dry_run: bool = True
    backfill_selected: bool = False
    backfill_limit: int = 10
    report: bool = False
    json_output: bool = False


class ScoredWalletCandidate(BaseModel):
    candidate: WalletDiscoveryCandidate
    score: WalletCandidateScore
    selected_for_backfill: bool = False


class WalletDiscoveryResult(BaseModel):
    run_id: int | None = None
    sources_attempted: int = 0
    source_results: list[WalletDiscoverySourceResult] = Field(default_factory=list)
    candidates_found: int = 0
    candidates_after_filter: int = 0
    candidates_positive_pnl: int = 0
    candidates_positive_roi: int = 0
    selected_wallets: list[ScoredWalletCandidate] = Field(default_factory=list)
    selected_by_coin: dict[str, int] = Field(default_factory=dict)
    top_wallets_by_coin: dict[str, list[str]] = Field(default_factory=dict)
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    errors_count: int = 0
    state: str = "idle"
    notes: list[str] = Field(default_factory=list)


def build_wallet_discovery_plan(
    settings: Settings,
    *,
    sources: list[str] | None = None,
    coins: list[str] | None = None,
    include_altcoins: bool = True,
    max_candidates: int | None = None,
    min_discovery_score: float | None = None,
    require_positive_pnl: bool | None = None,
    require_positive_roi: bool | None = None,
    store: bool = False,
    dry_run: bool = True,
    backfill_selected: bool = False,
    backfill_limit: int | None = None,
    min_altcoin_liquidity_score: float = 0.0,
    max_coins_per_wallet: int = 20,
    report: bool = False,
    json_output: bool = False,
) -> WalletDiscoveryPlan:
    discovery = settings.wallet_discovery
    return WalletDiscoveryPlan(
        sources=sources or discovery.sources,
        coins=[coin.upper() for coin in (coins or ["ANY"])],
        include_altcoins=include_altcoins,
        max_candidates=max_candidates or discovery.max_total_candidates,
        max_coins_per_wallet=max_coins_per_wallet,
        min_altcoin_liquidity_score=min_altcoin_liquidity_score,
        max_candidates_per_source=discovery.max_candidates_per_source,
        min_discovery_score=(
            discovery.min_discovery_score if min_discovery_score is None else min_discovery_score
        ),
        require_positive_pnl=(
            discovery.require_positive_pnl if require_positive_pnl is None else require_positive_pnl
        ),
        require_positive_roi=(
            discovery.require_positive_roi if require_positive_roi is None else require_positive_roi
        ),
        allow_incomplete_external_metrics=discovery.allow_incomplete_external_metrics,
        store=store,
        dry_run=dry_run,
        backfill_selected=backfill_selected,
        backfill_limit=backfill_limit or discovery.max_wallets_to_backfill,
        report=report,
        json_output=json_output,
    )


def run_wallet_discovery(
    plan: WalletDiscoveryPlan,
    settings: Settings,
    *,
    session_factory: sessionmaker | None = None,
) -> WalletDiscoveryResult:
    init_db(settings.database_url)
    if session_factory is None:
        engine = create_sqlite_engine(settings.database_url)
        session_factory = create_session_factory(engine)

    with session_factory() as session:
        return _run_wallet_discovery_with_session(plan, settings, session)


def _run_wallet_discovery_with_session(
    plan: WalletDiscoveryPlan,
    settings: Settings,
    session: Session,
) -> WalletDiscoveryResult:
    result = WalletDiscoveryResult(state="discovering")
    repo = DiscoveryRepository(session)
    run = repo.create_wallet_discovery_run(notes="dry-run" if plan.dry_run else "stored discovery run")
    result.run_id = run.id
    all_candidates: list[WalletDiscoveryCandidate] = []
    try:
        for source in build_discovery_sources(plan.sources)[: settings.wallet_discovery.max_sources_per_run]:
            source_result = source.fetch_candidates(session=session, limit=plan.max_candidates_per_source)
            result.source_results.append(source_result)
            result.sources_attempted += 1
            if plan.store and not plan.dry_run:
                repo.store_discovery_source(run_id=run.id, source_result=source_result)
            if source_result.status in {"source_failed", "rate_limited"}:
                result.errors_count += 1
            if source_result.status == "not_implemented":
                result.notes.append(f"{source_result.source_name}: source preparee non active")
            all_candidates.extend(source_result.candidates)
        result.candidates_found = len(all_candidates)
        result.candidates_positive_pnl = sum(1 for candidate in all_candidates if (candidate.external_pnl_usdc or 0) > 0)
        result.candidates_positive_roi = sum(1 for candidate in all_candidates if (candidate.external_roi_pct or 0) > 0)
        coin_filtered_candidates = _filter_candidates_by_coin(plan, all_candidates)
        unique_candidates, rejected = dedupe_candidates(coin_filtered_candidates)
        result.candidates_after_filter = len(unique_candidates)
        for address, decision in rejected.items():
            result.rejected.append({"address": address, "decision": decision.value, "reason": decision.value})
        result.state = "filtering"
        scored = _score_and_select(plan, unique_candidates)
        for item in scored:
            selected = item.score.decision == WalletDiscoveryDecision.SELECT_FOR_BACKFILL
            item.selected_for_backfill = selected
            if selected:
                result.selected_wallets.append(item)
                coin_key = item.candidate.coin or "GLOBAL"
                result.selected_by_coin[coin_key] = result.selected_by_coin.get(coin_key, 0) + 1
                result.top_wallets_by_coin.setdefault(coin_key, []).append(str(item.candidate.address))
            else:
                result.rejected.append(
                    {
                        "address": item.candidate.address,
                        "decision": item.score.decision.value,
                        "reason": ",".join(item.score.reasons),
                    }
                )
            if plan.store and not plan.dry_run:
                repo.store_wallet_candidate(
                    run_id=run.id,
                    candidate=item.candidate,
                    selected_for_backfill=selected,
                    rejection_reason=None if selected else ",".join(item.score.reasons),
                )
                repo.store_wallet_candidate_score(run_id=run.id, score=item.score)
                if selected and item.candidate.address is not None:
                    repo.add_auto_watchlist(
                        wallet_address=item.candidate.address,
                        coin=item.candidate.coin,
                        label=item.candidate.label,
                        source=item.candidate.source_name,
                        discovery_score=item.score.final_discovery_score,
                        notes="selected_for_backfill",
                    )
        result.selected_wallets.sort(key=lambda item: item.score.final_discovery_score, reverse=True)
        result.selected_wallets = result.selected_wallets[: plan.backfill_limit]
        if not all_candidates:
            result.state = "no_candidates"
            result.notes.append("aucune_source_n_a_fourni_de_wallet")
        elif not result.selected_wallets:
            result.state = "no_selected_wallets"
            result.notes.append("aucun_wallet_ne_passe_les_filtres")
        else:
            result.state = "completed"
        if not plan.store or plan.dry_run:
            session.rollback()
        else:
            repo.finish_wallet_discovery_run(
                run,
                status="SUCCESS" if result.errors_count == 0 else "PARTIAL",
                sources_attempted=result.sources_attempted,
                candidates_found=result.candidates_found,
                candidates_after_filter=result.candidates_after_filter,
                wallets_selected=len(result.selected_wallets),
                errors_count=result.errors_count,
                notes=";".join(result.notes) or None,
            )
            session.commit()
    except Exception:
        session.rollback()
        raise
    return result


def format_discovery_report(result: WalletDiscoveryResult) -> str:
    selected = [item.candidate.address for item in result.selected_wallets]
    lines = [
        "wallet discovery report",
        f"sources essayees: {result.sources_attempted}",
        f"wallets candidats trouves: {result.candidates_found}",
        f"wallets pnl positif: {result.candidates_positive_pnl}",
        f"wallets roi positif: {result.candidates_positive_roi}",
        f"wallets apres filtre: {result.candidates_after_filter}",
        f"wallets selectionnes: {len(result.selected_wallets)}",
        f"wallets rejetes: {len(result.rejected)}",
        f"etat: {result.state}",
    ]
    if selected:
        lines.append(f"prochains backfills: {', '.join(str(wallet) for wallet in selected)}")
    if result.selected_by_coin:
        lines.append(f"top wallets par coin: {result.selected_by_coin}")
    if result.notes:
        lines.append(f"notes: {'; '.join(sorted(set(result.notes)))}")
    for source in result.source_results:
        if source.status != "ok":
            lines.append(f"source {source.source_name}: {source.status} - {source.error_message or 'aucun wallet'}")
    return "\n".join(lines)


def discovery_result_json(result: WalletDiscoveryResult) -> str:
    return json.dumps(result.model_dump(), indent=2, sort_keys=True, default=str)


def _score_and_select(
    plan: WalletDiscoveryPlan,
    candidates: list[WalletDiscoveryCandidate],
) -> list[ScoredWalletCandidate]:
    scored: list[ScoredWalletCandidate] = []
    for candidate in candidates[: plan.max_candidates]:
        score = score_discovery_candidate(
            wallet_address=candidate.address or "",
            coin=candidate.coin,
            source_reliability_score=candidate.confidence_score,
            external_pnl_usdc=candidate.external_pnl_usdc,
            external_roi_pct=candidate.external_roi_pct,
            external_volume_usdc=candidate.external_volume_usdc,
            external_position_usdc=candidate.external_position_usdc,
            external_win_rate=candidate.external_win_rate,
            min_discovery_score=plan.min_discovery_score,
            require_positive_pnl=plan.require_positive_pnl,
            require_positive_roi=plan.require_positive_roi,
            allow_incomplete_external_metrics=plan.allow_incomplete_external_metrics,
        )
        scored.append(ScoredWalletCandidate(candidate=candidate, score=score))
    return scored


def _filter_candidates_by_coin(
    plan: WalletDiscoveryPlan,
    candidates: list[WalletDiscoveryCandidate],
) -> list[WalletDiscoveryCandidate]:
    requested = {coin.upper() for coin in plan.coins}
    if not requested or "ANY" in requested or "ALL" in requested:
        return [
            candidate
            for candidate in candidates
            if plan.include_altcoins or candidate.coin in {None, "BTC", "ETH"}
        ]
    return [
        candidate
        for candidate in candidates
        if candidate.coin is None or candidate.coin.upper() in requested
    ]
