"""Execute external GitHub profiles as local paper adapters (scoped).

This module is the bridge between cloned upstream repositories and the
HyperSmart simulation. It never imports or runs upstream bot code. Instead, each
installed repo profile is invoked as a deterministic local paper adapter against
the same live Hyperliquid-derived context. The result is explicit: a profile is
either evaluated, produces a paper candidate/order, or returns a clear NO_TRADE
reason.

Depuis 2026-07-07, le bus complet n'est plus le mode normal: par défaut seuls
les repos prioritaires de la matrice de distillation sont évalués
(HYPERSMART_EXTERNAL_PROFILES_SCOPE=priority). Le mode "all" reste disponible
pour la recherche locale contrôlée uniquement.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Iterable

from hl_observer.arbitrage.triangular_opportunity_detector import TriangularOpportunity
from hl_observer.arbitrage.ws_price_discrepancy_detector import PriceDiscrepancy
from hl_observer.connectors.standard import PaperOrderResult
from hl_observer.copy_wallet.copy_conflict_resolver import CopyConflictDecision, LeaderVote
from hl_observer.funding.funding_rate_scanner import FundingSignal
from hl_observer.market_making.market_making_paper import PaperMakerQuote
from hl_observer.strategies.external_github_bridge import (
    discover_external_repo_capabilities,
    external_strategy_definitions,
)
from hl_observer.strategies.github_distillation import priority_distillation_matrix
from hl_observer.strategies.models import StrategyDefinition, StrategyKind

# Scope d'évaluation des profils GitHub externes.
# "priority" (défaut): seuls les repos de la matrice de distillation sont évalués.
# "all": comportement historique du bus (recherche locale uniquement).
# "off": aucun profil externe évalué.
PROFILE_SCOPE_ENV = "HYPERSMART_EXTERNAL_PROFILES_SCOPE"
_VALID_SCOPES = frozenset({"priority", "all", "off"})


def external_profile_scope() -> str:
    value = str(os.getenv(PROFILE_SCOPE_ENV, "priority")).strip().lower()
    return value if value in _VALID_SCOPES else "priority"


def _priority_repo_ids() -> frozenset[str]:
    return frozenset(idea.repo_id for idea in priority_distillation_matrix())


@dataclass(frozen=True, slots=True)
class ExternalProfileExecution:
    repo_id: str
    profile_id: str
    family: str
    kind: str
    installed: bool
    status: str
    decision: str
    reason: str
    candidate_count: int
    accepted_paper_orders: int
    paper_order_refs: tuple[str, ...] = ()
    supported_paper_actions: tuple[str, ...] = ("OPEN", "CLOSE")
    open_close_capable: bool = True
    paper_only: bool = True
    read_only: bool = True
    direct_external_execution: bool = False
    real_execution: bool = False

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["paper_order_refs"] = list(self.paper_order_refs)
        payload["supported_paper_actions"] = list(self.supported_paper_actions)
        return payload


def run_external_profile_simulation_bus(
    *,
    leader_votes: tuple[LeaderVote, ...],
    conflict: CopyConflictDecision,
    price_discrepancies: tuple[PriceDiscrepancy, ...],
    funding_signals: tuple[FundingSignal, ...],
    triangular_opportunities: tuple[TriangularOpportunity, ...],
    maker_quotes: tuple[PaperMakerQuote, ...],
    paper_orders: tuple[PaperOrderResult, ...],
) -> tuple[ExternalProfileExecution, ...]:
    """Evaluate external profiles as simulation adapters.

    Par défaut, seuls les repos prioritaires de la matrice de distillation sont
    évalués. Le mode "all" (bus complet historique) reste disponible pour la
    recherche locale mais n'est plus le mode normal.
    """

    scope = external_profile_scope()
    if scope == "off":
        return ()
    priority_ids = _priority_repo_ids() if scope == "priority" else None

    capabilities = {cap.local_id: cap for cap in discover_external_repo_capabilities()}
    orders_by_strategy: dict[str, list[PaperOrderResult]] = {}
    for order in paper_orders:
        if order.strategy_id:
            orders_by_strategy.setdefault(order.strategy_id, []).append(order)

    executions: list[ExternalProfileExecution] = []
    for definition in external_strategy_definitions():
        repo_id = definition.params.get("source_local_id", "")
        if priority_ids is not None and repo_id not in priority_ids:
            continue
        cap = capabilities.get(repo_id)
        family = next((tag for tag in definition.tags if tag not in {"external-github-priority", "upstream-preserved", "hyperliquid-paper-adapter"}), "")
        orders = tuple(order for order in orders_by_strategy.get(definition.strategy_id, ()) if order.accepted)
        if not definition.enabled or cap is None or not cap.installed:
            executions.append(
                ExternalProfileExecution(
                    repo_id=repo_id,
                    profile_id=definition.strategy_id,
                    family=family,
                    kind=definition.kind.value,
                    installed=False,
                    status="UNAVAILABLE",
                    decision="NOT_EXECUTED",
                    reason=str(definition.params.get("source_status") or "UPSTREAM_NOT_INSTALLED"),
                    candidate_count=0,
                    accepted_paper_orders=0,
                )
            )
            continue

        decision, reason, candidates = _evaluate_profile(
            definition,
            leader_votes=leader_votes,
            conflict=conflict,
            price_discrepancies=price_discrepancies,
            funding_signals=funding_signals,
            triangular_opportunities=triangular_opportunities,
            maker_quotes=maker_quotes,
            accepted_orders=orders,
        )
        executions.append(
            ExternalProfileExecution(
                repo_id=repo_id,
                profile_id=definition.strategy_id,
                family=family,
                kind=definition.kind.value,
                installed=True,
                status="EXECUTED",
                decision=decision,
                reason=reason,
                candidate_count=candidates,
                accepted_paper_orders=len(orders),
                paper_order_refs=tuple(order.order_id for order in orders),
            )
        )
    return tuple(executions)


def summarize_external_profile_executions(executions: Iterable[ExternalProfileExecution]) -> dict[str, object]:
    rows = tuple(executions)
    installed = [row for row in rows if row.installed]
    unavailable = [row for row in rows if not row.installed]
    accepted = [row for row in rows if row.accepted_paper_orders > 0]
    return {
        "profile_scope": external_profile_scope(),
        "profiles_total": len(rows),
        "profiles_installed": len(installed),
        "profiles_unavailable": len(unavailable),
        "profiles_executed": sum(1 for row in installed if row.status == "EXECUTED"),
        "profiles_with_paper_orders": len(accepted),
        "paper_orders_total": sum(row.accepted_paper_orders for row in rows),
        "all_installed_profiles_executed": bool(installed) and all(row.status == "EXECUTED" for row in installed),
        "unavailable_profile_ids": [row.profile_id for row in unavailable],
    }


def _evaluate_profile(
    definition: StrategyDefinition,
    *,
    leader_votes: tuple[LeaderVote, ...],
    conflict: CopyConflictDecision,
    price_discrepancies: tuple[PriceDiscrepancy, ...],
    funding_signals: tuple[FundingSignal, ...],
    triangular_opportunities: tuple[TriangularOpportunity, ...],
    maker_quotes: tuple[PaperMakerQuote, ...],
    accepted_orders: tuple[PaperOrderResult, ...],
) -> tuple[str, str, int]:
    if accepted_orders:
        return "PAPER_ORDER_ACCEPTED", "PROFILE_PRODUCED_ACCEPTED_LOCAL_PAPER_ORDER", len(accepted_orders)

    kind = definition.kind
    if kind is StrategyKind.COPY_FOLLOW:
        if not leader_votes:
            return "NO_TRADE", "NO_LEADER_VOTES", 0
        if conflict.decision != "FOLLOW":
            return "NO_TRADE", "COPY_CONFLICT_OR_NO_MAJORITY", len(leader_votes)
        return "EVALUATED_NO_ORDER", "COPY_CONSENSUS_EXISTS_BUT_PROFILE_NOT_SELECTED", len(leader_votes)

    if kind in {StrategyKind.ARBITRAGE_SIM, StrategyKind.CROSS_SOURCE_DISCREPANCY}:
        candidates = len(price_discrepancies) + sum(1 for row in triangular_opportunities if row.accepted)
        if candidates <= 0:
            return "NO_TRADE", "NO_ARBITRAGE_EDGE_AFTER_COSTS", 0
        return "EVALUATED_DIAGNOSTIC", "ARBITRAGE_CANDIDATE_SEEN_BUT_NOT_MATERIALIZED_BY_THIS_PROFILE", candidates

    if kind is StrategyKind.SPREAD_FARM:
        candidates = sum(1 for row in funding_signals if row.decision == "FUNDING_SPIKE")
        if candidates <= 0:
            return "NO_TRADE", "NO_FUNDING_SPIKE", 0
        return "EVALUATED_DIAGNOSTIC", "FUNDING_CANDIDATE_SEEN_BUT_NOT_MATERIALIZED_BY_THIS_PROFILE", candidates

    if kind is StrategyKind.MARKET_MAKING_SIM:
        if not maker_quotes:
            return "NO_TRADE", "NO_MARKET_MAKING_QUOTES", 0
        return "EVALUATED_DIAGNOSTIC", "PAPER_QUOTES_READY_NO_POSITION_OPENED", len(maker_quotes)

    if kind in {StrategyKind.SHADOW_MODEL, StrategyKind.RAG_EVIDENCE_CONTEXT}:
        context_count = len(leader_votes) + len(price_discrepancies) + len(funding_signals) + len(maker_quotes)
        return "EVALUATED_DIAGNOSTIC", "RESEARCH_OR_SHADOW_PROFILE_EVALUATED_READ_ONLY", context_count

    if kind in {StrategyKind.STRATEGY_ENSEMBLE, StrategyKind.DCA_SIM, StrategyKind.FAST_TIMING, StrategyKind.DIRECTION_HUNT}:
        context_count = len(leader_votes) + len(price_discrepancies) + len(funding_signals) + len(maker_quotes)
        return "EVALUATED_DIAGNOSTIC", "PROFILE_EVALUATED_AS_GUARD_OR_SUPPORT_MODULE", context_count

    return "EVALUATED_DIAGNOSTIC", "PROFILE_KIND_EVALUATED_NO_DIRECT_POSITION", 0


__all__ = [
    "ExternalProfileExecution",
    "PROFILE_SCOPE_ENV",
    "external_profile_scope",
    "run_external_profile_simulation_bus",
    "summarize_external_profile_executions",
]
