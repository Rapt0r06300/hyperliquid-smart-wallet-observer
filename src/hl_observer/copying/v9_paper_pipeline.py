"""V9 — Pipeline copy-trade paper END-TO-END (colonne vertébrale exécutable).

Chaîne, sur un flux de fills de leaders, toute la logique V9 :
  fill -> porte d'admission (fill_admission) -> gate edge net / liquidité / fraîcheur
       -> OUVERTURE paper (au prix marché RÉEL fourni) ; ou FERMETURE paper + PnL réalisé
  -> equity (réalisé + latent) + ledger de décisions + verdict OFFRE/GATES.

100 % pur et déterministe : aucun réseau, aucune donnée inventée. Les prix marché sont
FOURNIS par l'appelant (réels Hyperliquid) ; si un prix manque -> NO_TRADE (jamais 0 inventé).
read-only / paper-only / execution="forbidden". Ce n'est pas un ordre, pas une promesse de gain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256

from hl_observer.signals.fill_admission import (
    FillAdmissionConfig,
    admit_live_fill,
    fill_identity,
    KIND_ENTRY,
    KIND_EXIT,
)
from hl_observer.signals.entry_supply_diagnostics import CycleEvent, build_entry_supply_report, EntrySupplyReport


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class V9PipelineConfig:
    starting_equity_usdt: float = 1000.0
    max_position_notional_usdt: float = 50.0
    max_total_exposure_usdt: float = 200.0
    min_edge_bps: float = 10.0
    single_wallet_min_edge_bps: float = 15.0
    min_liquidity_score: float = 0.3
    max_signal_age_ms: int = 30_000
    hard_backfill_age_ms: int = 60_000
    fee_bps: float = 2.5
    spread_bps: float = 3.0
    slippage_bps: float = 1.5
    single_wallet_penalty_bps: float = 1.0
    default_reduce_fraction: float = 0.5
    min_remaining_notional_usdt: float = 5.0
    allow_add_as_entry: bool = True
    allow_exotic_markets: bool = False
    read_only: bool = True
    execution: str = "forbidden"


@dataclass(slots=True)
class PaperPosition:
    coin: str
    side: str            # LONG | SHORT
    notional_usdt: float
    entry_price: float
    wallet: str
    opened_ts_ms: int


@dataclass(slots=True)
class V9SessionResult:
    starting_equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    equity_usdt: float
    entries_opened: int
    exits_closed: int
    reduces_applied: int
    open_positions: dict[str, PaperPosition]
    decisions: list[dict]
    supply_report: EntrySupplyReport
    read_only: bool = True
    execution: str = "forbidden"


def _position_key(wallet: str, coin: str, side: str) -> str:
    return f"{str(wallet).lower()}|{str(coin).upper()}|{str(side).upper()}"


def _paper_ref(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}:" + sha256(raw.encode("utf-8")).hexdigest()[:20]


def _decision(**payload: object) -> dict:
    row = {
        "simulation_only": True,
        "read_only": True,
        "external_action": False,
        "execution": "forbidden",
        "venue_endpoint": None,
        "secret_material_used": False,
    }
    row.update(payload)
    row["evidence_hash"] = "ev:" + sha256(
        json.dumps(row, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    return row


def _exit_fraction(action: str, fill: dict, cfg: V9PipelineConfig) -> float:
    if action in {"CLOSE_LONG", "CLOSE_SHORT"}:
        return 1.0
    for key in ("reduce_fraction", "close_fraction", "leader_reduce_fraction"):
        if fill.get(key) is not None:
            try:
                return _clamp(float(fill[key]), 0.0, 1.0)
            except (TypeError, ValueError):
                break
    return _clamp(cfg.default_reduce_fraction, 0.0, 1.0)


def _net_edge_bps(*, leader_edge_bps: float, age_ms: int, consensus_wallets: int, cfg: V9PipelineConfig) -> float:
    freshness = _clamp(1.0 - max(0, age_ms) / max(1, cfg.max_signal_age_ms))
    consensus_factor = _clamp(1.0 + 0.08 * max(0, consensus_wallets - 1), 1.0, 1.25)
    single_wallet_penalty = cfg.single_wallet_penalty_bps if consensus_wallets < 2 else 0.0
    costs = cfg.fee_bps + cfg.spread_bps + cfg.slippage_bps + single_wallet_penalty
    return float(leader_edge_bps) * freshness * consensus_factor - costs


def _signed_pnl_usdt(side: str, notional: float, entry: float, mark: float) -> float:
    if entry <= 0:
        return 0.0
    move = (mark - entry) / entry
    if side.upper() == "SHORT":
        move = -move
    return notional * move


def run_v9_paper_session(
    fills: list[dict],
    *,
    now_ms: int,
    mark_price: dict[str, float] | None = None,
    config: V9PipelineConfig | None = None,
) -> V9SessionResult:
    """Rejoue un flux de fills de leaders en simulation paper end-to-end.

    Chaque `fill` (dict) : wallet, coin, side(LONG/SHORT), action_type, price, size,
    notional_usdc, fill_ts_ms, leader_edge_bps, liquidity_score, leader_score, consensus_wallets.
    `mark_price[coin]` = prix marché RÉEL courant (None si indisponible -> NO_TRADE).
    """
    cfg = config or V9PipelineConfig()
    marks = mark_price or {}
    adm_cfg = FillAdmissionConfig(
        max_signal_age_ms=cfg.max_signal_age_ms,
        hard_backfill_age_ms=cfg.hard_backfill_age_ms,
        allow_add_as_entry=cfg.allow_add_as_entry,
        allow_exotic_markets=cfg.allow_exotic_markets,
    )

    book: dict[str, PaperPosition] = {}
    seen: set[str] = set()
    realized = 0.0
    entries = exits = reduces = 0
    events: list[CycleEvent] = []
    decisions: list[dict] = []

    for f in fills:
        coin = str(f.get("coin") or "").upper()
        side = str(f.get("side") or "").upper()
        action = str(f.get("action_type") or "").upper()
        wallet = str(f.get("wallet") or "")
        fid = fill_identity(
            wallet_address=wallet, coin=coin, side=side, action_type=action,
            price=float(f.get("price") or 0.0), size=float(f.get("size") or 0.0),
            ts_ms=int(f.get("fill_ts_ms") or 0),
        )
        key = _position_key(wallet, coin, side)
        adm = admit_live_fill(
            action_type=action, coin=coin, fill_ts_ms=int(f.get("fill_ts_ms") or 0), now_ms=now_ms,
            already_seen=fid in seen, has_matching_paper_position=key in book,
            leader_price=f.get("price"), config=adm_cfg,
        )
        seen.add(fid)

        if not adm.admit:
            events.append(CycleEvent(admission=adm))
            if adm.log_decision:
                decisions.append(_decision(
                    coin=coin,
                    side=side,
                    action_type=action,
                    wallet=wallet,
                    status="REFUSED",
                    reason=adm.reason,
                    raw_event_hash=fid,
                ))
            continue

        if adm.kind == KIND_ENTRY:
            mark = f.get("mark_price") if f.get("mark_price") is not None else marks.get(coin)
            if mark is None or mark <= 0:
                events.append(CycleEvent(admission=adm, accepted=False, refusal_reason="PRICE_MISSING"))
                decisions.append(_decision(
                    coin=coin,
                    side=side,
                    action_type=action,
                    wallet=wallet,
                    status="REFUSED",
                    reason="PRICE_MISSING",
                    raw_event_hash=fid,
                ))
                continue
            edge = _net_edge_bps(
                leader_edge_bps=float(f.get("leader_edge_bps") or 0.0),
                age_ms=adm.age_ms, consensus_wallets=int(f.get("consensus_wallets") or 1), cfg=cfg,
            )
            liquidity = float(f.get("liquidity_score") or 0.0)
            consensus = int(f.get("consensus_wallets") or 1)
            min_edge = cfg.single_wallet_min_edge_bps if consensus < 2 else cfg.min_edge_bps
            reason = None
            if liquidity < cfg.min_liquidity_score:
                reason = "LIQUIDITY_TOO_LOW"
            elif edge < min_edge:
                reason = "EDGE_REMAINING_TOO_LOW"
            else:
                exposure = sum(p.notional_usdt for p in book.values())
                notional = min(cfg.max_position_notional_usdt, max(0.0, cfg.max_total_exposure_usdt - exposure))
                if notional <= 0:
                    reason = "MAX_EXPOSURE_REACHED"
            if reason:
                events.append(CycleEvent(admission=adm, accepted=False, refusal_reason=reason))
                decisions.append(_decision(
                    coin=coin,
                    side=side,
                    action_type=action,
                    wallet=wallet,
                    status="REFUSED",
                    reason=reason,
                    edge_bps=round(edge, 4),
                    raw_event_hash=fid,
                ))
                continue
            # OUVERTURE paper au prix marché réel
            existing = book.get(key)
            if existing:
                total_notional = existing.notional_usdt + notional
                avg_entry = (
                    existing.entry_price * existing.notional_usdt + float(mark) * notional
                ) / total_notional
                book[key] = PaperPosition(
                    coin=coin,
                    side=side,
                    notional_usdt=round(total_notional, 8),
                    entry_price=round(avg_entry, 10),
                    wallet=wallet,
                    opened_ts_ms=existing.opened_ts_ms,
                )
                status = "PAPER_INCREASE"
            else:
                book[key] = PaperPosition(
                    coin=coin, side=side, notional_usdt=notional, entry_price=float(mark),
                    wallet=wallet, opened_ts_ms=int(f.get("fill_ts_ms") or now_ms),
                )
                status = "PAPER_ENTRY"
            realized -= notional * (cfg.fee_bps / 10_000.0)  # frais d'entrée
            entries += 1
            events.append(CycleEvent(admission=adm, accepted=True))
            decisions.append(_decision(
                coin=coin,
                side=side,
                action_type=action,
                wallet=wallet,
                status=status,
                paper_ref=_paper_ref(status.lower(), fid, key, mark, notional),
                notional_usdt=round(notional, 4),
                position_notional_usdt=round(book[key].notional_usdt, 4),
                entry_price=float(mark),
                average_entry_price=book[key].entry_price,
                edge_bps=round(edge, 4),
                raw_event_hash=fid,
            ))

        elif adm.kind == KIND_EXIT:
            pos = book.get(key)
            mark = f.get("mark_price") if f.get("mark_price") is not None else marks.get(coin)
            if not mark or mark <= 0:
                events.append(CycleEvent(admission=adm, accepted=False, refusal_reason="PRICE_MISSING_EXIT"))
                decisions.append(_decision(
                    coin=coin,
                    side=side,
                    action_type=action,
                    wallet=wallet,
                    status="REFUSED",
                    reason="PRICE_MISSING_EXIT",
                    raw_event_hash=fid,
                ))
                continue
            if pos:
                fraction = _exit_fraction(action, f, cfg)
                if fraction <= 0:
                    events.append(CycleEvent(admission=adm, accepted=False, refusal_reason="INVALID_REDUCE_FRACTION"))
                    decisions.append(_decision(
                        coin=coin,
                        side=pos.side,
                        action_type=action,
                        wallet=wallet,
                        status="REFUSED",
                        reason="INVALID_REDUCE_FRACTION",
                        raw_event_hash=fid,
                    ))
                    continue
                notional_closed = pos.notional_usdt * fraction
                full_pnl = _signed_pnl_usdt(pos.side, pos.notional_usdt, pos.entry_price, float(mark))
                pnl = full_pnl * fraction
                pnl -= notional_closed * (cfg.fee_bps / 10_000.0)  # frais de sortie
                realized += pnl
                remaining = pos.notional_usdt - notional_closed
                full_close = fraction >= 0.999 or remaining < cfg.min_remaining_notional_usdt
                if full_close:
                    del book[key]
                    exits += 1
                    status = "PAPER_EXIT"
                    remaining = 0.0
                else:
                    book[key] = PaperPosition(
                        coin=pos.coin,
                        side=pos.side,
                        notional_usdt=round(remaining, 8),
                        entry_price=pos.entry_price,
                        wallet=pos.wallet,
                        opened_ts_ms=pos.opened_ts_ms,
                    )
                    reduces += 1
                    status = "PAPER_REDUCE"
                events.append(CycleEvent(admission=adm, accepted=True))
                decisions.append(_decision(
                    coin=coin,
                    side=pos.side,
                    action_type=action,
                    wallet=wallet,
                    status=status,
                    paper_ref=_paper_ref(status.lower(), fid, key, mark, fraction),
                    reduce_fraction=round(fraction, 6),
                    notional_closed_usdt=round(notional_closed, 6),
                    remaining_notional_usdt=round(remaining, 6),
                    realized_pnl_usdt=round(pnl, 6),
                    exit_price=float(mark),
                    raw_event_hash=fid,
                ))

    # latent (mark-to-market sur prix réels)
    unrealized = 0.0
    for p in book.values():
        mark = marks.get(p.coin)
        if mark and mark > 0:
            unrealized += _signed_pnl_usdt(p.side, p.notional_usdt, p.entry_price, float(mark))

    equity = cfg.starting_equity_usdt + realized + unrealized
    return V9SessionResult(
        starting_equity_usdt=cfg.starting_equity_usdt,
        realized_pnl_usdt=round(realized, 6),
        unrealized_pnl_usdt=round(unrealized, 6),
        equity_usdt=round(equity, 6),
        entries_opened=entries,
        exits_closed=exits,
        reduces_applied=reduces,
        open_positions=book,
        decisions=decisions,
        supply_report=build_entry_supply_report(events),
    )


__all__ = ["V9PipelineConfig", "PaperPosition", "V9SessionResult", "run_v9_paper_session"]
