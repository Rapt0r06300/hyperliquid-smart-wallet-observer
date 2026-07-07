"""V26 L6 — Kelly fractionné PAR LEADER (porté d'APEX PREDATOR core/kelly.py, repo 25).

Multiplicateur de taille de copie par wallet leader, calculé sur SES trades clos
(depuis le ledger — matched_position_key = ``wallet|coin|side``) :

* f* = (p·b − q) / b, fraction conservative 0.25, lookback 50 trades ;
* < 10 trades ⇒ ×1.0 (jamais de Kelly sur bruit) ;
* edge (EV) < 2 % ⇒ ×1.0 ; Kelly négatif ⇒ ×0.5 ; plafond ×2.0, plancher ×0.5.

Le book est nourri par le pipeline d'exits (closes réels du paper ledger).
Opt-in : ``HYPERSMART_V26_KELLY_LEADER=1`` (défaut OFF ⇒ multiplicateur 1.0).
Pur, paper-only : un multiplicateur de taille SIMULÉE, jamais un ordre.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

MASTER_FLAG = "HYPERSMART_V26_KELLY_LEADER"
FRACTION_ENV = "HYPERSMART_V26_KELLY_FRACTION"
LOOKBACK_ENV = "HYPERSMART_V26_KELLY_LOOKBACK"
MIN_TRADES_ENV = "HYPERSMART_V26_KELLY_MIN_TRADES"
MIN_EDGE_ENV = "HYPERSMART_V26_KELLY_MIN_EDGE"
MAX_MULT_ENV = "HYPERSMART_V26_KELLY_MAX_MULT"
MIN_MULT_ENV = "HYPERSMART_V26_KELLY_MIN_MULT"

_DEF = {
    FRACTION_ENV: 0.25, LOOKBACK_ENV: 50.0, MIN_TRADES_ENV: 10.0,
    MIN_EDGE_ENV: 0.02, MAX_MULT_ENV: 2.0, MIN_MULT_ENV: 0.5,
}


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class LeaderKellyStats:
    wallet: str
    sample_size: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    edge: float               # EV = p·avg_win − q·avg_loss
    kelly_fraction: float
    multiplier: float
    reason: str


def kelly_stats_from_returns(wallet: str, returns_pct: list[float], env: dict | None = None) -> LeaderKellyStats:
    """Stats Kelly exactes d'APEX (calculate_kelly) sur une liste de retours (pnl/size)."""
    lookback = int(_f(LOOKBACK_ENV, env))
    rs = [float(r) for r in returns_pct][-lookback:]
    n = len(rs)
    min_trades = int(_f(MIN_TRADES_ENV, env))
    if n < min_trades:
        return LeaderKellyStats(wallet, n, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "INSUFFICIENT_SAMPLE_NEUTRAL")
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    edge = win_rate * avg_win - (1 - win_rate) * avg_loss
    if avg_loss > 0:
        odds = avg_win / avg_loss
        kelly = ((win_rate * odds) - (1 - win_rate)) / odds if odds > 0 else 0.0
    else:
        kelly = 0.0
    adjusted = kelly * _f(FRACTION_ENV, env)
    # Déviation assumée vs APEX : un edge NÉGATIF prouvé (leader perdant) est RÉDUIT (x0.5),
    # pas laissé neutre — c'est tout l'intérêt du sizing par leader. 0 <= edge < min => neutre.
    if edge < 0 or (adjusted <= 0 and edge >= _f(MIN_EDGE_ENV, env)):
        mult, reason = _f(MIN_MULT_ENV, env), "KELLY_NEGATIVE_REDUCED"
    elif edge < _f(MIN_EDGE_ENV, env):
        mult, reason = 1.0, "EDGE_BELOW_MIN_NEUTRAL"
    else:
        mult, reason = min(1.0 + adjusted, _f(MAX_MULT_ENV, env)), "KELLY_APPLIED"
    return LeaderKellyStats(
        wallet, n, round(win_rate, 4), round(avg_win, 6), round(avg_loss, 6),
        round(edge, 6), round(kelly, 6), round(mult, 4), reason,
    )


class KellyLeaderBook:
    """Retours par wallet leader, nourris depuis les closes du ledger. Thread-safe."""

    def __init__(self, maxlen_per_wallet: int = 100) -> None:
        self._lock = threading.Lock()
        self._maxlen = int(maxlen_per_wallet)
        self._returns: dict[str, list[float]] = {}

    def record_close(self, wallet: str, net_pnl_usd: float, notional_usd: float) -> None:
        key = (wallet or "").strip().lower()
        if not key or notional_usd <= 0:
            return
        r = float(net_pnl_usd) / float(notional_usd)
        with self._lock:
            lst = self._returns.setdefault(key, [])
            lst.append(r)
            if len(lst) > self._maxlen:
                del lst[: len(lst) - self._maxlen]

    def update_from_ledger_events(self, events: list[dict]) -> int:
        """Ingère les closes du ledger (wallet extrait de matched_position_key)."""
        n = 0
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            if str(ev.get("paper_action_type") or "").upper() != "CLOSE":
                continue
            key = str(ev.get("matched_position_key") or "")
            wallet = key.split("|")[0] if "|" in key else ""
            notional = float(ev.get("notional_closed_usdt") or 0.0)
            if wallet and notional > 0:
                self.record_close(wallet, float(ev.get("estimated_net_pnl_usdc") or 0.0), notional)
                n += 1
        return n

    def stats(self, wallet: str, env: dict | None = None) -> LeaderKellyStats:
        key = (wallet or "").strip().lower()
        with self._lock:
            rs = list(self._returns.get(key, ()))
        return kelly_stats_from_returns(key, rs, env)

    def multiplier(self, wallet: str, env: dict | None = None) -> float:
        """×1.0 si flag OFF ou wallet inconnu (jamais de malus sur l'inconnu)."""
        if not flag_on(env) or not (wallet or "").strip():
            return 1.0
        return self.stats(wallet, env).multiplier

    def clear(self) -> None:
        with self._lock:
            self._returns.clear()


DEFAULT_KELLY_LEADER_BOOK = KellyLeaderBook()

__all__ = [
    "MASTER_FLAG", "flag_on", "LeaderKellyStats", "kelly_stats_from_returns",
    "KellyLeaderBook", "DEFAULT_KELLY_LEADER_BOOK",
]
