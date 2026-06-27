"""Stop-loss / take-profit / trailing exit logic (S8 — V9, CloddsBot / MrFadiAi).

Gives a paper position its own exit discipline instead of only closing when the
leader closes: a hard stop-loss, a take-profit target, and an optional trailing
stop that locks in gains once price has run in our favour. All thresholds are in
bps of the entry price; PnL is computed signed for LONG and SHORT.

Pure and deterministic — the caller feeds entry / current / peak prices and gets
back an exit verdict + reason. SAFETY: an "EXIT" verdict is a *paper* close
decision, never a real order, signature, or venue call.
"""

from __future__ import annotations

from dataclasses import dataclass

HOLD = "HOLD"
STOP_LOSS = "STOP_LOSS"
TAKE_PROFIT = "TAKE_PROFIT"
TRAILING_STOP = "TRAILING_STOP"


@dataclass(frozen=True, slots=True)
class SLTPConfig:
    stop_loss_bps: float = 150.0          # -1.5%
    take_profit_bps: float = 250.0        # +2.5%
    trailing_stop_bps: float | None = None  # e.g. 120 -> exit on 1.2% give-back from peak
    trailing_activation_bps: float | None = None  # arm trailing only after a real favourable move
    breakeven_buffer_bps: float = 0.0      # trailing never exits below this signed PnL
    # below this absolute move (bps) nothing triggers (avoids churn at the floor)
    min_move_bps: float = 0.0


@dataclass(frozen=True, slots=True)
class SLTPDecision:
    exit: bool
    reason: str
    pnl_bps: float            # signed PnL of the position at current price
    favorable_excursion_bps: float  # best signed PnL seen (for trailing)

    @property
    def hold(self) -> bool:
        return not self.exit


def signed_pnl_bps(side: str, entry_price: float, price: float) -> float:
    """Signed PnL in bps for a LONG/SHORT position (entry vs price)."""
    if entry_price <= 0:
        return 0.0
    move = (price - entry_price) / entry_price * 10_000.0
    return -move if side.upper() in {"SHORT", "SELL"} else move


def evaluate_sl_tp(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    peak_price: float | None = None,
    config: SLTPConfig | None = None,
) -> SLTPDecision:
    """Decide whether a paper position should exit now.

    ``peak_price`` is the most favourable price seen since entry (highest for a
    LONG, lowest for a SHORT); pass it to enable the trailing stop.
    """
    cfg = config or SLTPConfig()
    pnl = signed_pnl_bps(side, entry_price, current_price)

    # best favourable excursion so far (for trailing) — from peak if given,
    # otherwise the current PnL.
    fav = pnl
    if peak_price is not None:
        fav = max(pnl, signed_pnl_bps(side, entry_price, peak_price))

    if abs(pnl) >= cfg.min_move_bps:
        if pnl <= -abs(cfg.stop_loss_bps):
            return SLTPDecision(True, STOP_LOSS, round(pnl, 6), round(fav, 6))
        if pnl >= abs(cfg.take_profit_bps):
            return SLTPDecision(True, TAKE_PROFIT, round(pnl, 6), round(fav, 6))

    if cfg.trailing_stop_bps is not None and fav > 0:
        activation = (
            abs(float(cfg.trailing_activation_bps))
            if cfg.trailing_activation_bps is not None
            else abs(float(cfg.trailing_stop_bps))
        )
        give_back = fav - pnl
        if (
            fav >= activation
            and pnl > float(cfg.breakeven_buffer_bps)
            and give_back >= abs(cfg.trailing_stop_bps)
        ):
            return SLTPDecision(True, TRAILING_STOP, round(pnl, 6), round(fav, 6))

    return SLTPDecision(False, HOLD, round(pnl, 6), round(fav, 6))


__all__ = [
    "HOLD",
    "STOP_LOSS",
    "TAKE_PROFIT",
    "TRAILING_STOP",
    "SLTPConfig",
    "SLTPDecision",
    "signed_pnl_bps",
    "evaluate_sl_tp",
]
