"""V26 L5 — Protections fenêtrées (portées de freqtrade plugins/protections).

Trois règles, alimentées UNIQUEMENT par les événements de close du ledger (vérité unique) :

* ``StoplossGuard``  : ≥ N sorties STOP_LOSS dans la fenêtre ⇒ halt (global ou par marché).
* ``LowProfitMarket``: profit cumulé d'un marché < seuil sur ≥ N trades ⇒ blacklist du marché.
* ``WindowedMaxDrawdown`` : PnL réalisé cumulé de la fenêtre < -seuil ⇒ pause globale.

Pattern RiskRule composable (repo 38 chainstacklabs) : chaque règle = un check pur.
Le ``ProtectionsBook`` module-level est nourri par le pipeline d'exits (données réelles
du ledger) et lu par le veto d'entrée. Vide = état honnête (rien ne bloque).
Opt-in : ``HYPERSMART_V26_PROTECTIONS=1`` (défaut OFF). Paper-only, jamais un ordre.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

MASTER_FLAG = "HYPERSMART_V26_PROTECTIONS"

# StoplossGuard (défauts freqtrade adaptés copie : 4 stops / 60 min -> halt 60 min)
SG_N_ENV = "HYPERSMART_V26_SG_TRADE_LIMIT"
SG_WINDOW_ENV = "HYPERSMART_V26_SG_WINDOW_MIN"
SG_HALT_ENV = "HYPERSMART_V26_SG_HALT_MIN"
SG_PER_MARKET_ENV = "HYPERSMART_V26_SG_PER_MARKET"   # 1 = halt par marché, 0 = global
# LowProfitMarket (2 trades mini, profit < 0 sur 240 min -> blacklist 120 min)
LP_N_ENV = "HYPERSMART_V26_LP_TRADE_LIMIT"
LP_WINDOW_ENV = "HYPERSMART_V26_LP_WINDOW_MIN"
LP_MIN_PROFIT_ENV = "HYPERSMART_V26_LP_MIN_PROFIT_USD"
LP_BLOCK_ENV = "HYPERSMART_V26_LP_BLOCK_MIN"
# WindowedMaxDrawdown (perte fenêtre 120 min > seuil USD -> pause 60 min)
DD_WINDOW_ENV = "HYPERSMART_V26_DD_WINDOW_MIN"
DD_MAX_LOSS_ENV = "HYPERSMART_V26_DD_MAX_LOSS_USD"
DD_HALT_ENV = "HYPERSMART_V26_DD_HALT_MIN"

_DEF = {
    SG_N_ENV: 4.0, SG_WINDOW_ENV: 60.0, SG_HALT_ENV: 60.0, SG_PER_MARKET_ENV: 1.0,
    LP_N_ENV: 2.0, LP_WINDOW_ENV: 240.0, LP_MIN_PROFIT_ENV: 0.0, LP_BLOCK_ENV: 120.0,
    DD_WINDOW_ENV: 120.0, DD_MAX_LOSS_ENV: 15.0, DD_HALT_ENV: 60.0,
}

REASON_SG = "STOPLOSS_GUARD_ACTIVE"
REASON_LP = "MARKET_LOW_PROFIT_BLOCKED"
REASON_DD = "WINDOWED_DRAWDOWN_HALT"


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
class CloseRecord:
    """Trace minimale d'un close paper (issue du ledger, jamais fabriquée)."""

    coin: str
    closed_at_ms: int
    net_pnl_usd: float
    was_stop_loss: bool


@dataclass(frozen=True, slots=True)
class ProtectionVerdict:
    blocked: bool
    reason: str | None      # code taxonomie
    detail: str = ""


def close_record_from_ledger_event(event: dict) -> CloseRecord | None:
    """Extrait un CloseRecord d'un événement ledger de close. None si pas un close."""
    try:
        if str(event.get("paper_action_type") or "").upper() != "CLOSE":
            return None
        coin = str(event.get("coin") or "").upper()
        if not coin:
            return None
        exit_method = str(event.get("exit_method") or "").upper()
        return CloseRecord(
            coin=coin,
            closed_at_ms=int(event.get("observed_at_ms") or 0),
            net_pnl_usd=float(event.get("estimated_net_pnl_usdc") or 0.0),
            was_stop_loss="STOP_LOSS" in exit_method,
        )
    except (TypeError, ValueError):
        return None


class ProtectionsBook:
    """État des protections, nourri par les closes réels. Thread-safe, borné."""

    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._maxlen = int(maxlen)
        self._closes: list[CloseRecord] = []

    def record_close(self, rec: CloseRecord) -> None:
        with self._lock:
            self._closes.append(rec)
            if len(self._closes) > self._maxlen:
                self._closes = self._closes[-self._maxlen:]

    def update_from_ledger_events(self, events: list[dict]) -> int:
        n = 0
        for ev in events or []:
            rec = close_record_from_ledger_event(ev if isinstance(ev, dict) else {})
            if rec is not None:
                self.record_close(rec)
                n += 1
        return n

    def _window(self, now_ms: int, window_min: float, coin: str | None = None) -> list[CloseRecord]:
        cutoff = int(now_ms) - int(window_min * 60_000)
        with self._lock:
            return [
                c for c in self._closes
                if c.closed_at_ms >= cutoff and (coin is None or c.coin == coin)
            ]

    # ── Règles (une règle = un check, pattern repo 38) ──────────────────────

    def stoploss_guard(self, coin: str, now_ms: int, env: dict | None = None) -> ProtectionVerdict:
        per_market = _f(SG_PER_MARKET_ENV, env) >= 1.0
        scope = coin if per_market else None
        stops = [c for c in self._window(now_ms, _f(SG_WINDOW_ENV, env), scope) if c.was_stop_loss]
        limit = int(_f(SG_N_ENV, env))
        if limit > 0 and len(stops) >= limit:
            last = max(c.closed_at_ms for c in stops)
            until = last + int(_f(SG_HALT_ENV, env) * 60_000)
            if now_ms < until:
                return ProtectionVerdict(True, REASON_SG, f"{len(stops)} stops/{scope or 'GLOBAL'}")
        return ProtectionVerdict(False, None)

    def low_profit_market(self, coin: str, now_ms: int, env: dict | None = None) -> ProtectionVerdict:
        closes = self._window(now_ms, _f(LP_WINDOW_ENV, env), coin)
        if len(closes) >= int(_f(LP_N_ENV, env)):
            profit = sum(c.net_pnl_usd for c in closes)
            if profit < _f(LP_MIN_PROFIT_ENV, env):
                last = max(c.closed_at_ms for c in closes)
                until = last + int(_f(LP_BLOCK_ENV, env) * 60_000)
                if now_ms < until:
                    return ProtectionVerdict(True, REASON_LP, f"{coin} pnl={profit:.2f}$")
        return ProtectionVerdict(False, None)

    def windowed_drawdown(self, now_ms: int, env: dict | None = None) -> ProtectionVerdict:
        closes = self._window(now_ms, _f(DD_WINDOW_ENV, env))
        loss = sum(c.net_pnl_usd for c in closes)
        max_loss = _f(DD_MAX_LOSS_ENV, env)
        if closes and loss <= -abs(max_loss):
            last = max(c.closed_at_ms for c in closes)
            until = last + int(_f(DD_HALT_ENV, env) * 60_000)
            if now_ms < until:
                return ProtectionVerdict(True, REASON_DD, f"loss={loss:.2f}$")
        return ProtectionVerdict(False, None)

    def entry_verdict(self, coin: str, now_ms: int, env: dict | None = None) -> ProtectionVerdict:
        """Composition fail-fast : DD global → stoploss guard → low-profit marché."""
        for v in (
            self.windowed_drawdown(now_ms, env),
            self.stoploss_guard(coin, now_ms, env),
            self.low_profit_market(coin, now_ms, env),
        ):
            if v.blocked:
                return v
        return ProtectionVerdict(False, None)

    def status(self) -> dict:
        with self._lock:
            n = len(self._closes)
            stops = sum(1 for c in self._closes if c.was_stop_loss)
        return {"closes_tracked": n, "stops_tracked": stops, "read_only": True}

    def clear(self) -> None:
        with self._lock:
            self._closes.clear()


DEFAULT_PROTECTIONS_BOOK = ProtectionsBook()

__all__ = [
    "MASTER_FLAG", "REASON_SG", "REASON_LP", "REASON_DD",
    "CloseRecord", "ProtectionVerdict", "close_record_from_ledger_event",
    "ProtectionsBook", "DEFAULT_PROTECTIONS_BOOK", "flag_on",
]
