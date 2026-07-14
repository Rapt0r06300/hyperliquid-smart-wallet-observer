"""V26 L4 — Halt gradué GREEN/AMBER/RED (porté de passivbot equity_hard_stop_loss).

Machine à états supervisant le drawdown RÉALISÉ fenêtré (source : ledger, via le
ProtectionsBook ou une somme directe) :

* GREEN : normal.
* AMBER : perte fenêtrée >= seuil amber ⇒ taille réduite (multiplier) + nouvelles
  entrées interdites sur les marchés sans position existante.
* RED   : perte fenêtrée >= seuil red ⇒ toutes entrées interdites + sorties forcées
  (paper) ; retour vers AMBER puis GREEN uniquement après **cooldown** (anti yo-yo,
  « cooldown contracts » passivbot).

Wrapper ADDITIF au hard-halt V25 existant : ne le remplace pas, ne l'affaiblit pas
(le plus strict des deux gagne toujours). Opt-in : ``HYPERSMART_V26_GRADED_HALT=1``.
Paper-only : un « force exit » est un événement ledger simulé, jamais un ordre.
"""

from __future__ import annotations
from hl_observer.strategies.strategy_mode import mode_of_position

import os
import threading
from dataclasses import dataclass

MASTER_FLAG = "HYPERSMART_V26_GRADED_HALT"
AMBER_LOSS_ENV = "HYPERSMART_V26_HALT_AMBER_LOSS_USD"
RED_LOSS_ENV = "HYPERSMART_V26_HALT_RED_LOSS_USD"
WINDOW_ENV = "HYPERSMART_V26_HALT_WINDOW_MIN"
COOLDOWN_ENV = "HYPERSMART_V26_HALT_COOLDOWN_MIN"
AMBER_SIZE_MULT_ENV = "HYPERSMART_V26_HALT_AMBER_SIZE_MULT"

_DEF = {
    AMBER_LOSS_ENV: 12.0,        # perte réalisée fenêtre -> AMBER
    RED_LOSS_ENV: 25.0,          # -> RED (aligné hard halt 2.5% d'une equity 1000)
    WINDOW_ENV: 240.0,           # 4 h
    COOLDOWN_ENV: 45.0,          # 45 min par palier de descente
    AMBER_SIZE_MULT_ENV: 0.5,
}

GREEN, AMBER, RED = "GREEN", "AMBER", "RED"
REASON_AMBER = "GRADED_HALT_AMBER"
REASON_RED = "GRADED_HALT_RED"


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def realized_window_pnl_usd(ledger_events: list[dict], now_ms: int, window_min: float) -> float:
    """PnL réalisé (closes) de la fenêtre — depuis le ledger, vérité unique."""
    cutoff = int(now_ms) - int(window_min * 60_000)
    total = 0.0
    for ev in ledger_events or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("paper_action_type") or "").upper() != "CLOSE":
            continue
        if int(ev.get("observed_at_ms") or 0) < cutoff:
            continue
        total += float(ev.get("estimated_net_pnl_usdc") or 0.0)
    return round(total, 6)


@dataclass(frozen=True, slots=True)
class HaltEffects:
    state: str
    entries_blocked_globally: bool
    new_markets_blocked: bool
    size_multiplier: float
    force_exit_all: bool
    reason_code: str | None


class GradedHaltStateMachine:
    """État + contrats de cooldown. Thread-safe. Ne décide que depuis le ledger."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = GREEN
        self._entered_state_ms = 0
        self._red_forced_exit_done = False

    def update(self, ledger_events: list[dict], now_ms: int, env: dict | None = None) -> str:
        """Met à jour l'état. Montée immédiate, descente seulement après cooldown."""
        loss = -realized_window_pnl_usd(ledger_events, now_ms, _f(WINDOW_ENV, env))
        amber_at, red_at = _f(AMBER_LOSS_ENV, env), _f(RED_LOSS_ENV, env)
        target = GREEN
        if loss >= red_at:
            target = RED
        elif loss >= amber_at:
            target = AMBER
        cooldown_ms = int(_f(COOLDOWN_ENV, env) * 60_000)
        with self._lock:
            order = {GREEN: 0, AMBER: 1, RED: 2}
            if order[target] > order[self._state]:
                self._state = target                    # escalade : immédiate
                self._entered_state_ms = int(now_ms)
                if target != RED:
                    self._red_forced_exit_done = False
            elif order[target] < order[self._state]:
                # désescalade : un palier à la fois, après cooldown (contrat anti yo-yo)
                if int(now_ms) - self._entered_state_ms >= cooldown_ms:
                    self._state = {RED: AMBER, AMBER: GREEN, GREEN: GREEN}[self._state]
                    self._entered_state_ms = int(now_ms)
                    if self._state != RED:
                        self._red_forced_exit_done = False
            return self._state

    def effects(self, env: dict | None = None) -> HaltEffects:
        with self._lock:
            s = self._state
            force = s == RED and not self._red_forced_exit_done
        if s == RED:
            return HaltEffects(RED, True, True, 0.0, force, REASON_RED)
        if s == AMBER:
            return HaltEffects(AMBER, False, True, _f(AMBER_SIZE_MULT_ENV, env), False, REASON_AMBER)
        return HaltEffects(GREEN, False, False, 1.0, False, None)

    def mark_forced_exit_done(self) -> None:
        with self._lock:
            self._red_forced_exit_done = True

    def state(self) -> str:
        with self._lock:
            return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = GREEN
            self._entered_state_ms = 0
            self._red_forced_exit_done = False


DEFAULT_GRADED_HALT = GradedHaltStateMachine()


def force_exit_all_positions(
    positions: dict,
    ledger_events: list[dict],
    mid_prices: dict[str, float] | None,
    *,
    now_ms: int,
    cost_bps: float = 12.0,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
) -> list[dict]:
    """Sorties forcées RED : close paper de toutes les positions au mark réel.

    Positions sans mark disponible : conservées (état honnête, on ne ferme pas
    à un prix inventé) — elles seront closes à la prochaine passe avec mark.
    """
    marks = mid_prices or {}
    closed = []
    for key in list(positions.keys()):
        pos = positions.get(key) or {}
        parts = key.split("|") if isinstance(key, str) else []
        coin = (parts[1] if len(parts) >= 3 else str(pos.get("coin") or "")).upper()
        side = (parts[2] if len(parts) >= 3 else str(pos.get("side") or "")).upper()
        wallet = parts[0] if len(parts) >= 3 else str(pos.get("wallet_address") or "")
        size = abs(float(pos.get("size") or 0.0))
        avg = float(pos.get("avg_price") or 0.0)
        mark = float(marks.get(coin) or 0.0)
        if size <= 0 or avg <= 0 or mark <= 0 or side not in {"LONG", "SHORT"}:
            continue
        gross = (mark - avg) * size if side == "LONG" else (avg - mark) * size
        cost = abs(size * mark) * cost_bps / 10_000.0
        net = gross - cost
        ledger_events.append({
            "coin": coin,
            "leader_side": side,
            "matched_position_key": f"{wallet}|{coin}|{side}",
            "strategy_mode": mode_of_position(pos),
            "paper_action_type": "CLOSE",
            "exit_method": "GRADED_HALT_RED_FORCE_EXIT",
            "reason": "GRADED_HALT_RED_FORCE_EXIT_LOCAL_REPLAY_NOT_AN_ORDER",
            "estimated_net_pnl_usdc": round(net, 6),
            "gross_pnl_usdc": round(gross, 6),
            "fee_cost_usdc": round(cost, 6),
            "average_entry_price": round(avg, 8),
            "exit_price": round(mark, 8),
            "notional_closed_usdt": round(size * mark, 6),
            "size_before": round(size, 10),
            "size_closed": round(size, 10),
            "size_after": 0.0,
            "reduce_fraction": 1.0,
            "research_only": True,
            "paper_mode": paper_mode,
            "observed_at_ms": int(now_ms),
            "status": "LOCAL_REPLAY",
        })
        positions.pop(key, None)
        closed.append({"coin": coin, "side": side, "reason": "GRADED_HALT_RED_FORCE_EXIT", "net_pnl_usdc": round(net, 6)})
    return closed


__all__ = [
    "MASTER_FLAG", "GREEN", "AMBER", "RED", "REASON_AMBER", "REASON_RED",
    "flag_on", "realized_window_pnl_usd", "HaltEffects",
    "GradedHaltStateMachine", "DEFAULT_GRADED_HALT", "force_exit_all_positions",
]
