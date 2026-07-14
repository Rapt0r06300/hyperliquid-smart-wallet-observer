from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.simulation.live_filters import (
    DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS,
    DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS,
    DEFAULT_SIMULATION_MIN_EDGE_BPS,
    DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE,
    DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS,
)


@dataclass(slots=True)
class RealtimeCopyRiskConfig:
    """Pessimistic local scoring config for realtime copy simulation only."""

    min_edge_required_bps: float = DEFAULT_SIMULATION_MIN_EDGE_BPS
    max_signal_age_ms: int = DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS
    fee_bps: float = 4.0
    spread_bps: float = 3.0
    slippage_bps: float = 2.5
    latency_cost_bps_per_minute: float = 1.0
    max_latency_cost_bps: float = 12.0
    adverse_selection_penalty_bps: float = 2.0
    funding_penalty_bps: float = 0.0
    min_liquidity_score: float = DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE
    low_liquidity_penalty_bps: float = 4.0
    single_wallet_penalty_bps: float = 3.0
    single_wallet_min_edge_required_bps: float = DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS
    crowding_penalty_start_wallets: int = 5
    crowding_penalty_bps_per_wallet: float = 2.0
    max_copy_degradation_bps: float = DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS
    max_price_deviation_bps: float = 18.0
    starting_equity_usdt: float = 1000.0
    max_position_notional_usdt: float = 50.0
    min_position_notional_usdt: float = 5.0
    max_total_exposure_usdt: float = 200.0
    base_risk_fraction: float = 0.03
    max_risk_fraction: float = 0.05


@dataclass(slots=True)
class RealtimeCopyScoreInput:
    action_type: str
    direction: str
    # 2e EDGE FABRIQUE (2026-07-11). `leader_expected_edge_bps` arrive de
    # `fresh_opportunity._expected_edge_bps` = score x 0,55 + wallets x 9 + notional/25000
    # + tightness x 10. Aucune de ces constantes ne vient d'une mesure : ce nombre n'a JAMAIS
    # touche un prix. Le multiplier ensuite par la fraicheur ne le rend pas vrai -- une fiction
    # qui decroit reste une fiction.
    # Desormais l'appelant DOIT declarer si son edge est empirique. Par defaut : NON -> refus.
    leader_expected_edge_bps: float | None
    leader_consistency_factor: float
    signal_age_ms: int
    consensus_wallets: int
    liquidity_score: float
    leader_score: float
    leader_reference_price: float
    current_mid: float | None
    leader_notional_usdt: float
    current_open_exposure_usdt: float
    current_open_positions: int
    max_open_positions: int
    directional_bias_bps: float = 0.0  # V9 multi-TF bias (bias_model), bounded; 0 = neutral
    coin: str = ""  # V26 L1: marché (optionnel). "" = inconnu -> vetos V26 inertes (jamais bloquants).
    # DENY-BY-DEFAULT : tant qu'un appelant ne PROUVE pas que son edge est mesure sur des prix
    # reels, on considere qu'il ne l'est pas -- et le gate refuse. C'est ainsi qu'un edge
    # fabrique ne peut plus autoriser une entree en silence.
    edge_is_empirical: bool = False
    leader_wallet: str = ""  # V26 L6: wallet leader (optionnel). "" = Kelly neutre x1.0.
    # #594 : l'horodatage du signal, pour le verrou ANTI-LOOKAHEAD de la table mesuree (Q1).
    # `None` = on ne peut pas verifier que la table a ete construite AVANT ce signal. La table
    # laisse alors passer -- c'est le seul endroit ou l'appelant doit faire son travail.
    signal_ms: float | None = None


@dataclass(slots=True)
class RealtimeCopyScore:
    decision: str
    refusal_reasons: list[str]
    signal_freshness_score: float
    leader_expected_edge_bps: float | None
    leader_consistency_factor: float
    consensus_wallets: int
    consensus_factor: float
    liquidity_score: float
    leader_score: float
    copy_degradation_bps: float
    edge_remaining_bps: float | None
    opportunity_score: float
    risk_score: float
    price_deviation_bps: float
    adverse_price_move_bps: float
    simulated_notional_usdt: float
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.decision == "ACCEPT_LOCAL_SIMULATION"


def score_realtime_copy_candidate(
    inputs: RealtimeCopyScoreInput,
    *,
    config: RealtimeCopyRiskConfig | None = None,
) -> RealtimeCopyScore:
    """Score one fresh leader delta for local paper-style simulation.

    The output is deliberately a local research decision. It is not an order,
    not a recommendation, and not a promise of future profit.
    """

    cfg = config or RealtimeCopyRiskConfig()
    reasons: list[str] = []
    warnings: list[str] = []
    action_type = inputs.action_type.upper()
    direction = inputs.direction.upper()
    if action_type in {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT", "UNKNOWN"}:
        reason = "REDUCE_OR_CLOSE_NOT_ENTRY" if action_type != "UNKNOWN" else "UNKNOWN_DELTA"
        return _rejected_score(inputs, cfg, [reason], warnings)
    if action_type not in {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}:
        return _rejected_score(inputs, cfg, ["UNKNOWN_DELTA"], warnings)
    if direction not in {"LONG", "SHORT"}:
        return _rejected_score(inputs, cfg, ["UNKNOWN_DELTA"], warnings)
    if inputs.leader_reference_price <= 0:
        return _rejected_score(inputs, cfg, ["PRICE_INVALID"], warnings)
    if inputs.leader_expected_edge_bps is None:
        return _rejected_score(inputs, cfg, ["EDGE_UNMEASURABLE"], warnings)
    if inputs.current_open_positions >= inputs.max_open_positions:
        reasons.append("MAX_OPEN_PAPER_TRADES_REACHED")

    freshness = freshness_factor(inputs.signal_age_ms, cfg.max_signal_age_ms)
    if inputs.signal_age_ms > cfg.max_signal_age_ms:
        reasons.append("STALE_SIGNAL")

    current_mid = inputs.current_mid if inputs.current_mid and inputs.current_mid > 0 else inputs.leader_reference_price
    price_deviation_bps = abs(current_mid - inputs.leader_reference_price) / inputs.leader_reference_price * 10_000.0
    adverse_price_move_bps = _adverse_price_move_bps(
        direction=direction,
        leader_price=inputs.leader_reference_price,
        current_mid=current_mid,
    )
    if adverse_price_move_bps > cfg.max_price_deviation_bps:
        reasons.append("PRICE_DEVIATION_TOO_HIGH")

    consensus_factor = 1.0 + min(0.25, max(0, inputs.consensus_wallets - 1) * 0.08)
    crowding_penalty_bps = max(0, inputs.consensus_wallets - cfg.crowding_penalty_start_wallets) * cfg.crowding_penalty_bps_per_wallet
    if crowding_penalty_bps > 0:
        warnings.append("CROWDING_PENALTY_APPLIED")
    liquidity_score = clamp(inputs.liquidity_score, 0.0, 1.0)
    liquidity_penalty_bps = cfg.low_liquidity_penalty_bps if liquidity_score < cfg.min_liquidity_score else 0.0
    if liquidity_penalty_bps > 0:
        reasons.append("LIQUIDITY_TOO_LOW")

    # ------------------------------------------------------------------ L'EDGE EST-IL REEL ?
    # LE GATE QUI MANQUAIT. `leader_expected_edge_bps` etait une formule inventee ; on la
    # multipliait par la fraicheur, on lui soustrayait des couts, on la comparait a un seuil...
    # et on ouvrait. Tout cet appareil de rigueur s'appliquait a un nombre qui ne decrit rien.
    # Un edge est MESURE, ou il n'existe pas. Deny-by-default.
    #
    # CABLAGE MORT CORRIGE LE 2026-07-12
    # ----------------------------------
    # Ce gate ne LISAIT PAS la table mesuree. Il testait `inputs.edge_is_empirical` -- un drapeau
    # a `False` par defaut que PERSONNE ne calculait. Il refusait donc TOUJOURS, en test comme en
    # production, et `edge_from_calibration()` -- la fonction ecrite pour lire la mesure -- n'etait
    # appelee nulle part sur ce chemin. Pire : le seul endroit du code qui posait `True` l'ecrivait
    # EN DUR, sous une etiquette "..._MEASURED_..." -- une revendication de mesure sur un nombre
    # qui n'en etait pas une. Le champ cense empecher les edges fabriques etait lui-meme fabrique.
    #
    # Desormais : LA TABLE EST LA SOURCE. Un appelant ne peut plus se declarer empirique ; il doit
    # y avoir une bande MESUREE couvrant la fraicheur de ce signal, avec un echantillon suffisant.
    #
    # NOTE IMPORTANTE : "empirique" parle de la PROVENANCE, pas du SIGNE. Sur la vraie table du
    # 11/07, toutes les bandes sont NEGATIVES (-2,17 / -0,56 / -0,23 bps). Le signal devient donc
    # empirique... et se fait refuser plus bas par le seuil d'edge, apres couts. C'est le refus
    # POUR LA BONNE RAISON -- "l'edge mesure est negatif" -- et non plus par accident de cablage.
    #
    # 🔴 #594 / #310 -- 2026-07-13 : IL Y AVAIT **DEUX TABLES**, ET LA SECONDE ECRASAIT LA PREMIERE.
    # -----------------------------------------------------------------------------------------
    # `ui/routes.py` (chemin LIVE) mesurait l'edge par la porte Q1 (`edge.edge_source.edge_brut`,
    # table conditionnee sur coin x direction x age x score du leader x consensus, BORNE BASSE,
    # verrou anti-lookahead) et le passait ici dans `leader_expected_edge_bps`.
    #
    # Et ici, ce chiffre etait **JETE** : ce bloc appelait `edge.empirical_edge`, une AUTRE table
    # (`runtime/calibration/empirical_edge.json`), indexee sur le SEUL age, sans coin, sans
    # direction, sans consensus, sans anti-lookahead. Tout le travail de Q1 mourait ici, en
    # silence -- 6e deguisement de la maladie : « la capacite est la, le fil est coupe ».
    #
    # Et ce n'est pas tout. La valeur ainsi obtenue etait ensuite RE-MULTIPLIEE par `freshness`
    # et `consensus_factor` -- exactement les features sur lesquelles la table CONDITIONNE DEJA.
    # Sur un edge NEGATIF (et la mesure reelle EST negative : -2,17 / -0,56 / -0,23 bps),
    # multiplier par une fraicheur qui DECROIT rend l'edge MOINS negatif :
    #
    #     age  6 s : -2,17 x 0,92 = -1,99 bps          <- signal FRAIS,  edge "pire"
    #     age 25 s : -0,56 x 0,31 = -0,17 bps          <- signal VIEUX,  edge "meilleur"
    #
    # Le multiplicateur de fraicheur, cense PENALISER les vieux signaux, les RECOMPENSAIT.
    # Il n'inverse pas seulement une intention : il inverse un SIGNE.
    #
    # Desormais : UNE porte (Q1), et sur un edge MESURE on ne fait plus qu'une chose --
    # soustraire les couts. Pas de ponderation, pas de bonus, pas de biais ajoute.
    edge_base_bps = 0.0
    edge_est_mesure = False
    try:
        from hl_observer.edge.edge_source import edge_brut as _porte_de_l_edge

        _e = _porte_de_l_edge(
            coin=getattr(inputs, "coin", "") or "",
            direction=direction,
            signal_age_ms=float(inputs.signal_age_ms),
            leader_score=float(inputs.leader_score),
            consensus_wallets=float(inputs.consensus_wallets),
            signal_ms=getattr(inputs, "signal_ms", None),
            strategie="COPY",
            # Le mode `formule` (A/B explicite, HYPERSMART_EDGE_SOURCE=formule) est le SEUL qui
            # rende la main a l'ancien chiffre -- et `edge_brut` l'estampille alors `fabrique=True`.
            formule_de_secours=(lambda: float(inputs.leader_expected_edge_bps or 0.0)),
        )
        if not _e.utilisable:
            reasons.append(_e.raison or "EDGE_NON_MESURE_NO_TRADE")
        else:
            edge_base_bps = float(_e.valeur_bps)
            edge_est_mesure = not _e.fabrique
            warnings.append("EDGE_FROM_MEASURED_TABLE" if edge_est_mesure else _e.raison)
    except Exception:                      # un gate qui plante ne doit jamais OUVRIR une position
        reasons.append("EDGE_EMPIRICITY_CHECK_FAILED")
    single_wallet_penalty_bps = cfg.single_wallet_penalty_bps if inputs.consensus_wallets < 2 else 0.0
    # V26 reliquat — coûts carnet LIVE (walk-the-book, opt-in) : remplacent les constantes
    # quand un snapshot l2 frais existe pour ce coin. Sinon constantes V25 inchangées.
    spread_bps_used, slippage_bps_used = cfg.spread_bps, cfg.slippage_bps
    try:
        from hl_observer.collection.l2_snapshot_cache import live_costs_for as _live_costs

        _lc = _live_costs(getattr(inputs, "coin", "") or "")
        if _lc is not None:
            spread_bps_used, slippage_bps_used = _lc
            warnings.append("LIVE_BOOK_COSTS_USED")
    except Exception:
        pass
    delay_cost_bps = min(cfg.max_latency_cost_bps, max(0, inputs.signal_age_ms) / 60_000.0 * cfg.latency_cost_bps_per_minute)
    copy_degradation_bps = (
        delay_cost_bps
        + spread_bps_used
        + slippage_bps_used
        + cfg.fee_bps
        + liquidity_penalty_bps
        + single_wallet_penalty_bps
        + adverse_price_move_bps
        + cfg.adverse_selection_penalty_bps
        + crowding_penalty_bps
        + cfg.funding_penalty_bps
    )
    if spread_bps_used > 20:
        reasons.append("SPREAD_TOO_WIDE")
    if slippage_bps_used > 25:
        reasons.append("SLIPPAGE_TOO_HIGH")
    if copy_degradation_bps > cfg.max_copy_degradation_bps:
        reasons.append("COPY_DEGRADATION_TOO_HIGH")

    if edge_est_mesure:
        # LE CHEMIN NORMAL. La table Q1 conditionne DEJA sur l'age, le score du leader et le
        # consensus. Les re-multiplier ici compterait ces memes features DEUX FOIS (#594) -- et
        # sur un edge negatif, la fraicheur INVERSAIT la penalite (cf. le bloc plus haut).
        # Un edge mesure moins ses couts. Rien d'autre. Aucune ponderation, aucun bonus.
        edge_remaining_bps = edge_base_bps - copy_degradation_bps
    else:
        # MODE A/B EXPLICITE (`HYPERSMART_EDGE_SOURCE=formule`). La valeur est FABRIQUEE et deja
        # estampillee `fabrique=True` par la porte. On conserve l'ancienne ponderation A L'IDENTIQUE
        # pour que la comparaison A/B reste valable -- une fiction ponderee reste une fiction, mais
        # au moins c'est la MEME fiction qu'avant, et elle est declaree.
        # EDGE_NON_FABRIQUE: aucune valeur d'edge n'est CREEE ici. Les nombres visibles sont les
        # BORNES de clamp de l'ancien chemin A/B (0..1.5, -10..+10) ; la base vient de la porte, qui
        # l'a deja marquee comme fabriquee et l'a fait remonter dans les logs et le dashboard.
        edge_remaining_bps = (
            edge_base_bps
            * clamp(inputs.leader_consistency_factor, 0.0, 1.5)
            * freshness
            * consensus_factor
            + clamp(inputs.directional_bias_bps, -10.0, 10.0)  # V9 trend-alignment, bounded
            - copy_degradation_bps
        )
    if edge_remaining_bps < cfg.min_edge_required_bps:
        reasons.append("EDGE_REMAINING_TOO_LOW")
    if inputs.consensus_wallets < 2 and edge_remaining_bps < cfg.single_wallet_min_edge_required_bps:
        reasons.append("SINGLE_WALLET_EDGE_TOO_LOW")
    if edge_remaining_bps <= 0:
        warnings.append("EDGE_NON_POSITIVE_AFTER_COSTS")

    simulated_notional, sizing_warnings = capped_simulated_notional(inputs, cfg, edge_remaining_bps)
    warnings.extend(sizing_warnings)
    # V26 L6 — multiplicateur Kelly par leader (opt-in ; x1.0 si flag OFF ou wallet inconnu)
    try:
        from hl_observer.risk.kelly_leader_book import DEFAULT_KELLY_LEADER_BOOK as _klb

        _km = _klb.multiplier(getattr(inputs, "leader_wallet", "") or "")
        if _km != 1.0 and simulated_notional > 0:
            # cap au max de position LEVERAGE (sinon Kelly annulait le levier -> retour aux centimes)
            import os as _os_k
            _lev_k = max(1.0, float(_os_k.environ.get("HYPERSMART_SIMULATION_LEVERAGE", "1") or 1.0))
            simulated_notional = min(cfg.max_position_notional_usdt * _lev_k, max(0.0, simulated_notional * _km))
            warnings.append("KELLY_LEADER_MULT_%.2f" % _km)
    except Exception:
        pass
    if simulated_notional <= 0:
        reasons.append("MAX_EXPOSURE_REACHED")

    risk_score = risk_score_from_costs(
        copy_degradation_bps=copy_degradation_bps,
        price_deviation_bps=adverse_price_move_bps,
        liquidity_score=liquidity_score,
    )
    opportunity_score = clamp(
        30.0
        + (edge_remaining_bps * 1.35)
        + clamp(inputs.leader_score, 0.0, 100.0) * 0.18
        + (inputs.consensus_wallets - 1) * 5.0
        + liquidity_score * 8.0
        - (100.0 - risk_score) * 0.12,
        0.0,
        100.0,
    )

    # V26 L1 — vetos funding sain + edge stable (repo 32). Opt-in env, défaut OFF => inchangé.
    # Intersection stricte : ne peut qu'AJOUTER des raisons de refus, jamais créer un trade.
    # Enregistre aussi l'historique d'edge (observabilité) même flag OFF. Fail-safe total.
    try:
        from hl_observer.signals.v26_entry_vetos import apply_v26_entry_vetos

        import os as _os

        _snapshot = None
        if str(_os.environ.get("HYPERSMART_V26_RECORD_CANDIDATES", "0")).lower() in ("1", "true", "yes", "on"):
            _snapshot = {
                "action_type": action_type, "direction": direction,
                "coin": getattr(inputs, "coin", "") or "",
                "leader_wallet": getattr(inputs, "leader_wallet", "") or "",
                "leader_expected_edge_bps": inputs.leader_expected_edge_bps,
                "leader_consistency_factor": inputs.leader_consistency_factor,
                "signal_age_ms": inputs.signal_age_ms,
                "consensus_wallets": inputs.consensus_wallets,
                "liquidity_score": liquidity_score,
                "leader_score": inputs.leader_score,
                "leader_reference_price": inputs.leader_reference_price,
                "current_mid": current_mid,
                "leader_notional_usdt": inputs.leader_notional_usdt,
                "edge_remaining_bps": edge_remaining_bps,
                "copy_degradation_bps": copy_degradation_bps,
            }
        reasons.extend(
            apply_v26_entry_vetos(
                coin=getattr(inputs, "coin", "") or "",
                side=direction,
                edge_remaining_bps=edge_remaining_bps,
                leader_score=inputs.leader_score,
                copy_degradation_bps=copy_degradation_bps,
                liquidity_score=liquidity_score,
                candidate_snapshot=_snapshot,
            )
        )
    except Exception:  # pragma: no cover — le moteur ne doit jamais casser sur un veto
        pass

    deduped_reasons = sorted(set(reasons))
    decision = "REJECT_NO_TRADE" if deduped_reasons else "ACCEPT_LOCAL_SIMULATION"
    return RealtimeCopyScore(
        decision=decision,
        refusal_reasons=deduped_reasons,
        signal_freshness_score=round(freshness, 6),
        leader_expected_edge_bps=round(inputs.leader_expected_edge_bps, 6),
        leader_consistency_factor=round(inputs.leader_consistency_factor, 6),
        consensus_wallets=max(0, int(inputs.consensus_wallets)),
        consensus_factor=round(consensus_factor, 6),
        liquidity_score=round(liquidity_score, 6),
        leader_score=round(clamp(inputs.leader_score, 0.0, 100.0), 6),
        copy_degradation_bps=round(copy_degradation_bps, 6),
        edge_remaining_bps=round(edge_remaining_bps, 6),
        opportunity_score=round(opportunity_score, 6),
        risk_score=round(risk_score, 6),
        price_deviation_bps=round(price_deviation_bps, 6),
        adverse_price_move_bps=round(adverse_price_move_bps, 6),
        simulated_notional_usdt=round(simulated_notional, 6),
        warnings=warnings,
    )


def capped_simulated_notional(
    inputs: RealtimeCopyScoreInput,
    cfg: RealtimeCopyRiskConfig,
    edge_remaining_bps: float,
) -> tuple[float, list[str]]:
    warnings: list[str] = []
    edge_fraction_boost = min(0.02, max(0.0, edge_remaining_bps) / 2_000.0)
    consensus_boost = 0.01 if inputs.consensus_wallets >= 2 else 0.0
    risk_fraction = min(cfg.max_risk_fraction, cfg.base_risk_fraction + edge_fraction_boost + consensus_boost)
    # LEVIER (demande Flo "pas des centimes"): la copie sizait le NOTIONAL = marge (~$40) sans
    # jamais appliquer le levier -> PnL en centimes. Un vrai copy-trader leverage copie la
    # DIRECTION du leader mais dimensionne sur SON compte a SON levier: notional = marge x levier.
    # On met TOUT a l'echelle du levier (position, leader, exposition) -> meme nb de positions,
    # meme marge a risque, mais notional x levier => PnL x levier (honnete: notional x variation).
    import os as _os
    lev = max(1.0, float(_os.environ.get("HYPERSMART_SIMULATION_LEVERAGE", "1") or 1.0))
    target = cfg.starting_equity_usdt * risk_fraction * lev
    max_pos = cfg.max_position_notional_usdt * lev
    leader_cap = (inputs.leader_notional_usdt * lev) if inputs.leader_notional_usdt > 0 else max_pos
    notional = min(max_pos, max(cfg.min_position_notional_usdt, target), leader_cap)
    remaining_exposure = max(0.0, cfg.max_total_exposure_usdt * lev - max(0.0, inputs.current_open_exposure_usdt))
    if remaining_exposure <= 0:
        return 0.0, ["MAX_TOTAL_EXPOSURE_CAP_ACTIVE"]
    if notional > remaining_exposure:
        notional = remaining_exposure
        warnings.append("POSITION_SIZE_CAPPED_BY_TOTAL_EXPOSURE")
    if notional < cfg.min_position_notional_usdt:
        return 0.0, [*warnings, "POSITION_SIZE_BELOW_MINIMUM"]
    if inputs.leader_notional_usdt * lev > max_pos:
        warnings.append("POSITION_SIZE_CAPPED_VS_LEADER")
    return notional, warnings


def freshness_factor(signal_age_ms: int, max_signal_age_ms: int) -> float:
    """Edge-preserving freshness multiplier (V9, calibrated decay).

    Replaces the old brutal *linear* curve (``1 - age/max``) that crushed the
    edge of fresh-but-not-instant signals (only 17% left at 25s with a 30s
    window) -- the deepest measured cause of "0 ouverture". Keeps full edge
    during a short grace period, decays with a half-life, still reaches 0 at
    ``max_signal_age_ms`` (stale). Only ever *raises* the multiplier for fresh
    signals; never lowers the net-edge bar. Falls back to linear on any error.
    """
    if max_signal_age_ms <= 0:
        return 0.0
    try:
        from hl_observer.freshness.signal_decay import freshness_factor_calibrated

        return freshness_factor_calibrated(int(signal_age_ms), int(max_signal_age_ms))
    except Exception:  # pragma: no cover - graceful degradation
        return clamp(1.0 - max(0, signal_age_ms) / max_signal_age_ms, 0.0, 1.0)


def risk_score_from_costs(*, copy_degradation_bps: float, price_deviation_bps: float, liquidity_score: float) -> float:
    cost_penalty = min(45.0, max(0.0, copy_degradation_bps) * 1.2)
    deviation_penalty = min(25.0, max(0.0, price_deviation_bps) * 0.6)
    liquidity_penalty = (1.0 - clamp(liquidity_score, 0.0, 1.0)) * 30.0
    return clamp(100.0 - cost_penalty - deviation_penalty - liquidity_penalty, 0.0, 100.0)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _adverse_price_move_bps(*, direction: str, leader_price: float, current_mid: float) -> float:
    if leader_price <= 0 or current_mid <= 0:
        return 0.0
    if direction.upper() == "LONG":
        return max(0.0, (current_mid - leader_price) / leader_price * 10_000.0)
    if direction.upper() == "SHORT":
        return max(0.0, (leader_price - current_mid) / leader_price * 10_000.0)
    return 0.0


def _rejected_score(
    inputs: RealtimeCopyScoreInput,
    cfg: RealtimeCopyRiskConfig,
    reasons: list[str],
    warnings: list[str],
) -> RealtimeCopyScore:
    freshness = freshness_factor(inputs.signal_age_ms, cfg.max_signal_age_ms)
    liquidity_score = clamp(inputs.liquidity_score, 0.0, 1.0)
    current_mid = inputs.current_mid if inputs.current_mid and inputs.current_mid > 0 else inputs.leader_reference_price
    price_deviation_bps = (
        abs(current_mid - inputs.leader_reference_price) / inputs.leader_reference_price * 10_000.0
        if inputs.leader_reference_price > 0 and current_mid > 0
        else 0.0
    )
    adverse_price_move_bps = _adverse_price_move_bps(
        direction=inputs.direction,
        leader_price=inputs.leader_reference_price,
        current_mid=current_mid,
    )
    return RealtimeCopyScore(
        decision="REJECT_NO_TRADE",
        refusal_reasons=sorted(set(reasons)),
        signal_freshness_score=round(freshness, 6),
        leader_expected_edge_bps=inputs.leader_expected_edge_bps,
        leader_consistency_factor=round(inputs.leader_consistency_factor, 6),
        consensus_wallets=max(0, int(inputs.consensus_wallets)),
        consensus_factor=1.0,
        liquidity_score=round(liquidity_score, 6),
        leader_score=round(clamp(inputs.leader_score, 0.0, 100.0), 6),
        copy_degradation_bps=0.0,
        edge_remaining_bps=None,
        opportunity_score=0.0,
        risk_score=0.0,
        price_deviation_bps=round(price_deviation_bps, 6),
        adverse_price_move_bps=round(adverse_price_move_bps, 6),
        simulated_notional_usdt=0.0,
        warnings=warnings,
    )
