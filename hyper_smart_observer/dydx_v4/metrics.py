"""
Métriques anti-illusion — mesurer honnêtement, ne jamais maquiller.

1. Copy capture ratio: notre PnL paper vs le PnL du leader sur les trades
   copiés. La littérature copy-trading: la copie naïve capture seulement
   20-40% du PnL source. Si notre ratio est bas → travailler les exits,
   pas ajouter des trades.
2. Walk-forward: PnL par fenêtres temporelles successives hors-échantillon.
   Un PnL positif sur UNE fenêtre ne prouve rien; la stabilité inter-fenêtres si.
3. Résumé NO_TRADE hebdomadaire: les refus sont une feature, pas un bug.

PAPER-ONLY. Ces métriques ne déclenchent jamais d'ordre.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


# ---------------------------------------------------------------------------
# 1. Copy capture ratio
# ---------------------------------------------------------------------------
@dataclass
class CopyCaptureReport:
    matched_trades: int
    our_pnl: float
    leader_pnl: float
    capture_ratio: float | None  # None si leader_pnl <= 0 (non interprétable)
    per_market: dict[str, tuple[float, float]] = field(default_factory=dict)

    def summary_text(self) -> str:
        ratio = f"{self.capture_ratio:.0%}" if self.capture_ratio is not None else "N/A"
        return (
            f"CopyCapture: {self.matched_trades} trades appariés | "
            f"nous={self.our_pnl:+.2f} leader={self.leader_pnl:+.2f} | capture={ratio}"
        )


def copy_capture_ratio(
    our_trades: list[dict],
    leader_trades: list[dict],
    match_window_ms: int = 30 * 60 * 1000,
) -> CopyCaptureReport:
    """
    Apparier nos trades paper aux trades du leader (même market+side,
    ouverture dans ±match_window_ms) et comparer les PnL net.

    Format attendu (dict): market, side, opened_at_ms, pnl_net.
    """
    matched = 0
    our_pnl = 0.0
    leader_pnl = 0.0
    per_market: dict[str, tuple[float, float]] = {}
    used: set[int] = set()

    for ours in our_trades:
        m, s = ours.get("market"), str(ours.get("side", "")).upper()
        t0 = int(ours.get("opened_at_ms", 0))
        best_idx, best_dt = None, None
        for idx, lt in enumerate(leader_trades):
            if idx in used:
                continue
            if lt.get("market") != m or str(lt.get("side", "")).upper() != s:
                continue
            dt = abs(int(lt.get("opened_at_ms", 0)) - t0)
            if dt <= match_window_ms and (best_dt is None or dt < best_dt):
                best_idx, best_dt = idx, dt
        if best_idx is None:
            continue
        used.add(best_idx)
        matched += 1
        op = float(ours.get("pnl_net", 0.0))
        lp = float(leader_trades[best_idx].get("pnl_net", 0.0))
        our_pnl += op
        leader_pnl += lp
        po, pl = per_market.get(m, (0.0, 0.0))
        per_market[m] = (po + op, pl + lp)

    ratio = (our_pnl / leader_pnl) if leader_pnl > 0 else None
    return CopyCaptureReport(
        matched_trades=matched,
        our_pnl=round(our_pnl, 4),
        leader_pnl=round(leader_pnl, 4),
        capture_ratio=ratio,
        per_market=per_market,
    )


# ---------------------------------------------------------------------------
# 2. Walk-forward
# ---------------------------------------------------------------------------
@dataclass
class WalkForwardWindow:
    index: int
    start_ms: int
    end_ms: int
    trades: int
    pnl_net: float
    winrate: float


@dataclass
class WalkForwardReport:
    windows: list[WalkForwardWindow]
    positive_windows: int
    stability: float  # part de fenêtres positives (0-1)
    total_pnl: float

    def summary_text(self) -> str:
        return (
            f"WalkForward: {len(self.windows)} fenêtres | "
            f"{self.positive_windows} positives ({self.stability:.0%}) | "
            f"PnL total={self.total_pnl:+.2f} | "
            "Rappel: stabilité inter-fenêtres > PnL d'une fenêtre unique"
        )


def walk_forward_report(
    closed_trades: list[dict],
    n_windows: int = 4,
) -> WalkForwardReport:
    """
    Découper les trades clos (dict: closed_at_ms, pnl_net) en n fenêtres
    temporelles égales et mesurer le PnL de chacune (out-of-sample successif).
    """
    trades = sorted(
        (t for t in closed_trades if t.get("closed_at_ms")),
        key=lambda t: t["closed_at_ms"],
    )
    if not trades or n_windows < 1:
        return WalkForwardReport([], 0, 0.0, 0.0)

    t0 = int(trades[0]["closed_at_ms"])
    t1 = int(trades[-1]["closed_at_ms"]) + 1
    span = max(1, t1 - t0)
    width = span // n_windows or 1

    windows: list[WalkForwardWindow] = []
    for i in range(n_windows):
        ws = t0 + i * width
        we = t1 if i == n_windows - 1 else ws + width
        in_win = [t for t in trades if ws <= int(t["closed_at_ms"]) < we]
        pnl = sum(float(t.get("pnl_net", 0.0)) for t in in_win)
        wins = sum(1 for t in in_win if float(t.get("pnl_net", 0.0)) > 0)
        windows.append(WalkForwardWindow(
            index=i, start_ms=ws, end_ms=we, trades=len(in_win),
            pnl_net=round(pnl, 4),
            winrate=round(wins / len(in_win), 4) if in_win else 0.0,
        ))

    positive = sum(1 for w in windows if w.pnl_net > 0 and w.trades > 0)
    active = sum(1 for w in windows if w.trades > 0)
    return WalkForwardReport(
        windows=windows,
        positive_windows=positive,
        stability=round(positive / active, 4) if active else 0.0,
        total_pnl=round(sum(w.pnl_net for w in windows), 4),
    )


# ---------------------------------------------------------------------------
# 3. Résumé NO_TRADE hebdomadaire
# ---------------------------------------------------------------------------
def weekly_no_trade_summary(
    decisions: list,
    now_ms: int,
) -> dict:
    """
    Compter les refus de la semaine écoulée par raison.
    Accepte des NoTradeDecision ou des dicts {reason, timestamp_ms}.
    """
    cutoff = now_ms - WEEK_MS
    counter: Counter = Counter()
    total = 0
    for d in decisions:
        ts = getattr(d, "timestamp_ms", None) or (d.get("timestamp_ms") if isinstance(d, dict) else 0)
        if not ts or ts < cutoff:
            continue
        reason = getattr(d, "reason", None) or (d.get("reason") if isinstance(d, dict) else "?")
        counter[str(reason)] += 1
        total += 1
    return {
        "week_start_ms": cutoff,
        "total_refused": total,
        "by_reason": dict(counter.most_common()),
        "note": "Les refus protègent le PnL: un signal n'est jamais un ordre.",
    }
