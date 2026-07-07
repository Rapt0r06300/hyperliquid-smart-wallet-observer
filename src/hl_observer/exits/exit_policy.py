"""Politique d'exit composee (R2/R3/R4) — une seule decision ordonnee.

Compose des primitives DEJA presentes (pas de doublon) :
- trailing : exits.trailing_stop.trailing_stop_price
- time-stop : exits.time_stop.time_stop_triggered
- break-even : risk.scale_out.move_to_breakeven
- scale-out ladder : risk.scale_out.scale_out_plan
et AJOUTE le manque reel : SL/TP dynamiques bases ATR (volatilite).

Pur, sans I/O. Long ET short. Decide un exit PAPER, jamais un ordre reel.
Priorite : STOP_LOSS -> BREAKEVEN_STOP -> TAKE_PROFIT -> TRAILING_STOP -> TIME_STOP -> HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.exits.time_stop import time_stop_triggered
from hl_observer.exits.trailing_stop import trailing_stop_price


def signed_pnl_bps(side: str, entry_price: float, price: float) -> float:
    if entry_price <= 0:
        return 0.0
    raw = (price - entry_price) / entry_price * 10000.0
    return raw if str(side).lower() == "long" else -raw


def favorable_excursion_bps(side: str, entry_price: float, best_price: float) -> float:
    """Meilleur profit atteint (bps) sur la base de l'extreme favorable."""
    return signed_pnl_bps(side, entry_price, best_price)


def atr_sl_tp_bps(atr_bps: float, *, sl_mult: float = 1.5, tp_mult: float = 3.0) -> tuple[float, float]:
    """SL/TP dynamiques proportionnels a la volatilite (ATR en bps).

    Manque reel comble ici : un marche volatil merite un SL/TP plus larges,
    un marche calme des seuils plus serres. Renvoie (sl_bps, tp_bps) positifs.
    """
    a = max(0.0, float(atr_bps))
    return (a * float(sl_mult), a * float(tp_mult))


@dataclass(frozen=True, slots=True)
class ExitPolicyConfig:
    enable_stop_loss: bool = True
    stop_loss_bps: float = 80.0
    enable_take_profit: bool = True
    take_profit_bps: float = 250.0
    enable_breakeven: bool = True
    breakeven_trigger_bps: float = 60.0
    breakeven_buffer_bps: float = 0.0
    enable_trailing: bool = True
    trailing_arm_bps: float = 50.0
    trailing_bps: float = 30.0
    enable_time_stop: bool = True
    max_hold_ms: int = 14_400_000  # 4 h (tony MAX_HOLD_TIME_MINUTES=240)
    enable_atr: bool = False
    atr_sl_mult: float = 1.5
    atr_tp_mult: float = 3.0


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_exit: bool
    reason: str
    pnl_bps: float
    detail: dict


def evaluate_exit(
    *,
    side: str,
    entry_price: float,
    mark_price: float,
    best_price: float,
    age_ms: int,
    config: ExitPolicyConfig,
    atr_bps: float | None = None,
) -> ExitDecision:
    """Decision d'exit composee, ordonnee par priorite. best_price = extreme favorable
    (peak pour long, trough pour short)."""
    side_l = "long" if str(side).lower() == "long" else "short"
    pnl = signed_pnl_bps(side_l, entry_price, mark_price)
    fav = favorable_excursion_bps(side_l, entry_price, best_price)

    sl_bps = config.stop_loss_bps
    tp_bps = config.take_profit_bps
    if config.enable_atr and atr_bps is not None:
        sl_bps, tp_bps = atr_sl_tp_bps(atr_bps, sl_mult=config.atr_sl_mult, tp_mult=config.atr_tp_mult)

    detail = {"sl_bps": round(sl_bps, 4), "tp_bps": round(tp_bps, 4), "fav_bps": round(fav, 4)}

    # 1. Stop-loss dur
    if config.enable_stop_loss and pnl <= -abs(sl_bps):
        return ExitDecision(True, "STOP_LOSS", pnl, detail)

    # 2. Break-even : une fois le profit declenche, on ne laisse plus repasser sous le buffer
    if config.enable_breakeven and fav >= config.breakeven_trigger_bps and pnl <= config.breakeven_buffer_bps:
        return ExitDecision(True, "BREAKEVEN_STOP", pnl, detail)

    # 3. Take-profit
    if config.enable_take_profit and pnl >= abs(tp_bps):
        return ExitDecision(True, "TAKE_PROFIT", pnl, detail)

    # 4. Trailing (une fois arme)
    if config.enable_trailing and fav >= config.trailing_arm_bps:
        stop = trailing_stop_price(side_l, best_price, config.trailing_bps)
        crossed = mark_price <= stop if side_l == "long" else mark_price >= stop
        detail["trailing_stop"] = round(stop, 8)
        if crossed:
            return ExitDecision(True, "TRAILING_STOP", pnl, detail)

    # 5. Time-stop / max-hold
    if config.enable_time_stop and time_stop_triggered(int(age_ms), int(config.max_hold_ms)):
        return ExitDecision(True, "TIME_STOP", pnl, detail)

    return ExitDecision(False, "HOLD", pnl, detail)


__all__ = [
    "signed_pnl_bps",
    "favorable_excursion_bps",
    "atr_sl_tp_bps",
    "ExitPolicyConfig",
    "ExitDecision",
    "evaluate_exit",
]


def exit_policy_config_from_env(env: dict | None = None) -> "ExitPolicyConfig | None":
    """Construit une ExitPolicyConfig depuis l'environnement. Retourne None si
    HYPERSMART_EXIT_POLICY_ENABLED n'est pas explicitement activé (deny-by-default).
    Permet au runtime d'activer la politique composée sans la coder en dur."""
    import os
    e = env if env is not None else os.environ
    if str(e.get("HYPERSMART_EXIT_POLICY_ENABLED", "0")).lower() not in ("1", "true", "yes"):
        return None

    def _f(name: str, default: float) -> float:
        v = e.get(name)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _b(name: str, default: bool) -> bool:
        v = e.get(name)
        return default if v in (None, "") else str(v).lower() in ("1", "true", "yes")

    return ExitPolicyConfig(
        enable_stop_loss=_b("HYPERSMART_EXIT_SL_ENABLED", True),
        stop_loss_bps=_f("HYPERSMART_EXIT_SL_BPS", 80.0),
        enable_take_profit=_b("HYPERSMART_EXIT_TP_ENABLED", True),
        take_profit_bps=_f("HYPERSMART_EXIT_TP_BPS", 250.0),
        enable_breakeven=_b("HYPERSMART_EXIT_BREAKEVEN_ENABLED", True),
        breakeven_trigger_bps=_f("HYPERSMART_EXIT_BREAKEVEN_TRIGGER_BPS", 60.0),
        enable_trailing=_b("HYPERSMART_EXIT_TRAILING_ENABLED", True),
        trailing_arm_bps=_f("HYPERSMART_EXIT_TRAILING_ARM_BPS", 50.0),
        trailing_bps=_f("HYPERSMART_EXIT_TRAILING_BPS", 30.0),
        enable_time_stop=_b("HYPERSMART_EXIT_TIME_STOP_ENABLED", True),
        max_hold_ms=int(_f("HYPERSMART_EXIT_MAX_HOLD_MS", 14_400_000)),
        enable_atr=_b("HYPERSMART_EXIT_ATR_ENABLED", False),
        atr_sl_mult=_f("HYPERSMART_EXIT_ATR_SL_MULT", 1.5),
        atr_tp_mult=_f("HYPERSMART_EXIT_ATR_TP_MULT", 3.0),
    )


__all__.append("exit_policy_config_from_env")
