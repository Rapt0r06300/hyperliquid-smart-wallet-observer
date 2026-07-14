"""Deep paper execution model (S8 — V9, pm-backtest A2 / CloddsBot — SIM).

Models what filling a copy order would *really* cost, on real book state, so the
paper PnL reflects execution reality instead of an idealised mid-price fill:

  * taker path: pay the taker fee + half-spread + size/depth market impact;
  * maker path: earn the maker rebate, but face queue position and fill risk;
  * latency: optional time-decay cost while the order is in flight.

Everything is *simulated*. Nothing is sent to a real venue; there is no order id,
no signature, no endpoint. It only returns an effective fill price and a signed
cost in bps (positive = cost, negative = rebate credit). SAFETY: pure & paper.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecModelConfig:
    # TARIF REEL HYPERLIQUID (tarif de base, verifie 2026-07-11) :
    #   taker = 0,045 % = 4,5 bps  |  maker = 0,015 % = 1,5 bps -- LE MAKER **COUTE**.
    # BUG CORRIGE : `maker_rebate_bps = 1.0` traitait le maker comme un REBATE (fee = -1 bps),
    # donc un cout d'execution NEGATIF : le bot etait *paye* pour entrer, et rempli a un prix
    # MEILLEUR que le marche. Sur Hyperliquid le rebate n'existe qu'aux paliers de volume les plus
    # eleves ; au tarif de base un maker PAIE. Erreur de 2,5 bps par execution, dans le sens
    # FAVORABLE -- exactement ce qui aurait fait "valider" une strategie maker-first qui perd en reel.
    taker_fee_bps: float = 4.5
    maker_fee_bps: float = 1.5             # cout d'un fill passif (0,015 %)
    maker_rebate_bps: float = 0.0          # rebate reel : 0 au tarif de base (opt-in par palier)
    half_spread_bps: float = 1.0
    impact_coef_bps: float = 10.0          # impact when the order consumes the whole top depth
    # BUG CORRIGE (2026-07-11) — LA LATENCE NE COUTAIT RIEN (0.0).
    # On copie un leader avec un retard median MESURE de 57 secondes. Pendant ce temps le prix
    # bouge : c'est le cout de copie le plus reel qui soit, et il etait facture ZERO.
    # 0,20 bps par seconde, plafonne plus bas : ~11 bps pour 57 s, coherent avec la degradation
    # de copie mesuree par le scorer (~14 bps).
    latency_cost_bps_per_sec: float = 0.20
    max_latency_cost_bps: float = 15.0
    # if depth is unknown we cannot trust the fill -> charge a conservative impact
    unknown_depth_impact_bps: float = 25.0


@dataclass(frozen=True, slots=True)
class ExecResult:
    fill_price: float
    slippage_bps: float
    fee_bps: float           # signed: + = fee paid, - = rebate earned
    latency_bps: float
    net_cost_bps: float      # total signed cost vs mid (slippage + fee + latency)
    queue_ratio: float | None
    is_maker: bool
    notional_usdc: float


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True, slots=True)
class DepthExecutionResult:
    requested_notional_usdc: float
    filled_notional_usdc: float
    missed_notional_usdc: float
    average_fill_price: float | None
    fill_ratio: float
    partial: bool
    missed: bool
    slippage_bps: float
    levels_consumed: int
    reason: str


def estimate_slippage_bps(
    notional_usdc: float,
    top_depth_usdc: float | None,
    *,
    config: ExecModelConfig | None = None,
) -> float:
    """Half-spread + size/depth market impact, in bps. Depth None -> conservative."""
    cfg = config or ExecModelConfig()
    if top_depth_usdc is None or top_depth_usdc <= 0:
        return cfg.half_spread_bps + cfg.unknown_depth_impact_bps
    consume_ratio = max(0.0, notional_usdc) / top_depth_usdc
    return cfg.half_spread_bps + cfg.impact_coef_bps * consume_ratio


def _apply_price(mid_price: float, side: str, signed_bps: float) -> float:
    # a positive cost moves the fill against you (buy higher, sell lower)
    adj = signed_bps / 10_000.0
    if side.upper() in {"LONG", "BUY"}:
        return mid_price * (1.0 + adj)
    return mid_price * (1.0 - adj)


def simulate_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    top_depth_usdc: float | None = None,
    is_maker: bool = False,
    latency_sec: float = 0.0,
    queue_ahead_usdc: float = 0.0,
    config: ExecModelConfig | None = None,
) -> ExecResult:
    """Simulate filling ``notional_usdc`` at ``mid_price`` on the given book."""
    cfg = config or ExecModelConfig()
    latency_bps = min(
        float(getattr(cfg, "max_latency_cost_bps", 15.0)),
        max(0.0, latency_sec) * cfg.latency_cost_bps_per_sec,
    )

    if is_maker:
        # Passive fill: no spread paid, earn the rebate; model queue position.
        depth = top_depth_usdc if (top_depth_usdc and top_depth_usdc > 0) else None
        queue_ratio = None
        if depth is not None:
            queue_ratio = max(0.0, queue_ahead_usdc) / depth
        slippage_bps = 0.0
        # cout maker NET : les frais payes, moins un eventuel rebate de palier (0 par defaut).
        # Il n'est negatif QUE si un vrai rebate est configure -- jamais par accident.
        fee_bps = float(cfg.maker_fee_bps) - float(cfg.maker_rebate_bps)
        # Honnêteté du fill passif: adverse selection configurable (mode grinder).
        # 0.0 par défaut = comportement historique inchangé.
        adverse_bps = _env_adverse_selection_bps()
        net_cost_bps = slippage_bps + fee_bps + latency_bps + adverse_bps
        fill_price = _apply_price(mid_price, side, net_cost_bps)
        return ExecResult(
            fill_price=round(fill_price, 10),
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            latency_bps=latency_bps,
            net_cost_bps=net_cost_bps,
            queue_ratio=queue_ratio,
            is_maker=True,
            notional_usdc=notional_usdc,
        )

    # Taker path: pay fee + half-spread + impact.
    # NOTE (chasse aux bugs 2026-07-11) : j'ai d'abord cru que le demi-spread n'etait jamais paye,
    # parce qu'il n'apparait pas explicitement ici. C'etait FAUX : `estimate_slippage_bps` retourne
    # DEJA `half_spread_bps + impact`. L'ajouter une seconde fois l'aurait compte DOUBLE -- et c'est
    # `test_v9_exec_model_direction_bias::test_taker_costs_fee_plus_slippage` qui a attrape l'erreur.
    # Le vrai bug etait ailleurs : la LATENCE (voir `latency_cost_bps_per_sec`).
    slippage_bps = estimate_slippage_bps(notional_usdc, top_depth_usdc, config=cfg)   # spread INCLUS
    fee_bps = cfg.taker_fee_bps
    net_cost_bps = slippage_bps + fee_bps + latency_bps
    fill_price = _apply_price(mid_price, side, net_cost_bps)
    return ExecResult(
        fill_price=round(fill_price, 10),
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        latency_bps=latency_bps,
        net_cost_bps=net_cost_bps,
        queue_ratio=None,
        is_maker=False,
        notional_usdc=notional_usdc,
    )


def round_trip_cost_bps(
    *,
    entry: ExecResult,
    exit_: ExecResult,
) -> float:
    """Total signed cost of a round trip (entry + exit), in bps."""
    return entry.net_cost_bps + exit_.net_cost_bps


def simulate_depth_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.85,
) -> DepthExecutionResult:
    """Estimate average fill from explicit book levels.

    ``asks`` and ``bids`` are ``(price, size)`` levels. Size is in base units.
    The result is still paper-only and deterministic. It is useful for refusing
    entries where the top/multi-level book cannot realistically fill the paper
    notional.
    """

    requested = max(0.0, float(notional_usdc or 0.0))
    mid = float(mid_price or 0.0)
    if requested <= 0 or mid <= 0:
        return DepthExecutionResult(
            requested_notional_usdc=requested,
            filled_notional_usdc=0.0,
            missed_notional_usdc=requested,
            average_fill_price=None,
            fill_ratio=0.0,
            partial=False,
            missed=True,
            slippage_bps=0.0,
            levels_consumed=0,
            reason="INVALID_REQUEST",
        )

    raw_levels = asks if side.upper() in {"BUY", "LONG"} else bids
    levels = _clean_levels(raw_levels, reverse=side.upper() not in {"BUY", "LONG"})
    remaining = requested
    filled_notional = 0.0
    filled_qty = 0.0
    consumed = 0
    for level in levels:
        available_notional = level.price * level.size
        if available_notional <= 0:
            continue
        take_notional = min(remaining, available_notional)
        filled_notional += take_notional
        filled_qty += take_notional / level.price
        remaining -= take_notional
        consumed += 1
        if remaining <= 1e-9:
            break

    if filled_notional <= 0 or filled_qty <= 0:
        return DepthExecutionResult(
            requested_notional_usdc=round(requested, 8),
            filled_notional_usdc=0.0,
            missed_notional_usdc=round(requested, 8),
            average_fill_price=None,
            fill_ratio=0.0,
            partial=False,
            missed=True,
            slippage_bps=0.0,
            levels_consumed=0,
            reason="NO_DEPTH",
        )

    avg = filled_notional / filled_qty
    fill_ratio = min(1.0, filled_notional / requested)
    partial = fill_ratio < 0.999999
    missed = fill_ratio < max(0.0, float(min_fill_ratio or 0.0))
    if side.upper() in {"BUY", "LONG"}:
        slippage = max(0.0, (avg / mid - 1.0) * 10_000.0)
    else:
        slippage = max(0.0, (1.0 - avg / mid) * 10_000.0)
    return DepthExecutionResult(
        requested_notional_usdc=round(requested, 8),
        filled_notional_usdc=round(filled_notional, 8),
        missed_notional_usdc=round(max(0.0, requested - filled_notional), 8),
        average_fill_price=round(avg, 10),
        fill_ratio=round(fill_ratio, 8),
        partial=partial,
        missed=missed,
        slippage_bps=round(slippage, 8),
        levels_consumed=consumed,
        reason="MISSED_FILL" if missed else "PARTIAL_FILL" if partial else "FILLED",
    )


def _clean_levels(
    raw_levels: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    reverse: bool,
) -> list[BookLevel]:
    levels: list[BookLevel] = []
    for price, size in raw_levels:
        p = float(price or 0.0)
        s = float(size or 0.0)
        if p > 0 and s > 0:
            levels.append(BookLevel(price=p, size=s))
    return sorted(levels, key=lambda level: level.price, reverse=reverse)


__all__ = [
    "ExecModelConfig",
    "ExecResult",
    "DepthExecutionResult",
    "estimate_slippage_bps",
    "simulate_execution",
    "simulate_depth_execution",
    "round_trip_cost_bps",
]

def _env_adverse_selection_bps() -> float:
    import os

    try:
        return max(0.0, float(os.environ.get("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS", "0")))
    except (TypeError, ValueError):
        return 0.0
