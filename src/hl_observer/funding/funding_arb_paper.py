"""Moteur funding-arbitrage delta-neutre PAPER (mode grinder, brique 2).

Distillé du repo 32_gajesh2007_funding_arb_bot (+ règles Hummingbot):
beaucoup de petites paires delta-neutres qui encaissent le funding horaire,
zéro risque directionnel modélisé. 100 % paper: aucune position réelle,
aucun ordre, aucune venue contactée — les entrées/accruals/sorties sont des
événements de ledger explicables.

Règles portées:
- entrée si |funding horaire| >= seuil ET rate stable (pas de spike 2σ vs 24h);
- sortie si |funding| < seuil de sortie (edge effondré) ou âge max atteint;
- PnL = funding accumulé - coûts d'entrée/sortie des DEUX jambes (maker par
  défaut + adverse selection), jamais de PnL prix (paires supposées couvertes;
  la divergence de prix réelle est un risque listé, pas simulé comme gain).
- caps: max paires simultanées, notional par jambe, notional total.

Aucune promesse de PnL. Si les données funding manquent: NO_TRADE.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from hl_observer.funding.funding_carry_economics import REFUS_NON_COUVERT
from hl_observer.funding.spike_detector import detect_funding_spike

ENV_ENABLED = "HYPERSMART_FUNDING_ARB_PAPER"

# VERROU CARRY (2026-07-11) -- adosse a une MESURE, pas a une intuition.
# 232 marches, 9 512 releves : funding median 0,125 bps/h, mouvement de prix ~35 bps/h.
# Pour 1 bps de funding encaisse, une jambe NUE subit ~281 bps de mouvement de prix.
# Cette "paire delta-neutre" n'a QU'UNE jambe. Ouvrir dessus, c'est parier sur le prix en
# pretendant encaisser du portage. DEFAUT = refus. Le flag n'existe que pour l'A/B et le legacy.
ENV_ALLOW_UNHEDGED_LEG = "HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG"


def unhedged_leg_allowed() -> bool:
    return str(os.environ.get(ENV_ALLOW_UNHEDGED_LEG, "0")).strip().lower() in _ENABLED_VALUES
_ENABLED_VALUES = {"1", "true", "yes", "on"}


def funding_arb_paper_enabled() -> bool:
    return str(os.environ.get(ENV_ENABLED, "0")).strip().lower() in _ENABLED_VALUES


@dataclass(frozen=True, slots=True)
class FundingArbConfig:
    min_entry_edge_bps_per_hour: float = 2.5   # ~20 bps/8h (repo 32: minEdge 20)
    exit_edge_bps_per_hour: float = 0.65       # ~5 bps/8h (repo 32: exitEdge 5)
    spike_sigma: float = 2.0                   # anti-spike 2σ vs historique
    min_history_points: int = 8                # jamais entrer sans historique
    leg_notional_usdt: float = 25.0
    max_pairs: int = 5                         # top-N symboles (repo 32: 5)
    max_total_notional_usdt: float = 250.0
    max_hold_hours: float = 72.0
    entry_cost_bps_per_leg: float = 1.0        # maker + adverse (2 jambes)
    exit_cost_bps_per_leg: float = 1.0
    hedge_venue_extra_bps: float = 1.0         # coût forfaitaire jambe de couverture

    @classmethod
    def from_env(cls) -> "FundingArbConfig":
        def _f(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name, ""))
            except (TypeError, ValueError):
                return default

        def _i(name: str, default: int) -> int:
            try:
                return int(float(os.environ.get(name, "")))
            except (TypeError, ValueError):
                return default

        base = cls()  # slots=True: les défauts ne sont pas lisibles via cls.attr
        return cls(
            min_entry_edge_bps_per_hour=_f("HYPERSMART_FUNDING_ARB_MIN_EDGE_BPS_H", base.min_entry_edge_bps_per_hour),
            exit_edge_bps_per_hour=_f("HYPERSMART_FUNDING_ARB_EXIT_EDGE_BPS_H", base.exit_edge_bps_per_hour),
            leg_notional_usdt=_f("HYPERSMART_FUNDING_ARB_LEG_NOTIONAL_USDT", base.leg_notional_usdt),
            max_pairs=_i("HYPERSMART_FUNDING_ARB_MAX_PAIRS", base.max_pairs),
            max_total_notional_usdt=_f("HYPERSMART_FUNDING_ARB_MAX_TOTAL_USDT", base.max_total_notional_usdt),
            max_hold_hours=_f("HYPERSMART_FUNDING_ARB_MAX_HOLD_HOURS", base.max_hold_hours),
        )


@dataclass(frozen=True, slots=True)
class FundingArbPosition:
    pair_id: str
    coin: str
    receiving_side: str            # jambe HL qui ENCAISSE le funding: LONG ou SHORT
    leg_notional_usdt: float
    entry_rate_bps_per_hour: float
    opened_at_ms: int
    # SANS LUI, LE PnL EST UNE FICTION (bug corrige le 2026-07-11).
    # La position n'a qu'UNE jambe : c'est donc une position NUE sur un perp. Son PnL valait
    #     net = funding encaisse - couts
    # sans AUCUN terme de prix -- un revenu sans risque de marche, ce qui n'existe pas.
    entry_price: float = 0.0
    accrued_funding_usdc: float = 0.0
    entry_costs_usdc: float = 0.0
    last_accrual_at_ms: int = 0
    paper_only: bool = True
    read_only: bool = True
    real_execution: bool = False


@dataclass(frozen=True, slots=True)
class FundingArbEvent:
    action: str                    # OPEN | ACCRUAL | CLOSE | NO_TRADE
    coin: str
    pair_id: str
    reason: str
    rate_bps_per_hour: float | None = None
    amount_usdc: float = 0.0
    net_pnl_usdc: float | None = None
    # None = prix inconnu -> on NE SAIT PAS ce qu'a fait la position. On ne l'invente pas.
    price_pnl_usdc: float | None = None
    price_pnl_unknown: bool = False
    event_id: str | None = None
    paper_only: bool = True
    real_execution: bool = False


@dataclass(frozen=True, slots=True)
class FundingArbReport:
    positions: tuple[FundingArbPosition, ...]
    events: tuple[FundingArbEvent, ...]
    open_pairs: int
    total_notional_usdt: float
    realized_pnl_usdc: float
    message: str = "delta-neutral funding farming; paper-only; no price PnL modeled"


def _price_pnl_usdc(pos: "FundingArbPosition", prix_sortie: float) -> float | None:
    """PnL de PRIX de la jambe NUE. None = prix inconnu -> on n'invente RIEN.

    `receiving_side` est le sens de la jambe detenue sur Hyperliquid :
      * SHORT -> on gagne quand le prix BAISSE ;
      * LONG  -> on gagne quand le prix MONTE.
    Ignorer ce terme revenait a encaisser du funding sans jamais porter le risque du marche.
    """
    entree = float(pos.entry_price or 0.0)
    sortie = float(prix_sortie or 0.0)
    if entree <= 0.0 or sortie <= 0.0:
        return None                       # etat vide honnete : pas de prix, pas de chiffre
    variation = (sortie - entree) / entree
    sens = 1.0 if str(pos.receiving_side).upper() == "LONG" else -1.0
    return pos.leg_notional_usdt * variation * sens


def _hourly_rate_bps(rates: list[float]) -> float | None:
    if not rates:
        return None
    return float(rates[-1]) * 10_000.0


def _funding_event_id(
    pair_id: str,
    action: str,
    *,
    causal_timestamp_ms: int | None = None,
) -> str:
    """Build a replay-stable identity from causal funding state."""

    suffix = (
        f":{int(causal_timestamp_ms)}"
        if causal_timestamp_ms is not None and action.upper() == "ACCRUAL"
        else ""
    )
    return f"{pair_id}:{action.lower()}{suffix}"


def evaluate_funding_arb(
    *,
    funding_rows: tuple[dict[str, object], ...],
    prices: dict[str, float],
    positions: tuple[FundingArbPosition, ...],
    now_ms: int,
    config: FundingArbConfig | None = None,
) -> FundingArbReport:
    """Un pas de décision funding-arb paper (pur, déterministe, sans I/O)."""

    cfg = config or FundingArbConfig.from_env()
    events: list[FundingArbEvent] = []
    realized = 0.0
    book: dict[str, FundingArbPosition] = {p.coin: p for p in positions}
    rows_by_coin: dict[str, list[float]] = {}
    for row in funding_rows:
        coin = str(row.get("coin") or "").upper()
        if coin:
            rows_by_coin[coin] = [float(x) for x in row.get("rates", [])]

    # 1) Gérer les paires ouvertes: accrual horaire, sortie si edge mort/expiré.
    survivors: dict[str, FundingArbPosition] = {}
    for coin, pos in book.items():
        rates = rows_by_coin.get(coin, [])
        rate_bps = _hourly_rate_bps(rates)
        if rate_bps is None:
            # Donnée manquante: on n'invente rien, on ferme proprement au coût.
            close_costs = 2 * pos.leg_notional_usdt * (cfg.exit_cost_bps_per_leg + cfg.hedge_venue_extra_bps / 2) / 10_000.0
            _px = _price_pnl_usdc(pos, float(prices.get(coin, 0.0) or 0.0))
            net = (
                pos.accrued_funding_usdc + _px - pos.entry_costs_usdc - close_costs
                if _px is not None
                else None
            )
            if net is not None:
                realized += net
            _reason = (
                "FUNDING_DATA_MISSING"
                if _px is not None
                else "PNL_UNMEASURABLE_PRICE_UNKNOWN_FUNDING_DATA_MISSING"
            )
            events.append(
                FundingArbEvent(
                    "CLOSE",
                    coin,
                    pos.pair_id,
                    _reason,
                    None,
                    round(close_costs, 8),
                    round(net, 8) if net is not None else None,
                    price_pnl_usdc=(round(_px, 8) if _px is not None else None),
                    price_pnl_unknown=(_px is None),
                    event_id=_funding_event_id(pos.pair_id, "CLOSE"),
                )
            )
            continue
        receiving_rate = rate_bps if pos.receiving_side == "SHORT" else -rate_bps
        hours_open = max(0.0, (now_ms - (pos.last_accrual_at_ms or pos.opened_at_ms)) / 3_600_000.0)
        accrual = 0.0
        if hours_open >= 1.0:
            whole_hours = int(hours_open)
            accrual = pos.leg_notional_usdt * (receiving_rate / 10_000.0) * whole_hours
            pos = replace(
                pos,
                accrued_funding_usdc=round(pos.accrued_funding_usdc + accrual, 8),
                last_accrual_at_ms=(pos.last_accrual_at_ms or pos.opened_at_ms) + whole_hours * 3_600_000,
            )
            events.append(
                FundingArbEvent(
                    "ACCRUAL",
                    coin,
                    pos.pair_id,
                    f"FUNDING_ACCRUED_{whole_hours}H",
                    round(receiving_rate, 4),
                    round(accrual, 8),
                    event_id=_funding_event_id(
                        pos.pair_id,
                        "ACCRUAL",
                        causal_timestamp_ms=pos.last_accrual_at_ms,
                    ),
                )
            )

        age_hours = (now_ms - pos.opened_at_ms) / 3_600_000.0
        edge_alive = abs(receiving_rate) >= cfg.exit_edge_bps_per_hour and receiving_rate > 0
        if not edge_alive or age_hours >= cfg.max_hold_hours:
            close_costs = 2 * pos.leg_notional_usdt * (cfg.exit_cost_bps_per_leg + cfg.hedge_venue_extra_bps / 2) / 10_000.0
            _px = _price_pnl_usdc(pos, float(prices.get(coin, 0.0) or 0.0))
            net = (
                pos.accrued_funding_usdc + _px - pos.entry_costs_usdc - close_costs
                if _px is not None
                else None
            )
            if net is not None:
                realized += net
            reason = "MAX_HOLD_REACHED" if age_hours >= cfg.max_hold_hours else "FUNDING_EDGE_COLLAPSED"
            if _px is None:
                reason = "PNL_UNMEASURABLE_PRICE_UNKNOWN_" + reason
            events.append(
                FundingArbEvent(
                    "CLOSE",
                    coin,
                    pos.pair_id,
                    reason,
                    round(receiving_rate, 4),
                    round(close_costs, 8),
                    round(net, 8) if net is not None else None,
                    price_pnl_usdc=(round(_px, 8) if _px is not None else None),
                    price_pnl_unknown=(_px is None),
                    event_id=_funding_event_id(pos.pair_id, "CLOSE"),
                )
            )
            continue
        survivors[coin] = pos

    # 2) Nouvelles entrées: edge fort, stable, prix connu, caps respectés.
    candidates: list[tuple[float, str, float]] = []
    for coin, rates in rows_by_coin.items():
        if coin in survivors:
            continue
        rate_bps = _hourly_rate_bps(rates)
        if rate_bps is None or len(rates) < cfg.min_history_points:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "FUNDING_HISTORY_TOO_SHORT", rate_bps))
            continue
        if abs(rate_bps) < cfg.min_entry_edge_bps_per_hour:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "FUNDING_EDGE_TOO_SMALL", round(rate_bps, 4)))
            continue
        spike = detect_funding_spike(rates, sigma=cfg.spike_sigma)
        if spike.spike:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "FUNDING_SPIKE_UNSTABLE", round(rate_bps, 4)))
            continue
        if float(prices.get(coin, 0.0) or 0.0) <= 0:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "MARKET_PRICE_MISSING", round(rate_bps, 4)))
            continue
        candidates.append((abs(rate_bps), coin, rate_bps))

    candidates.sort(reverse=True)
    total_notional = sum(2 * p.leg_notional_usdt for p in survivors.values())
    for _, coin, rate_bps in candidates:
        if len(survivors) >= cfg.max_pairs:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "MAX_PAIRS_REACHED", round(rate_bps, 4)))
            continue
        pair_notional = 2 * cfg.leg_notional_usdt
        if total_notional + pair_notional > cfg.max_total_notional_usdt:
            events.append(FundingArbEvent("NO_TRADE", coin, "", "MAX_TOTAL_NOTIONAL_REACHED", round(rate_bps, 4)))
            continue
        # VERROU CARRY : la jambe est NUE (une seule jambe). La mesure dit que le prix
        # noie le funding d'un facteur ~281. On refuse par defaut.
        if not unhedged_leg_allowed():
            events.append(FundingArbEvent("NO_TRADE", coin, "", REFUS_NON_COUVERT, round(rate_bps, 4)))
            continue

        receiving_side = "SHORT" if rate_bps > 0 else "LONG"
        entry_costs = 2 * cfg.leg_notional_usdt * (cfg.entry_cost_bps_per_leg + cfg.hedge_venue_extra_bps / 2) / 10_000.0
        pair_id = f"fundingarb:{coin}:{now_ms}"
        survivors[coin] = FundingArbPosition(
            pair_id=pair_id,
            coin=coin,
            receiving_side=receiving_side,
            leg_notional_usdt=cfg.leg_notional_usdt,
            entry_rate_bps_per_hour=round(rate_bps, 4),
            opened_at_ms=now_ms,
            entry_price=float(prices.get(coin, 0.0) or 0.0),   # sans lui, le PnL serait une fiction
            entry_costs_usdc=round(entry_costs, 8),
            last_accrual_at_ms=now_ms,
        )
        total_notional += pair_notional
        events.append(
            FundingArbEvent(
                "OPEN",
                coin,
                pair_id,
                f"FUNDING_EDGE_{receiving_side}_RECEIVES",
                round(rate_bps, 4),
                round(entry_costs, 8),
                event_id=_funding_event_id(pair_id, "OPEN"),
            )
        )

    return FundingArbReport(
        positions=tuple(survivors.values()),
        events=tuple(events),
        open_pairs=len(survivors),
        total_notional_usdt=round(sum(2 * p.leg_notional_usdt for p in survivors.values()), 8),
        realized_pnl_usdc=round(realized, 8),
    )




# --- Store process-local des paires ouvertes (recherche paper uniquement) ---
# Limitation assumée: un restart du serveur repart à plat (les paires ouvertes
# sont refermées au prochain tick via FUNDING_DATA_MISSING si les données
# manquent, ou recréées si l'edge persiste). Aucun état n'est inventé.
_OPEN_POSITIONS: tuple[FundingArbPosition, ...] = ()


def get_open_funding_arb_positions() -> tuple[FundingArbPosition, ...]:
    return _OPEN_POSITIONS


def set_open_funding_arb_positions(positions: tuple[FundingArbPosition, ...]) -> None:
    global _OPEN_POSITIONS
    _OPEN_POSITIONS = tuple(positions)


def reset_funding_arb_store() -> None:
    set_open_funding_arb_positions(())


__all__ = [
    "ENV_ENABLED",
    "FundingArbConfig",
    "FundingArbEvent",
    "FundingArbPosition",
    "FundingArbReport",
    "evaluate_funding_arb",
    "funding_arb_paper_enabled",
    "get_open_funding_arb_positions",
    "set_open_funding_arb_positions",
    "reset_funding_arb_store",
]
