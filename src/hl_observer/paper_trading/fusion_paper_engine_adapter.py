"""Adapter from fusion copy decisions to the existing PaperEngine."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import os

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote, resolve_copy_conflict
from hl_observer.paper_trading.paper_engine import PaperDecisionResult, PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.ops.echec_silencieux import noter as _noter_echec


@dataclass(frozen=True, slots=True)
class FusionPaperEngineSummary:
    decisions: tuple[PaperDecisionResult, ...]
    accepted_count: int
    equity_usdt: float
    drawdown_usdt: float
    # UN REFUS MUET N'EST PAS UN REFUS AUDITABLE (2026-07-11).
    # Les 3 points de refus de ce chemin renvoyaient un resume VIDE : aucun motif, nulle part.
    # On ne pouvait donc ni verifier qu'un gate avait tourne, ni savoir POURQUOI le bot
    # n'ouvrait pas. C'est exactement pourquoi personne n'a vu que l'edge etait fabrique et que
    # le carnet etait imaginaire : les gates "passaient" en silence.
    refusal_reasons: tuple[str, ...] = ()
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_count": self.accepted_count,
            "refusal_reasons": list(self.refusal_reasons),
            "equity_usdt": self.equity_usdt,
            "drawdown_usdt": self.drawdown_usdt,
            "decisions": [
                {
                    "accepted": item.accepted,
                    "trade": asdict(item.trade) if item.trade else None,
                    "position": asdict(item.position) if item.position else None,
                    "equity_usdt": item.equity_usdt,
                    "drawdown_usdt": item.drawdown_usdt,
                    "reason_codes": list(item.reason_codes),
                    "evidence_hash": item.evidence_hash,
                    "decision_context": dict(item.decision_context),
                }
                for item in self.decisions
            ],
            "paper_only": self.paper_only,
            "real_execution": self.real_execution,
        }


def run_copy_votes_through_paper_engine(
    votes: tuple[LeaderVote, ...],
    *,
    market_price: float,
    observed_at_ms: int,
    starting_cash_usdt: float = 1000.0,
    admission_floor_power: float | None = None,
) -> FusionPaperEngineSummary:
    max_position_usdt = _env_float("HYPERSMART_MAX_POSITION_USDT", 40.0)
    max_total_exposure_usdt = _env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 400.0)
    max_open_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    # BUG CORRIGE (audit 2026-07-11) -- FAIL-OPEN : `if leverage <= 1.0: leverage = 10.0`
    # ECRASAIT SILENCIEUSEMENT toute config a 1. On ne pouvait donc PAS simuler sans levier,
    # et un test qui reglait 1 obtenait 10 sans le savoir. Le defaut reste 10 (demande Flo
    # "pas des centimes"), mais une valeur EXPLICITE est desormais RESPECTEE. Le launcher
    # force deja 10 : le comportement live est inchange.
    leverage = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    if leverage <= 0.0:                 # seule une valeur INVALIDE retombe sur le defaut
        leverage = 10.0
    engine = PaperEngine(
        config=PaperEngineConfig(
            starting_cash_usdt=float(starting_cash_usdt),
            max_position_usdt=max_position_usdt,
            max_total_exposure_usdt=max_total_exposure_usdt,
            max_open_positions=max_open_positions,
            leverage=leverage,
            default_top_depth_usdt=_env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50_000.0),
        )
    )
    conflict = resolve_copy_conflict(votes)
    decisions: list[PaperDecisionResult] = []
    winning_votes = tuple(
        vote
        for vote in votes
        if str(vote.coin or "").upper() == str(conflict.coin or "").upper()
        and _side_bucket(vote.side) == str(conflict.winning_side or "").upper()
    )
    winning_wallets = tuple(sorted({str(vote.wallet).lower() for vote in winning_votes if vote.wallet}))
    distinct_wallets = len(winning_wallets)
    latest_vote_ms = max(
        (int(vote.observed_at_ms) for vote in winning_votes if int(vote.observed_at_ms or 0) > 0),
        default=int(observed_at_ms),
    )
    # LATENCE (Phase 3) -- horloge MONOTONE pour la duree LOCALE. On ne melange JAMAIS l'heure
    # d'exchange et l'heure locale : ce sont deux referentiels, et les confondre revient a mesurer
    # sa propre derive d'horloge en croyant mesurer le reseau.
    from hl_observer.runtime.latency_trace import LatencyTrace

    _trace = LatencyTrace(
        coin=str(conflict.coin or ""), source="fusion_copy_votes",
        source_event_time_ms=int(latest_vote_ms) or None,
    ).start()

    # BUG CORRIGE 2026-07-11 -- LE POLLER DE CARNET SONDAIT UNE LISTE VIDE.
    # Sa source de coins (`DEFAULT_EDGE_TREND_RECORDER`) n'etait alimentee par PERSONNE :
    # `record_edge_observation()` n'est appelee nulle part dans le code. Donc aucun carnet L2
    # n'etait recupere, et TOUS les couts (spread/slippage/profondeur) retombaient sur des
    # constantes -- meme avec HYPERSMART_V26_LIVE_BOOK_COSTS=1.
    # On declare ici le coin comme "d'interet" : c'est le seul endroit du chemin actif ou l'on
    # sait, avec certitude, qu'un signal reel porte sur ce marche.
    try:
        from hl_observer.collection import coin_universe as _cu

        _cu.note_coin(str(conflict.coin or ""))
    except Exception:
        _noter_echec("hl_observer/paper_trading/fusion_paper_engine_adapter.py:119")

    max_signal_age_ms = _env_int("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", 15_000)
    signal_age_ms = max(0, int(observed_at_ms) - int(latest_vote_ms))
    min_consensus_wallets = _env_int("HYPERSMART_FUSION_COPY_MIN_WALLETS", 2)
    if conflict.decision == "FOLLOW" and conflict.winning_side in {"LONG", "SHORT"}:
        if distinct_wallets < min_consensus_wallets or signal_age_ms > max_signal_age_ms:
            equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
            _motifs: list[str] = []
            if distinct_wallets < min_consensus_wallets:
                _motifs.append("CONSENSUS_TOO_WEAK")
            if signal_age_ms > max_signal_age_ms:
                _motifs.append(f"STALE_SIGNAL_{signal_age_ms}MS_OVER_{max_signal_age_ms}MS")
            # 🔴 IMPROVE-05 (#112) — LE REFUS AUSSI LAISSE SA LATENCE.
            #
            # Avant : ce `return` sortait AVANT tout tampon. On ne mesurait donc la latence que
            # des trades qu'on PREND -- un biais de survivant DANS L'INSTRUMENTATION. Or c'est
            # exactement ici qu'il faut mesurer : « a-t-on refuse ce signal parce qu'il etait
            # mauvais, ou parce qu'on est arrive trop tard ? » Sans latence sur les refus,
            # cette question n'a aucune reponse possible.
            try:
                from hl_observer.runtime import latency_journal as _lj

                _lj.enregistrer(_trace.stamp("gates"), _lj.ISSUE_REFUSE, ",".join(_motifs))
            except Exception:
                _noter_echec("hl_observer/paper_trading/fusion_paper_engine_adapter.py:144")
            return FusionPaperEngineSummary(
                decisions=(),
                accepted_count=0,
                equity_usdt=equity,
                drawdown_usdt=drawdown,
                refusal_reasons=tuple(_motifs),
            )
        # ---------------------------------------------------------------------------------
        # CAUSE RACINE (2026-07-11) -- L'EDGE QUI AUTORISAIT CHAQUE ENTREE ETAIT FABRIQUE.
        #
        # `_consensus_edge_remaining_bps` = dominance x 45 + bonus - 18. Ce nombre n'a JAMAIS
        # touche un prix : c'est un score de VOTE converti en bps par une formule inventee.
        # Le code l'avouait deja : edge_source="CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL".
        # Le seuil `min_edge` comparait donc une valeur INVENTEE a un plancher -> aucun reglage
        # de ce seuil ne pouvait rien changer, et le bot ouvrait ce que l'opportunity_report
        # (qui mesure un edge REEL) refusait au meme instant.
        #
        # Desormais : un edge est MESURE, ou il n'existe pas. Pas de mesure -> NO_TRADE.
        # DENY-BY-DEFAULT. Le proxy reste accessible pour une comparaison A/B explicite
        # (HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0), jamais par defaut.
        _trace.stamp("features")
        _spread_bps, _slip_bps, _book_live = _live_book_costs(conflict.coin)
        _trace.stamp("score")
        from hl_observer.edge.empirical_edge import edge_from_calibration, empirical_edge_refusal

        _emp = edge_from_calibration(signal_age_ms=signal_age_ms)
        _refus_edge = empirical_edge_refusal(_emp)
        _trace.stamp("gates")
        if _refus_edge:
            equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
            return FusionPaperEngineSummary(
                decisions=(), accepted_count=0, equity_usdt=equity, drawdown_usdt=drawdown,
                refusal_reasons=(_refus_edge,),
            )
        edge_remaining_bps = (
            float(_emp.value_bps) if _emp.is_empirical
            else _consensus_edge_remaining_bps(conflict, distinct_wallets=distinct_wallets)
        )
        if admission_floor_power is not None:
            # Refonte sélection: le trade copy doit clearer la barre du board unifié
            # (compétition avec toutes les stratégies). Refus AVANT ouverture ->
            # equity inchangée -> réconciliation préservée (comme le refus consensus).
            from hl_observer.integration.board_admission import candidate_power, is_admitted
            _cp = candidate_power(coin=conflict.coin, side=conflict.winning_side,
                                  net_edge_bps=edge_remaining_bps, signal_age_ms=signal_age_ms,
                                  consensus_wallets=distinct_wallets)
            if not is_admitted(_cp, admission_floor_power):
                equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
                return FusionPaperEngineSummary(
                    decisions=(), accepted_count=0, equity_usdt=equity, drawdown_usdt=drawdown,
                    refusal_reasons=("BOARD_ADMISSION_FLOOR_NOT_CLEARED",),
                )
        delta = LeaderDelta(
            delta_id=f"fusion-paper-engine:{conflict.coin}:{conflict.winning_side}:{observed_at_ms}",
            wallet=",".join(winning_wallets) or "unknown",
            coin=conflict.coin,
            action=LifecycleAction.OPEN_LONG if conflict.winning_side == "LONG" else LifecycleAction.OPEN_SHORT,
            previous_size=0.0,
            current_size=1.0 if conflict.winning_side == "LONG" else -1.0,
            delta_size=1.0 if conflict.winning_side == "LONG" else -1.0,
            observed_at_ms=int(observed_at_ms),
            leader_event_time_ms=int(latest_vote_ms),
            source="fusion_paper_engine_adapter",
            confidence=0.9,
            reason_codes=(),
            evidence_ref="fusion_runtime_consensus",
        )
        decisions.append(
            engine.apply_delta(
                delta,
                market_price=float(market_price),
                observed_at_ms=int(observed_at_ms),
                edge_remaining_bps=edge_remaining_bps,
                spread_bps=_spread_bps,
                estimated_slippage_bps=_slip_bps,
                top_depth_usdt=_env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50_000.0),
                wallet_score=_consensus_wallet_score(conflict, distinct_wallets=distinct_wallets),
                signal_score=_consensus_signal_score(conflict, distinct_wallets=distinct_wallets),
                marks={conflict.coin: float(market_price)},
                decision_context={
                    "consensus_wallets": distinct_wallets,
                    "leader_wallets": list(winning_wallets),
                    # PREUVES (fin des `null` dans le ledger) : les gates tournaient avec de
                    # vraies valeurs, mais ne les ecrivaient NULLE PART. Un controle sans trace
                    # n'est pas un controle : il est invérifiable.
                    "signal_age_ms": signal_age_ms,
                    "edge_remaining_bps": edge_remaining_bps,
                    "spread_bps": _spread_bps,
                    "estimated_slippage_bps": _slip_bps,
                    # VERITE DES DONNEES : on DIT si le cout vient du vrai carnet ou d'un repli.
                    "book_costs_are_live": _book_live,
                    # LATENCE : les deux horloges, SEPAREES. Jamais additionnees.
                    **{k: v for k, v in _trace.stamp("decision").as_dict().items()
                       if k in ("source_age_ms", "local_processing_ms", "stage_durations_ms")},
                    "data_quality_status": ("LIVE_BOOK" if _book_live
                                            else "DEGRADED_CONSTANT_COSTS_FALLBACK"),
                    "top_depth_usdt": _env_float("HYPERSMART_FUSION_COPY_TOP_DEPTH_USDT", 50_000.0),
                    **_emp.as_dict(),
                    "winning_vote_score": (
                        float(conflict.long_score)
                        if conflict.winning_side == "LONG"
                        else float(conflict.short_score)
                    ),
                    "opposing_vote_score": (
                        float(conflict.short_score)
                        if conflict.winning_side == "LONG"
                        else float(conflict.long_score)
                    ),
                },
            )
        )
    # IMPROVE-05 (#112) — l'autre moitie du journal : ce qui a ABOUTI (et ce qui a ete refuse
    # plus loin, par le noyau ou les vetos). `resumer()` peut enfin comparer les deux populations.
    try:
        from hl_observer.runtime import latency_journal as _lj

        _accepte = any(item.accepted for item in decisions)
        _motif = "" if _accepte else ",".join(
            str(getattr(item, "reason", "") or "") for item in decisions
        )[:120]
        _lj.enregistrer(
            _trace,
            _lj.ISSUE_ACCEPTE if _accepte else _lj.ISSUE_REFUSE,
            _motif if not _accepte else "",
        )
    except Exception:
        _noter_echec("hl_observer/paper_trading/fusion_paper_engine_adapter.py:271")

    equity, _, drawdown = engine.mark_to_market({conflict.coin or "UNKNOWN": float(market_price)})
    return FusionPaperEngineSummary(
        decisions=tuple(decisions),
        accepted_count=sum(1 for item in decisions if item.accepted),
        equity_usdt=equity,
        drawdown_usdt=drawdown,
    )


def run_distilled_opportunities_through_paper_engine(
    opportunities: tuple[DistilledOpportunity, ...],
    *,
    market_prices: dict[str, float],
    observed_at_ms: int,
    starting_cash_usdt: float = 1000.0,
) -> FusionPaperEngineSummary:
    """Evaluate distilled GitHub-inspired opportunities through PaperEngine.

    This is the safe replacement for direct GitHub-profile materialization. The
    upstream detector already requires fresh multi-wallet consensus, measured
    edge, measured liquidity and measured copy-degradation. This adapter still
    rechecks through RiskEngine/PaperEngine before any local paper position can
    appear in the UI.
    """

    max_position_usdt = _env_float("HYPERSMART_MAX_POSITION_USDT", 40.0)
    max_total_exposure_usdt = _env_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 400.0)
    max_open_positions = _env_int("HYPERSMART_MAX_OPEN_POSITIONS", 12)
    # BUG CORRIGE (audit 2026-07-11) -- FAIL-OPEN : `if leverage <= 1.0: leverage = 10.0`
    # ECRASAIT SILENCIEUSEMENT toute config a 1. On ne pouvait donc PAS simuler sans levier,
    # et un test qui reglait 1 obtenait 10 sans le savoir. Le defaut reste 10 (demande Flo
    # "pas des centimes"), mais une valeur EXPLICITE est desormais RESPECTEE. Le launcher
    # force deja 10 : le comportement live est inchange.
    leverage = _env_float("HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    if leverage <= 0.0:                 # seule une valeur INVALIDE retombe sur le defaut
        leverage = 10.0
    max_entries = max(1, min(_env_int("HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES", 1), 5))
    engine = PaperEngine(
        config=PaperEngineConfig(
            starting_cash_usdt=float(starting_cash_usdt),
            max_position_usdt=max_position_usdt,
            max_total_exposure_usdt=max_total_exposure_usdt,
            max_open_positions=max_open_positions,
            leverage=leverage,
            default_top_depth_usdt=_env_float("HYPERSMART_DISTILLED_TOP_DEPTH_USDT", 75_000.0),
        )
    )
    whale_sizing_enabled = str(_env_str("HYPERSMART_WHALE_CONSENSUS_SIZING", "0")).strip().lower() in {"1", "true", "yes", "on"}
    decisions: list[PaperDecisionResult] = []
    for opportunity in opportunities[:max_entries]:
        coin = str(opportunity.coin or "").upper()
        side = str(opportunity.side or "").upper()
        market_price = float(market_prices.get(coin, 0.0) or 0.0)
        action = LifecycleAction.OPEN_LONG if side == "LONG" else LifecycleAction.OPEN_SHORT
        wallets = ",".join(opportunity.wallets[:5]) or "distilled_cluster"
        margin_scale = 1.0
        sizing_evidence = ""
        if whale_sizing_enabled:
            # Import paresseux: copying/__init__ importe des modules qui dépendent
            # de paper_trading (cycle). Le module de sizing lui-même est pur.
            from hl_observer.copying.whale_consensus_sizing import compute_whale_consensus_sizing

            sizing = compute_whale_consensus_sizing(
                wallet_count=int(opportunity.wallet_count),
                max_signal_age_ms=int(opportunity.max_signal_age_ms),
                total_notional_usdc=float(opportunity.total_notional_usdc),
            )
            margin_scale = sizing.multiplier
            sizing_evidence = f"|whale_sizing:{sizing.tier}:{sizing.multiplier}:" + ",".join(sizing.reasons)
        delta = LeaderDelta(
            delta_id=f"distilled-paper-engine:{coin}:{side}:{observed_at_ms}:{opportunity.wallet_count}",
            wallet=wallets,
            coin=coin,
            action=action,
            previous_size=0.0,
            current_size=1.0 if side == "LONG" else -1.0,
            delta_size=1.0 if side == "LONG" else -1.0,
            observed_at_ms=int(observed_at_ms),
            leader_event_time_ms=max(0, int(observed_at_ms) - int(opportunity.max_signal_age_ms)),
            source="distilled_github_opportunity_detector",
            confidence=min(1.0, max(0.1, float(opportunity.average_liquidity_score))),
            reason_codes=(),
            evidence_ref="distilled_github_consensus" + sizing_evidence,
        )
        decisions.append(
            engine.apply_delta(
                delta,
                market_price=market_price,
                observed_at_ms=int(observed_at_ms),
                edge_remaining_bps=float(opportunity.average_edge_bps),
                spread_bps=_env_float("HYPERSMART_DISTILLED_SPREAD_BPS", 6.0),
                estimated_slippage_bps=_env_float("HYPERSMART_DISTILLED_SLIPPAGE_BPS", 8.0),
                top_depth_usdt=_env_float("HYPERSMART_DISTILLED_TOP_DEPTH_USDT", 75_000.0),
                wallet_score=_distilled_wallet_score(opportunity),
                signal_score=_distilled_signal_score(opportunity),
                marks=market_prices,
                margin_scale=margin_scale,
                decision_context={
                    "consensus_wallets": int(opportunity.wallet_count),
                    "leader_wallets": list(opportunity.wallets),
                    "leader_notional_usdc": float(opportunity.total_notional_usdc),
                    "liquidity_score": float(opportunity.average_liquidity_score),
                    "copy_degradation_bps": max(
                        0.0,
                        _env_float("HYPERSMART_DISTILLED_COPY_DEGRADATION_BPS", 0.0),
                    ),
                    # 2026-07-12 -- LE `True` EN DUR EST SUPPRIME.
                    # Il revendiquait une mesure ("..._MEASURED_...") sur `average_edge_bps`, qui
                    # est la moyenne du bus distille -- PAS la table d'edge mesuree hors echantillon.
                    # C'etait un 3e edge fabrique, et il etait fabrique dans le champ meme dont le
                    # role est d'empecher les edges fabriques. Desormais l'empiricite est DERIVEE de
                    # la table (`edge_from_calibration`) par le moteur de score, jamais declaree ici.
                    "edge_source": "DISTILLED_CANDIDATE_EDGE_NOT_A_MEASUREMENT",
                    "source_profiles": list(opportunity.source_profiles),
                },
            )
        )
    equity, _, drawdown = engine.mark_to_market(market_prices or {"UNKNOWN": 0.0})
    return FusionPaperEngineSummary(
        decisions=tuple(decisions),
        accepted_count=sum(1 for item in decisions if item.accepted),
        equity_usdt=equity,
        drawdown_usdt=drawdown,
    )


def _distilled_wallet_score(opportunity: DistilledOpportunity) -> float:
    return round(min(100.0, 55.0 + min(float(opportunity.wallet_count), 6.0) * 7.0 + float(opportunity.average_liquidity_score) * 12.0), 6)


def _distilled_signal_score(opportunity: DistilledOpportunity) -> float:
    return round(min(100.0, 45.0 + min(float(opportunity.average_edge_bps), 80.0) * 0.45 + min(float(opportunity.wallet_count), 6.0) * 6.0), 6)


def _live_book_costs(coin: str) -> tuple[float, float, bool]:
    """(spread_bps, slippage_bps, est_reel). LE CARNET REEL, ou un repli MARQUE.

    LE BUG (2026-07-11) : ce chemin utilisait `spread=6.0`, `slippage=6.0`, `profondeur=50 000`
    -- des CONSTANTES d'environnement. Le carnet reel n'etait JAMAIS lu. Le gate de liquidite
    "validait" donc l'entree contre un carnet imaginaire, IDENTIQUE pour BTC et pour un meme coin
    illiquide. Un gate qui juge une liquidite inventee ne protege de rien.

    Pire : les DEUX flags qui branchent le carnet (`HYPERSMART_V26_BOOK_POLLER` pour le collecter,
    `HYPERSMART_V26_LIVE_BOOK_COSTS` pour le consommer) etaient ABSENTS des launchers. La capacite
    existait, l'interrupteur etait eteint -- exactement comme le Grinder.

    Regle du brief (Phase 6) : un repli est autorise, mais il doit etre EXPLICITEMENT MARQUE --
    jamais substitue en silence par une valeur favorable.
    """
    try:
        from hl_observer.collection.l2_snapshot_cache import live_costs_for

        lc = live_costs_for(str(coin or ""))
        if lc is not None:
            return float(lc[0]), float(lc[1]), True
    except Exception:
        _noter_echec("hl_observer/paper_trading/fusion_paper_engine_adapter.py:429")
    return (
        _env_float("HYPERSMART_FUSION_COPY_SPREAD_BPS", 6.0),
        _env_float("HYPERSMART_FUSION_COPY_SLIPPAGE_BPS", 6.0),
        False,          # <- repli. Marque comme tel dans le contexte de decision.
    )


def _consensus_edge_remaining_bps(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 1e-9)
    dominance = abs(long_score - short_score) / total
    consensus_bonus = min(float(distinct_wallets), 5.0) * 4.0
    gross_signal = dominance * 45.0 + consensus_bonus
    conservative_cost = _env_float("HYPERSMART_FUSION_COPY_COST_BUFFER_BPS", 18.0)
    return round(gross_signal - conservative_cost, 6)


def _consensus_signal_score(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 1e-9)
    dominance = abs(long_score - short_score) / total
    return round(min(100.0, 30.0 + dominance * 45.0 + min(float(distinct_wallets), 5.0) * 5.0), 6)


def _consensus_wallet_score(conflict: object, *, distinct_wallets: int) -> float:
    long_score = float(getattr(conflict, "long_score", 0.0) or 0.0)
    short_score = float(getattr(conflict, "short_score", 0.0) or 0.0)
    total = max(long_score + short_score, 0.0)
    return round(min(100.0, 65.0 + min(float(distinct_wallets), 5.0) * 8.0 + min(total, 20.0) * 0.75), 6)


def _side_bucket(side: str) -> str:
    raw = str(side or "").upper()
    if "LONG" in raw or "BUY" in raw:
        return "LONG"
    if "SHORT" in raw or "SELL" in raw:
        return "SHORT"
    return "UNKNOWN"


def _env_str(name: str, default: str) -> str:
    import os

    value = os.environ.get(name)
    return default if value is None else str(value)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return int(default)


__all__ = [
    "FusionPaperEngineSummary",
    "run_copy_votes_through_paper_engine",
    "run_distilled_opportunities_through_paper_engine",
]
