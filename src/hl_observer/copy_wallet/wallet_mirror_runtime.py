from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.copy_wallet.mirror_candidate import (
    MirrorCandidate,
    MirrorRuntimeConfig,
    candidate_to_paper_intent,
    mirror_candidate_from_delta,
)
from hl_observer.copy_wallet.proportional_sizer import (
    ProportionalSizingConfig,
    ProportionalSizingDecision,
    size_proportional_to_leader,
)
from hl_observer.copy_wallet.slippage_budget import SlippageBudgetDecision, evaluate_slippage_budget
from hl_observer.copy_wallet.wallet_journal import WalletJournalRecord, append_wallet_journal
from hl_observer.copy_wallet.wallet_rank_decay import RankDecayResult, apply_wallet_rank_decay
from hl_observer.copy_wallet.wallet_tier import WalletTier, tier_for_wallet_score
from hl_observer.edge.edge_net_v12 import EdgeNetV12Estimate, EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.edge.edge_source import edge_brut          # Q1 : la porte unique de l'edge brut
from hl_observer.risk.risk_engine_v3 import (
    EntryCostGuardConfig,
    EntryCostGuardDecision,
    SessionEntryRiskContext,
    V19RiskConfig,
    V19RiskDecision,
    decision_to_dict,
    evaluate_entry_cost_guard,
    evaluate_v19_risk_gates,
)
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.models import PaperIntent


@dataclass(frozen=True, slots=True)
class MirrorPipelineResult:
    candidate: MirrorCandidate
    tier: WalletTier
    rank_decay: RankDecayResult
    sizing: ProportionalSizingDecision
    slippage_budget: SlippageBudgetDecision
    edge_estimate: EdgeNetV12Estimate
    entry_cost_guard: EntryCostGuardDecision
    risk_decision: V19RiskDecision
    paper_intent: PaperIntent | None
    no_trade_reasons: tuple[str, ...] = field(default_factory=tuple)
    journal_record: WalletJournalRecord | None = None
    paper_only: bool = True
    real_execution: bool = False
    # Q1 : D'OU VIENT L'EDGE BRUT ? La question ne doit JAMAIS rester sans reponse.
    # `edge_fabrique=True` => le chiffre sort d'une formule inventee, pas d'une mesure.
    # Ca remonte dans as_dict(), donc dans les logs, le dashboard et l'audit.
    edge_fabrique: bool = False
    edge_source_raison: str = ""

    @property
    def accepted(self) -> bool:
        return self.paper_intent is not None and not self.no_trade_reasons

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "candidate": self.candidate.as_dict(),
            "tier": asdict(self.tier),
            "rank_decay": asdict(self.rank_decay),
            "sizing": asdict(self.sizing),
            "slippage_budget": asdict(self.slippage_budget),
            "edge_estimate": {
                "measurable": self.edge_estimate.measurable,
                "accepted": self.edge_estimate.accepted,
                "gross_edge_bps": self.edge_estimate.gross_edge_bps,
                "total_cost_bps": self.edge_estimate.total_cost_bps,
                "net_edge_bps": self.edge_estimate.net_edge_bps,
                "threshold_bps": self.edge_estimate.threshold_bps,
                "reason_codes": list(self.edge_estimate.reason_codes),
                "cost_breakdown_bps": dict(self.edge_estimate.cost_breakdown_bps),
                # Q1 : la provenance du BRUT. Sans elle, un net calcule sur une formule inventee
                # est indiscernable d'un net calcule sur une mesure. C'etait exactement le
                # probleme.
                "edge_fabrique": self.edge_fabrique,
                "edge_source_raison": self.edge_source_raison,
            },
            "entry_cost_guard": self.entry_cost_guard.as_dict(),
            "risk_decision": decision_to_dict(self.risk_decision),
            "paper_intent": asdict(self.paper_intent) if self.paper_intent is not None else None,
            "no_trade_reasons": list(self.no_trade_reasons),
            "journal_record": self.journal_record.as_dict() if self.journal_record else None,
            "paper_only": True,
            "real_execution": False,
        }


def run_wallet_mirror_pipeline(
    delta: LeaderDelta,
    *,
    leader_price: float,
    observed_time_ms: int,
    wallet_score: float,
    copyability_score: float,
    wallet_rank: int = 1,
    wallet_rank_age_ms: int = 0,
    leader_notional_usdt: float,
    current_mid: float,
    spread_bps: float,
    fee_bps: float,
    slippage_bps: float,
    latency_penalty_bps: float = 0.0,
    logs_dir: Path | None = None,
    risk_config: V19RiskConfig | None = None,
    session_risk_context: SessionEntryRiskContext | None = None,
    entry_guard_config: EntryCostGuardConfig | None = None,
    sizing_config: ProportionalSizingConfig | None = None,
    mirror_config: MirrorRuntimeConfig | None = None,
    leader_expected_edge_bps: float | None = None,
) -> MirrorPipelineResult:
    """Run a full paper-only wallet mirror decision.

    This is the Rezzecup-style mirror flow adapted to HyperSmart: leader delta,
    score decay, tiering, proportional sizing, slippage budget, edge-after-cost,
    RiskEngineV3, then a PaperIntent only if every gate agrees.
    """

    rank_decay = apply_wallet_rank_decay(
        base_score=wallet_score,
        rank=wallet_rank,
        age_ms=wallet_rank_age_ms,
    )
    tier = tier_for_wallet_score(rank_decay.decayed_score, copyability_score)
    candidate = mirror_candidate_from_delta(
        delta,
        leader_price=leader_price,
        observed_time_ms=observed_time_ms,
        wallet_score=rank_decay.decayed_score,
        copyability_score=copyability_score,
        config=mirror_config,
    )
    sizing = size_proportional_to_leader(
        leader_notional_usdt=leader_notional_usdt,
        tier=tier,
        config=sizing_config,
    )
    slippage_gate = evaluate_slippage_budget(
        requested_budget_bps=candidate.slippage_budget_bps,
        tier=tier,
        spread_bps=spread_bps,
        estimated_slippage_bps=slippage_bps,
        latency_penalty_bps=latency_penalty_bps,
    )
    # Q1 (2026-07-13) -- LE 2e EDGE FABRIQUE, TUE A LA SOURCE.
    #
    # Cette ligne disait :
    #     expected_edge = 24.0 + score * 24.0 + copyability * 18.0
    # Trois constantes inventees. Ce nombre est l'edge BRUT de tout le pipeline miroir ; tout ce
    # qui suit (edge net, gates, RiskEngine) n'etait qu'une arithmetique propre sur un mensonge.
    #
    # Desormais la porte unique decide : table MESUREE par defaut, formule seulement si on la
    # demande explicitement -- et alors la decision est ESTAMPILLEE `fabrique`.
    if leader_expected_edge_bps is not None:
        expected_edge: float | None = float(leader_expected_edge_bps)
        edge_fabrique = False
        edge_raison = "EDGE_FOURNI_PAR_L_APPELANT"
    else:
        # `candidate` est deja calcule ci-dessus : il porte le coin et le SENS normalises.
        # On ne re-derive rien -- deux derivations du meme sens, c'est deux verites possibles.
        _e = edge_brut(
            coin=str(candidate.coin or ""),
            direction=str(candidate.side or ""),
            signal_age_ms=float(wallet_rank_age_ms or 0.0),
            leader_score=float(rank_decay.decayed_score),
            consensus_wallets=1.0,
            signal_ms=float(observed_time_ms or 0.0),
            strategie="COPY",
            formule_de_secours=lambda: 24.0
            + max(0.0, rank_decay.decayed_score) * 24.0
            + max(0.0, copyability_score) * 18.0,
        )
        expected_edge = _e.valeur_bps
        edge_fabrique = _e.fabrique
        edge_raison = _e.raison
    # `expected_edge is None` -> `estimate_edge_net_v12` rend EDGE_UNMEASURABLE -> NO_TRADE.
    # Le refus est donc porte par le contrat V12 existant, sans nouveau chemin de decision.
    copy_degradation = max(0.0, float(spread_bps or 0.0)) + max(0.0, float(slippage_bps or 0.0)) + max(
        0.0, float(latency_penalty_bps or 0.0)
    )
    edge = estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=leader_price,
            current_mid=current_mid,
            leader_expected_edge_bps=expected_edge,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            latency_penalty_bps=latency_penalty_bps,
            copy_degradation_bps=copy_degradation,
            funding_estimate_bps=0.0,
            min_edge_bps=18.0,
            max_copy_degradation_bps=40.0,
        )
    )
    reasons: list[str] = list(candidate.reason_codes)
    if not sizing.accepted:
        reasons.append(sizing.reason)
    reasons.extend(slippage_gate.reason_codes)
    reasons.extend(edge.reason_codes)
    entry_guard = evaluate_entry_cost_guard(
        coin=candidate.coin,
        wallet=candidate.leader_wallet,
        notional_usdt=sizing.margin_usdt,
        edge_net_bps=edge.net_edge_bps,
        context=session_risk_context,
        config=entry_guard_config,
    )
    if not entry_guard.accepted:
        reasons.extend(entry_guard.reason_codes)
    risk = evaluate_v19_risk_gates(
        net_pnl_usdc=float((session_risk_context or SessionEntryRiskContext()).net_pnl_usdc),
        total_decisions=max(1, int((session_risk_context or SessionEntryRiskContext()).total_decisions or 1)),
        accepted=int((session_risk_context or SessionEntryRiskContext()).accepted or (0 if reasons else 1)),
        negative_events=int((session_risk_context or SessionEntryRiskContext()).negative_events or 0),
        positive_events=int((session_risk_context or SessionEntryRiskContext()).positive_events or (1 if not reasons else 0)),
        fee_drag_ratio=float((session_risk_context or SessionEntryRiskContext()).fee_drag_ratio or 0.0),
        stale_reason_count=int(
            (session_risk_context or SessionEntryRiskContext()).stale_reason_count
            or sum(1 for reason in reasons if "STALE" in reason or "OLD" in reason)
        ),
        edge_negative_count=int((session_risk_context or SessionEntryRiskContext()).edge_negative_count or (0 if edge.accepted else 1)),
        edge_sentinel_count=0,
        orphan_close_count=int((session_risk_context or SessionEntryRiskContext()).orphan_close_count or 0),
        profit_factor_net=float((session_risk_context or SessionEntryRiskContext()).profit_factor_net or 1.25),
        consecutive_losses=int((session_risk_context or SessionEntryRiskContext()).consecutive_losses or 0),
        top_losing_coins=(session_risk_context or SessionEntryRiskContext()).top_losing_coins,
        top_losing_wallets=(session_risk_context or SessionEntryRiskContext()).top_losing_wallets,
        config=risk_config,
    )
    reasons.extend(risk.blocking_codes)
    unique_reasons = tuple(reason for reason in dict.fromkeys(str(reason) for reason in reasons) if reason)
    paper_intent: PaperIntent | None = None
    if not unique_reasons and risk.allow_new_entries and sizing.accepted and edge.accepted and slippage_gate.accepted:
        paper_intent = candidate_to_paper_intent(
            candidate,
            target_notional_usdt=sizing.margin_usdt,
            created_at_ms=observed_time_ms,
            strategy_id="wallet_mirror_copy_follow",
        )

    journal = WalletJournalRecord(
        event_type="wallet_mirror_decision",
        candidate_id=candidate.candidate_id,
        leader_wallet=candidate.leader_wallet,
        coin=candidate.coin,
        decision="ACCEPT_PAPER" if paper_intent is not None else "NO_TRADE",
        reasons=unique_reasons,
        payload={
            "candidate": candidate.as_dict(),
            "tier": asdict(tier),
            "rank_decay": asdict(rank_decay),
            "sizing": asdict(sizing),
            "edge_net_bps": edge.net_edge_bps,
            # Q1 : le journal DOIT dire d'ou vient le brut. Sinon, en relisant le ledger dans
            # six mois, personne ne pourra distinguer un PnL bati sur une mesure d'un PnL bati
            # sur `24 + score*24 + copyability*18`.
            "edge_brut_bps": edge.gross_edge_bps,
            "edge_fabrique": edge_fabrique,
            "edge_source_raison": edge_raison,
            "entry_cost_guard": entry_guard.as_dict(),
            "risk": decision_to_dict(risk),
        },
    )
    if logs_dir is not None:
        append_wallet_journal(journal, Path(logs_dir) / "wallet_mirror_journal.jsonl")

    return MirrorPipelineResult(
        candidate=candidate,
        tier=tier,
        rank_decay=rank_decay,
        sizing=sizing,
        slippage_budget=slippage_gate,
        edge_estimate=edge,
        entry_cost_guard=entry_guard,
        risk_decision=risk,
        paper_intent=paper_intent,
        no_trade_reasons=unique_reasons,
        journal_record=journal,
        edge_fabrique=edge_fabrique,
        edge_source_raison=edge_raison,
    )


__all__ = ["MirrorPipelineResult", "run_wallet_mirror_pipeline"]
