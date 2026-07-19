"""V26 — Hub des vetos d'entrée (L1 + L4 + L5 + L7 + L8) + enregistreur replay (L9).

Chaque veto est OPT-IN par son propre flag env (tous OFF par défaut ⇒ zéro changement),
en intersection stricte : ne peut qu'AJOUTER des refus, jamais créer un trade.
Inconnu (None / historique vide / marché non noté) ne bloque JAMAIS (état honnête).

* L1 ``HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE`` : funding sain (spike z-score 2σ,
  warmup) + edge stable (tendance décroissante) — repo 32 gajesh2007/funding-arb-bot.
* L4 ``HYPERSMART_V26_GRADED_HALT`` : états AMBER/RED du halt gradué (passivbot HSL).
* L5 ``HYPERSMART_V26_PROTECTIONS`` : StoplossGuard / LowProfitMarket / WindowedDrawdown
  (freqtrade plugins/protections), nourris par les closes réels du ledger.
* L7 ``HYPERSMART_V26_TIER_COST_BUDGET`` : coûts > budget du tier leader (repo 17).
* L8 ``HYPERSMART_V26_MARKET_QUALITY`` : marché hors univers top-K forager (passivbot).
* L9 ``HYPERSMART_V26_RECORD_CANDIDATES`` : journalise chaque candidat évalué (JSONL,
  runtime/replay/) pour le harnais A/B — observation pure, ne décide rien.

Paper-only : un veto est un NO_TRADE simulé, jamais un ordre. Seule exception réseau :
démarrage paresseux OPT-IN des pollers publics (funding / carnet), lecture seule.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from hl_observer.funding.spike_detector import detect_funding_spike
from hl_observer.ops.echec_silencieux import noter as _noter_echec

MASTER_FLAG = "HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE"
FUNDING_SUBFLAG = "HYPERSMART_V26_FUNDING_VETO"
TREND_SUBFLAG = "HYPERSMART_V26_EDGE_TREND_VETO"
RECORD_FLAG = "HYPERSMART_V26_RECORD_CANDIDATES"
RECORD_PATH_ENV = "HYPERSMART_V26_RECORD_PATH"

REASON_FUNDING_SPIKE = "FUNDING_SPIKE"
REASON_FUNDING_WARMUP = "FUNDING_HISTORY_WARMUP"
REASON_EDGE_TREND_DOWN = "EDGE_TRENDING_DOWN"

DEFAULT_SIGMA = 2.0
DEFAULT_MIN_FUNDING_SAMPLES = 6
DEFAULT_TREND_LOOKBACK = 6
DEFAULT_TREND_THRESHOLD_BPS = 2.0


def _flag(name: str, default: bool, env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    raw = str(e.get(name, "1" if default else "0")).strip().lower()
    return raw in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Tendance d'edge (repo 32 : getEdgeTrend — moitiés comparées, seuil bps)
# ---------------------------------------------------------------------------

class EdgeTrendRecorder:
    """Historique borné des edges nets observés par clé ``COIN|SIDE``. Thread-safe."""

    def __init__(self, maxlen: int = 24) -> None:
        self._lock = threading.Lock()
        self._maxlen = int(maxlen)
        self._series: dict[str, deque[tuple[float, float]]] = {}

    @staticmethod
    def key(coin: str, side: str) -> str:
        return f"{(coin or '').strip().upper()}|{(side or '').strip().upper()}"

    def record(self, coin: str, side: str, edge_bps: float, ts: float | None = None) -> None:
        if not (coin or "").strip():
            return
        try:
            v = float(edge_bps)
        except (TypeError, ValueError):
            return
        if math.isnan(v) or math.isinf(v):
            return
        k = self.key(coin, side)
        t = float(ts) if ts is not None else time.time()
        with self._lock:
            dq = self._series.get(k)
            if dq is None:
                dq = deque(maxlen=self._maxlen)
                self._series[k] = dq
            dq.append((t, v))

    def trend(
        self,
        coin: str,
        side: str,
        *,
        lookback: int = DEFAULT_TREND_LOOKBACK,
        threshold_bps: float = DEFAULT_TREND_THRESHOLD_BPS,
    ) -> str | None:
        """``increasing`` | ``stable`` | ``decreasing`` | None (pas assez d'échantillons)."""
        k = self.key(coin, side)
        with self._lock:
            dq = self._series.get(k)
            values = [v for (_, v) in dq] if dq else []
        if len(values) < int(lookback):
            return None
        recent = values[-int(lookback):]
        half = len(recent) // 2
        first, second = recent[:half], recent[half:]
        if not first or not second:
            return None
        diff = (sum(second) / len(second)) - (sum(first) / len(first))
        if diff > float(threshold_bps):
            return "increasing"
        if diff < -float(threshold_bps):
            return "decreasing"
        return "stable"

    def coins(self) -> list[str]:
        """Coins récemment observés (pour les pollers publics opt-in)."""
        with self._lock:
            return sorted({k.split("|")[0] for k in self._series if k.split("|")[0]})

    def clear(self) -> None:
        with self._lock:
            self._series.clear()


DEFAULT_EDGE_TREND_RECORDER = EdgeTrendRecorder()


def record_edge_observation(coin: str, side: str, edge_bps: float, *, recorder: EdgeTrendRecorder | None = None) -> None:
    (recorder or DEFAULT_EDGE_TREND_RECORDER).record(coin, side, edge_bps)


def edge_trend(coin: str, side: str, *, recorder: EdgeTrendRecorder | None = None) -> str | None:
    return (recorder or DEFAULT_EDGE_TREND_RECORDER).trend(coin, side)


# ---------------------------------------------------------------------------
# Sanité funding (repo 32 : hasEnoughHistory + isSpike, z-score vs fenêtre 24 h)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FundingSanity:
    ok: bool | None          # None = inconnu (ne bloque jamais)
    code: str | None         # FUNDING_SPIKE | FUNDING_HISTORY_WARMUP | None
    z_score: float | None


def funding_sanity(
    rates: list[float] | None,
    *,
    sigma: float = DEFAULT_SIGMA,
    min_samples: int = DEFAULT_MIN_FUNDING_SAMPLES,
) -> FundingSanity:
    if not rates:
        return FundingSanity(None, None, None)  # aucun flux → inconnu, jamais bloquant
    if len(rates) < int(min_samples):
        return FundingSanity(False, REASON_FUNDING_WARMUP, None)  # flux jeune → prudence (deny)
    d = detect_funding_spike(list(rates), sigma=float(sigma))
    if d.spike:
        return FundingSanity(False, REASON_FUNDING_SPIKE, d.z_score)
    return FundingSanity(True, None, d.z_score)


# ---------------------------------------------------------------------------
# Enregistreur de candidats (L9) — observation pure pour le harnais A/B replay
# ---------------------------------------------------------------------------

_record_lock = threading.Lock()


def _record_candidate(snapshot: dict, env: dict | None) -> None:
    if not _flag(RECORD_FLAG, False, env):
        return
    try:
        e = env if env is not None else os.environ
        base = str(e.get(RECORD_PATH_ENV, "") or "runtime/replay")
        row = {"recorded_at": time.time(), **snapshot}
        # ANTI-BLOAT: append CAPÉ (le run 48h a crashé sur du stockage non borné).
        from hl_observer.runtime.replay_recorder import (
            CANDIDATES_MAX_BYTES, CANDIDATES_MAX_LINES, append_replay_lines)
        with _record_lock:
            append_replay_lines(base, "candidates.jsonl", [row],
                                max_bytes=CANDIDATES_MAX_BYTES, max_lines=CANDIDATES_MAX_LINES)
    except Exception:
        _noter_echec("hl_observer/signals/v26_entry_vetos.py:184")


# ---------------------------------------------------------------------------
# Hook scorer (appelé par copying.realtime_magic_score — intersection stricte)
# ---------------------------------------------------------------------------

def apply_v26_entry_vetos(
    *,
    coin: str,
    side: str,
    edge_remaining_bps: float | None,
    funding_rates: list[float] | None = None,
    env: dict | None = None,
    recorder: EdgeTrendRecorder | None = None,
    sigma: float = DEFAULT_SIGMA,
    min_funding_samples: int = DEFAULT_MIN_FUNDING_SAMPLES,
    trend_lookback: int = DEFAULT_TREND_LOOKBACK,
    trend_threshold_bps: float = DEFAULT_TREND_THRESHOLD_BPS,
    leader_score: float | None = None,
    copy_degradation_bps: float | None = None,
    liquidity_score: float | None = None,
    now_ms: int | None = None,
    candidate_snapshot: dict | None = None,
) -> list[str]:
    """Retourne la liste (éventuellement vide) des raisons de refus V26.

    Tous les vetos sont opt-in par flags séparés ; sans flag, seule l'observation
    (historique d'edge, note de qualité marché, enregistrement replay) a lieu.
    Ne lève jamais : le scorer enveloppe déjà d'un try/except.
    """
    rec = recorder or DEFAULT_EDGE_TREND_RECORDER
    coin_known = bool((coin or "").strip())
    reasons: list[str] = []
    t_ms = int(now_ms) if now_ms else int(time.time() * 1000)

    # 0) Observations (toujours, jamais bloquantes en soi)
    if coin_known and edge_remaining_bps is not None:
        rec.record(coin, side, edge_remaining_bps)
    if coin_known:
        try:  # note de qualité marché (L8) — sur données réellement disponibles
            from hl_observer.paper_trading.vol_adjusted_barriers import DEFAULT_MID_VOL_ESTIMATOR
            from hl_observer.signals.market_quality_score import DEFAULT_MARKET_QUALITY_BOOK

            rng = DEFAULT_MID_VOL_ESTIMATOR.range_bps(coin, window_s=900.0, min_obs=5)
            DEFAULT_MARKET_QUALITY_BOOK.observe(
                coin, range_bps=rng, liquidity_score=liquidity_score, env=env
            )
        except Exception:
            _noter_echec("hl_observer/signals/v26_entry_vetos.py:233")
    if candidate_snapshot:
        _record_candidate(candidate_snapshot, env)

    # L4 — halt gradué (global, ne dépend pas du coin)
    try:
        from hl_observer.risk.graded_halt import DEFAULT_GRADED_HALT
        from hl_observer.risk.graded_halt import flag_on as halt_flag_on

        if halt_flag_on(env):
            fx = DEFAULT_GRADED_HALT.effects(env)
            if fx.entries_blocked_globally and fx.reason_code:
                reasons.append(fx.reason_code)
            elif fx.new_markets_blocked and fx.reason_code and coin_known:
                # AMBER : bloque seulement les entrées (pattern « moins de risque »)
                reasons.append(fx.reason_code)
    except Exception:
        _noter_echec("hl_observer/signals/v26_entry_vetos.py:250")

    # L5 — protections fenêtrées (ledger)
    if coin_known:
        try:
            from hl_observer.risk.protections_v26 import DEFAULT_PROTECTIONS_BOOK
            from hl_observer.risk.protections_v26 import flag_on as prot_flag_on

            if prot_flag_on(env):
                v = DEFAULT_PROTECTIONS_BOOK.entry_verdict(coin, t_ms, env)
                if v.blocked and v.reason:
                    reasons.append(v.reason)
        except Exception:
            _noter_echec("hl_observer/signals/v26_entry_vetos.py:263")

    # L8 — univers top-K forager
    if coin_known:
        try:
            from hl_observer.signals.market_quality_score import (
                DEFAULT_MARKET_QUALITY_BOOK,
                REASON_MQ,
            )
            from hl_observer.signals.market_quality_score import flag_on as mq_flag_on

            if mq_flag_on(env) and DEFAULT_MARKET_QUALITY_BOOK.allowed(coin, env) is False:
                reasons.append(REASON_MQ)
        except Exception:
            _noter_echec("hl_observer/signals/v26_entry_vetos.py:277")

    # L7 — budget de coûts par tier de leader
    try:
        from hl_observer.edge.tier_cost_budget import cost_budget_veto
        from hl_observer.edge.tier_cost_budget import flag_on as tier_flag_on

        if tier_flag_on(env):
            code = cost_budget_veto(
                leader_score=leader_score, copy_degradation_bps=copy_degradation_bps, env=env
            )
            if code:
                reasons.append(code)
    except Exception:
        _noter_echec("hl_observer/signals/v26_entry_vetos.py:291")

    # L1 — vetos funding sain + edge stable (flag maître historique)
    if _flag(MASTER_FLAG, False, env) and coin_known:
        try:
            from hl_observer.funding.funding_poller import ensure_started as _poller_start

            _poller_start(env)
        except Exception:
            _noter_echec("hl_observer/signals/v26_entry_vetos.py:300")
        try:
            from hl_observer.collection.l2_snapshot_cache import ensure_started as _book_start

            _book_start(env)
        except Exception:
            _noter_echec("hl_observer/signals/v26_entry_vetos.py:306")
        if _flag(TREND_SUBFLAG, True, env):
            t = rec.trend(coin, side, lookback=trend_lookback, threshold_bps=trend_threshold_bps)
            if t == "decreasing":
                reasons.append(REASON_EDGE_TREND_DOWN)
        if _flag(FUNDING_SUBFLAG, True, env):
            rates = funding_rates
            if rates is None:
                try:
                    from hl_observer.funding.funding_runtime_cache import recent_rates

                    rates = recent_rates(coin)
                except Exception:
                    rates = None
            fs = funding_sanity(rates, sigma=sigma, min_samples=min_funding_samples)
            if fs.ok is False and fs.code:
                reasons.append(fs.code)

    return reasons


__all__ = [
    "MASTER_FLAG",
    "FUNDING_SUBFLAG",
    "TREND_SUBFLAG",
    "RECORD_FLAG",
    "REASON_FUNDING_SPIKE",
    "REASON_FUNDING_WARMUP",
    "REASON_EDGE_TREND_DOWN",
    "EdgeTrendRecorder",
    "DEFAULT_EDGE_TREND_RECORDER",
    "record_edge_observation",
    "edge_trend",
    "FundingSanity",
    "funding_sanity",
    "apply_v26_entry_vetos",
]
# LOGS-MAX/replay: enregistrement candidats capé via runtime.replay_recorder (anti-bloat).
