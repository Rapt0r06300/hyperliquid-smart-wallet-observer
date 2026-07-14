"""V26 L2 — Barrières SL/TP/trailing ajustées à la volatilité (hummingbot TripleBarrier).

Porte le comportement de ``TripleBarrierConfig.new_instance_with_adjusted_volatility``
(hummingbot strategy_v2) sur le runtime d'exits paper existant (`sltp_runtime`) :
toutes les barrières (SL, TP, trailing, activation) sont multipliées par un facteur
de régime de volatilité PAR COIN, borné, avec un PLANCHER de stop (un SL plus serré
que le bruit = stop-out garanti — cause racine historique du WR 12,5 %).

Le facteur de vol vient d'un estimateur honnête sur les marks réels déjà observés
(range glissant en bps sur une fenêtre). Pas assez d'observations → facteur 1.0
(neutre, jamais inventé).

Opt-in : ``HYPERSMART_V26_VOL_BARRIERS=1`` (défaut OFF ⇒ passthrough strictement
identique à ``apply_sltp_exits``). Paper-only : une sortie est un close simulé,
jamais un ordre.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import replace

from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits

MASTER_FLAG = "HYPERSMART_V26_VOL_BARRIERS"
REF_RANGE_ENV = "HYPERSMART_V26_VOL_REF_RANGE_BPS"      # range "normal" de référence
WINDOW_ENV = "HYPERSMART_V26_VOL_WINDOW_S"
FACTOR_MIN_ENV = "HYPERSMART_V26_VOL_FACTOR_MIN"
FACTOR_MAX_ENV = "HYPERSMART_V26_VOL_FACTOR_MAX"
SL_FLOOR_ENV = "HYPERSMART_V26_SL_FLOOR_BPS"
TP_FLOOR_ENV = "HYPERSMART_V26_TP_FLOOR_BPS"
MIN_OBS_ENV = "HYPERSMART_V26_VOL_MIN_OBS"

_DEFAULTS = {
    REF_RANGE_ENV: 40.0,   # 40 bps de range sur la fenêtre = régime "normal" (facteur 1.0)
    WINDOW_ENV: 900.0,     # 15 min
    FACTOR_MIN_ENV: 0.5,
    FACTOR_MAX_ENV: 2.5,
    SL_FLOOR_ENV: 12.0,    # jamais de SL sous 12 bps (bruit)
    # PLANCHER DE TP (autopsie PnL 2026-07-11) — LA REGLE QUI MANQUAIT.
    # Le facteur de volatilite median mesure valait 0.71, et descendait jusqu'a 0.5. Un TP de base
    # de 40 bps tombait donc a 20 bps... pour 13 bps de frais aller-retour. Il ne restait que
    # 7 bps de gain reel, pendant que le SL, lui, s'elargissait a 90 bps. Ratio net : 1 pour 6.65
    # -> il fallait 87 % de winrate pour seulement rentrer dans ses frais. La perte etait CERTAINE,
    # quel que soit le signal. Un TP ne doit JAMAIS etre rabote sous ce plancher.
    TP_FLOOR_ENV: 45.0,
    MIN_OBS_ENV: 5.0,
}


def _fenv(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEFAULTS[name]) or _DEFAULTS[name])
    except (TypeError, ValueError):
        return float(_DEFAULTS[name])


def _flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


class MidVolEstimator:
    """Range glissant (bps) par coin, à partir des marks réels observés. Thread-safe."""

    def __init__(self, maxlen: int = 720) -> None:
        self._lock = threading.Lock()
        self._maxlen = int(maxlen)
        self._series: dict[str, deque[tuple[float, float]]] = {}

    def record(self, coin: str, mid: float, ts: float | None = None) -> None:
        key = (coin or "").strip().upper()
        try:
            m = float(mid)
        except (TypeError, ValueError):
            return
        if not key or m <= 0 or m != m or m == float("inf"):
            return
        t = float(ts) if ts is not None else time.time()
        with self._lock:
            dq = self._series.get(key)
            if dq is None:
                dq = deque(maxlen=self._maxlen)
                self._series[key] = dq
            dq.append((t, m))

    def range_bps(self, coin: str, *, window_s: float, min_obs: int, now: float | None = None) -> float | None:
        key = (coin or "").strip().upper()
        cutoff = (float(now) if now is not None else time.time()) - float(window_s)
        with self._lock:
            dq = self._series.get(key)
            pts = [m for (t, m) in dq if t >= cutoff] if dq else []
        if len(pts) < int(min_obs):
            return None  # pas assez d'observations réelles -> inconnu (jamais inventé)
        lo, hi, last = min(pts), max(pts), pts[-1]
        if last <= 0:
            return None
        return (hi - lo) / last * 10_000.0

    def clear(self) -> None:
        with self._lock:
            self._series.clear()


DEFAULT_MID_VOL_ESTIMATOR = MidVolEstimator()


def vol_factor_for_coin(
    coin: str,
    *,
    estimator: MidVolEstimator | None = None,
    env: dict | None = None,
    now: float | None = None,
) -> float:
    """Facteur de régime borné. 1.0 si historique insuffisant (neutre, honnête)."""
    est = estimator or DEFAULT_MID_VOL_ESTIMATOR
    rng = est.range_bps(
        coin,
        window_s=_fenv(WINDOW_ENV, env),
        min_obs=int(_fenv(MIN_OBS_ENV, env)),
        now=now,
    )
    if rng is None:
        return 1.0
    ref = max(1e-9, _fenv(REF_RANGE_ENV, env))
    lo, hi = _fenv(FACTOR_MIN_ENV, env), _fenv(FACTOR_MAX_ENV, env)
    return max(lo, min(hi, rng / ref))


def adjust_config(
    base: SLTPConfig, factor: float, *, sl_floor_bps: float, tp_floor_bps: float = 0.0
) -> SLTPConfig:
    """Barrières × facteur (hummingbot), avec DEUX planchers. Pure.

    ``sl_floor_bps`` : un SL trop serré se fait toucher par le bruit.
    ``tp_floor_bps`` : un TP trop serré se fait manger par les FRAIS -- c'est la cause mesuree
    du PnL negatif du run du 09-10 juillet (TP rabote a 20 bps pour 13 bps de frais).
    """
    f = float(factor)
    scaled_sl = max(float(base.stop_loss_bps) * f, float(sl_floor_bps))
    scaled_tp = max(float(base.take_profit_bps) * f, float(tp_floor_bps))
    return replace(
        base,
        stop_loss_bps=round(scaled_sl, 6),
        take_profit_bps=round(scaled_tp, 6),
        trailing_stop_bps=(
            round(float(base.trailing_stop_bps) * f, 6) if base.trailing_stop_bps is not None else None
        ),
        trailing_activation_bps=(
            round(float(base.trailing_activation_bps) * f, 6)
            if base.trailing_activation_bps is not None
            else None
        ),
    )


def _apply_sltp_exits_vol_adjusted_impl(
    positions,
    ledger_events,
    mid_prices,
    *,
    cost_bps: float = 12.0,
    now_ms: int = 0,
    config: SLTPConfig | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
    env: dict | None = None,
    estimator: MidVolEstimator | None = None,
):
    """Wrapper drop-in de ``apply_sltp_exits``.

    Flag OFF (défaut) : passthrough strictement identique (comportement V25).
    Flag ON : enregistre les marks réels, puis applique les exits PAR COIN avec un
    config dont les barrières sont ajustées au régime de volatilité du coin.
    """
    # ==============================================================================================
    # 🔴 #591 — LE GARDE-FOU AFFAME (trouve le 2026-07-13).
    # ==============================================================================================
    # Ces trois lignes etaient SOUS le `return` anticipe ci-dessous. Consequence : l'estimateur de
    # volatilite n'etait nourri **QUE lorsqu'une position etait deja ouverte**.
    #
    # Or son consommateur est `signals/v26_entry_vetos.py:228`, qui demande
    # `range_bps(window_s=900, min_obs=5)` **au moment de decider une ENTREE** -- c'est-a-dire,
    # justement, quand il n'y a le plus souvent AUCUNE position. Il recevait donc `None`.
    #
    # Et `None` ne fait pas d'erreur : `quality_score()` se contente de **sauter** le terme de
    # volatilite (+-30/35/+15 points -- le plus lourd des trois). Le veto `REASON_MQ`
    # (`MarketQualityBook.allowed()`) continuait de classer l'univers top-K... sur la liquidite
    # SEULE. Un veto qui tranche sur un score ampute, sans jamais le dire.
    #
    # C'est la maladie du projet sous un 11e deguisement : *la capacite est la, le fil est coupe,
    # personne ne rale.* Et c'est la meme lecon que le carnet L2 (#330) :
    # **le deny-by-default protege les ORDRES, pas les OCTETS.** Enregistrer un mark n'est pas
    # passer un ordre. On observe TOUJOURS ; on decide ensuite.
    # ==============================================================================================
    est = estimator or DEFAULT_MID_VOL_ESTIMATOR
    marks = mid_prices or {}
    now_s = (float(now_ms) / 1000.0) if now_ms else None
    for coin, mid in marks.items():
        est.record(str(coin), mid, ts=now_s)

    if config is None or not positions:
        return apply_sltp_exits(
            positions, ledger_events, mid_prices, cost_bps=cost_bps, now_ms=now_ms,
            config=config, paper_mode=paper_mode,
        )

    if not _flag_on(env):
        return apply_sltp_exits(
            positions, ledger_events, mid_prices, cost_bps=cost_bps, now_ms=now_ms,
            config=config, paper_mode=paper_mode,
        )

    sl_floor = _fenv(SL_FLOOR_ENV, env)
    tp_floor = _fenv(TP_FLOOR_ENV, env)
    closed_all = []
    # Grouper les positions par coin pour appliquer le config ajusté du coin.
    by_coin: dict[str, dict] = {}
    for key, pos in list(positions.items()):
        coin = str((pos or {}).get("coin") or "").upper()
        if not coin and isinstance(key, str) and "|" in key:
            coin = key.split("|")[1].upper() if len(key.split("|")) > 1 else ""
        by_coin.setdefault(coin or "?", {})[key] = pos

    for coin, group in by_coin.items():
        original_keys = set(group.keys())
        factor = vol_factor_for_coin(coin, estimator=est, env=env, now=now_s)
        cfg = adjust_config(config, factor, sl_floor_bps=sl_floor, tp_floor_bps=tp_floor)
        closed = apply_sltp_exits(
            group, ledger_events, marks, cost_bps=cost_bps, now_ms=now_ms,
            config=cfg, paper_mode=paper_mode,
        )
        for row in closed:
            row["vol_factor"] = round(factor, 6)
            row["vol_adjusted"] = True
        closed_all.extend(closed)
        # Répercuter les mutations du groupe (keys fermées) sur le dict source — drop-in fidèle.
        for key in original_keys - set(group.keys()):
            positions.pop(key, None)

    return closed_all




def apply_sltp_exits_vol_adjusted(
    positions,
    ledger_events,
    mid_prices,
    *,
    cost_bps: float = 12.0,
    now_ms: int = 0,
    config: SLTPConfig | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
    env: dict | None = None,
    estimator: MidVolEstimator | None = None,
):
    """Façade : exits (vol-ajustés ou passthrough) puis pipeline V26 (L3/L4/L5/L6/L8).

    Le pipeline est fail-safe et n'agit que via ses propres flags ; l'ingestion des
    closes dans les books (observation) est toujours active. Paper-only.
    """
    ledger_len_before = len(ledger_events) if isinstance(ledger_events, list) else 0
    closed = _apply_sltp_exits_vol_adjusted_impl(
        positions, ledger_events, mid_prices, cost_bps=cost_bps, now_ms=now_ms,
        config=config, paper_mode=paper_mode, env=env, estimator=estimator,
    )
    try:
        from hl_observer.paper_trading.v26_exit_pipeline import run_v26_exit_pipeline

        run_v26_exit_pipeline(
            positions, ledger_events, mid_prices,
            now_ms=int(now_ms or 0), cost_bps=cost_bps,
            ledger_len_before=ledger_len_before, env=env, paper_mode=paper_mode,
        )
    except Exception:  # le pipeline ne casse jamais les exits
        pass
    return closed


__all__ = [
    "MASTER_FLAG",
    "MidVolEstimator",
    "DEFAULT_MID_VOL_ESTIMATOR",
    "vol_factor_for_coin",
    "adjust_config",
    "apply_sltp_exits_vol_adjusted",
]
