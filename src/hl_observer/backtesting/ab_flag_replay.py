"""V26 L9 — Harnais A/B REPLAY : mesurer l'effet réel des lots V26 sur le PF.

Rejoue la MÊME fenêtre de candidats enregistrés (JSONL, produits par le moteur avec
``HYPERSMART_V26_RECORD_CANDIDATES=1``) sous deux jeux de flags :

* bras A (baseline) : tous les vetos V26 OFF ;
* bras B (V26)      : flags choisis ON.

Pour chaque candidat accepté, l'issue est simulée sur le CHEMIN DE MARKS RÉELS
enregistré (marks.jsonl) : sortie TP/SL/trailing (config de base, ou vol-ajustée si
le bras l'active) ou timeout d'horizon au dernier mark connu. Aucune donnée future
inventée : pas de marks après l'entrée ⇒ candidat marqué UNMEASURABLE, exclu des
deux bras (jamais compté d'un seul côté).

Contexte REPLAY strict : ne lit que des fichiers, n'écrit que le rapport demandé,
ne touche JAMAIS au ledger live, n'émet aucun ordre. Les métriques (PF, WR, DD) sont
descriptives — pas une promesse de PnL.

CLI : ``python -m hl_observer.backtesting.ab_flag_replay --candidates F --marks F [--out F]``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp

CONTEXT = "REPLAY"
DEFAULT_HORIZON_MIN = 240.0
DEFAULT_COST_BPS = 12.0

# Bras B par défaut : les vetos d'entrée + barrières vol (mesure de L1+L2+L4+L5+L7+L8)
DEFAULT_ARM_B_ENV = {
    "HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE": "1",
    "HYPERSMART_V26_PROTECTIONS": "1",
    "HYPERSMART_V26_GRADED_HALT": "0",       # dépend d'un état runtime, OFF par défaut en replay
    "HYPERSMART_V26_TIER_COST_BUDGET": "1",
    "HYPERSMART_V26_MARKET_QUALITY": "0",    # nécessite l'univers noté du runtime, OFF en replay
    "HYPERSMART_V26_VOL_BARRIERS": "1",
}
ARM_A_ENV = {k: "0" for k in DEFAULT_ARM_B_ENV}


@dataclass
class ArmMetrics:
    name: str
    candidates_seen: int = 0
    accepted: int = 0
    unmeasurable: int = 0
    trades: list[float] = field(default_factory=list)   # net pnl usd par trade

    def report(self) -> dict:
        wins = [t for t in self.trades if t > 0]
        losses = [t for t in self.trades if t <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        pf = round(gross_win / gross_loss, 4) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        equity, peak, max_dd = 0.0, 0.0, 0.0
        for t in self.trades:
            equity += t
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return {
            "arm": self.name,
            "context": CONTEXT,
            "candidates_seen": self.candidates_seen,
            "accepted": self.accepted,
            "trades": len(self.trades),
            "unmeasurable_excluded": self.unmeasurable,
            "win_rate": round(len(wins) / len(self.trades), 4) if self.trades else None,
            "profit_factor": pf if pf != float("inf") else "inf",
            "net_total_usd": round(sum(self.trades), 4),
            "gross_win_usd": round(gross_win, 4),
            "gross_loss_usd": round(gross_loss, 4),
            "max_drawdown_usd": round(max_dd, 4),
        }


def load_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    out.append(row)
            except json.JSONDecodeError:
                continue  # ligne corrompue ignorée (jamais réparée/inventée)
    return out


def marks_by_coin(mark_rows: list[dict]) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = {}
    for r in mark_rows:
        coin = str(r.get("coin") or "").upper()
        try:
            ts, mid = float(r.get("ts")), float(r.get("mid"))
        except (TypeError, ValueError):
            continue
        if coin and mid > 0:
            out.setdefault(coin, []).append((ts, mid))
    for coin in out:
        out[coin].sort()
    return out


def simulate_exit_on_path(
    *,
    side: str,
    entry_price: float,
    path: list[tuple[float, float]],
    entry_ts: float,
    config: SLTPConfig,
    horizon_min: float = DEFAULT_HORIZON_MIN,
    cost_bps: float = DEFAULT_COST_BPS,
    notional_usd: float = 50.0,
) -> float | None:
    """PnL net USD d'un trade simulé sur le chemin de marks réels. None = non mesurable."""
    future = [(t, m) for (t, m) in path if t > entry_ts and t <= entry_ts + horizon_min * 60.0]
    if not future or entry_price <= 0:
        return None
    peak = entry_price
    exit_price = future[-1][1]  # défaut : timeout d'horizon au dernier mark réel
    for _, mark in future:
        peak = max(peak, mark) if side == "LONG" else min(peak, mark)
        d = evaluate_sl_tp(side=side, entry_price=entry_price, current_price=mark, peak_price=peak, config=config)
        if d.exit:
            exit_price = mark
            break
    move = (exit_price - entry_price) / entry_price
    gross = notional_usd * (move if side == "LONG" else -move)
    costs = notional_usd * cost_bps / 10_000.0 * 2  # entrée + sortie
    return gross - costs


def _evaluate_arm(
    name: str,
    env: dict,
    candidates: list[dict],
    marks: dict[str, list[tuple[float, float]]],
    *,
    base_config: SLTPConfig,
    horizon_min: float,
    cost_bps: float,
) -> ArmMetrics:
    from hl_observer.paper_trading.vol_adjusted_barriers import (
        MidVolEstimator,
        adjust_config,
        vol_factor_for_coin,
    )
    from hl_observer.signals.v26_entry_vetos import EdgeTrendRecorder, apply_v26_entry_vetos

    m = ArmMetrics(name=name)
    recorder = EdgeTrendRecorder()          # état ISOLÉ par bras (aucune fuite du live)
    estimator = MidVolEstimator()
    vol_on = str(env.get("HYPERSMART_V26_VOL_BARRIERS", "0")).lower() in ("1", "true", "yes", "on")

    for cand in candidates:
        coin = str(cand.get("coin") or "").upper()
        side = str(cand.get("direction") or "").upper()
        edge = cand.get("edge_remaining_bps")
        entry = float(cand.get("current_mid") or 0.0)
        ts = float(cand.get("recorded_at") or 0.0)
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        m.candidates_seen += 1
        # nourrir l'estimateur de vol avec les marks réels antérieurs au candidat
        for t_mk, mid in marks.get(coin, []):
            if t_mk <= ts:
                estimator.record(coin, mid, ts=t_mk)
        # baseline d'acceptation : le candidat enregistré était déjà passé par le score V25 ;
        # on rejoue UNIQUEMENT les vetos V26 (c'est leur effet qu'on mesure, toutes choses égales).
        vetoes = apply_v26_entry_vetos(
            coin=coin, side=side,
            edge_remaining_bps=float(edge) if edge is not None else None,
            leader_score=cand.get("leader_score"),
            copy_degradation_bps=cand.get("copy_degradation_bps"),
            liquidity_score=cand.get("liquidity_score"),
            env=env, recorder=recorder, now_ms=int(ts * 1000),
        )
        if vetoes:
            continue
        m.accepted += 1
        cfg = base_config
        if vol_on:
            factor = vol_factor_for_coin(coin, estimator=estimator, env=env, now=ts)
            cfg = adjust_config(base_config, factor, sl_floor_bps=12.0)
        pnl = simulate_exit_on_path(
            side=side, entry_price=entry, path=marks.get(coin, []), entry_ts=ts,
            config=cfg, horizon_min=horizon_min, cost_bps=cost_bps,
            notional_usd=float(cand.get("leader_notional_usdt") or 50.0) if float(cand.get("leader_notional_usdt") or 0) > 0 else 50.0,
        )
        if pnl is None:
            m.unmeasurable += 1
            m.accepted -= 1
            continue
        m.trades.append(round(pnl, 6))
    return m


def run_ab_replay(
    candidates: list[dict],
    mark_rows: list[dict],
    *,
    arm_b_env: dict | None = None,
    base_config: SLTPConfig | None = None,
    horizon_min: float = DEFAULT_HORIZON_MIN,
    cost_bps: float = DEFAULT_COST_BPS,
) -> dict:
    """Compare bras A (V26 OFF) vs bras B (V26 ON). Déterministe, REPLAY-only."""
    marks = marks_by_coin(mark_rows)
    cfg = base_config or SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0)
    env_b = dict(DEFAULT_ARM_B_ENV)
    if arm_b_env:
        env_b.update({k: str(v) for k, v in arm_b_env.items()})
    a = _evaluate_arm("A_baseline_v26_off", dict(ARM_A_ENV), candidates, marks,
                      base_config=cfg, horizon_min=horizon_min, cost_bps=cost_bps)
    b = _evaluate_arm("B_v26_on", env_b, candidates, marks,
                      base_config=cfg, horizon_min=horizon_min, cost_bps=cost_bps)
    ra, rb = a.report(), b.report()
    # VALID-GATES: chaque bras passe par les gates de validation unifiees ; on ne
    # recommande d'activer B que s'il passe TOUS les gates ET ameliore le net vs A.
    from hl_observer.backtesting.validation_gates import run_validation_gates
    va, vb = run_validation_gates(a.trades), run_validation_gates(b.trades)
    b_improves = (rb["net_total_usd"] or 0) > (ra["net_total_usd"] or 0)
    recommend = "ACTIVATE_B" if (vb["verdict"] == "DEPLOY_CANDIDATE" and b_improves) else "KEEP_A"
    return {
        "context": CONTEXT,
        "honesty": "metriques descriptives sur donnees enregistrees ; aucune promesse de PnL",
        "arm_a": ra,
        "arm_b": rb,
        "delta_net_usd": round((rb["net_total_usd"] or 0) - (ra["net_total_usd"] or 0), 4),
        "arm_a_validation": va,
        "arm_b_validation": vb,
        "recommendation": recommend,
        "recommendation_rule": "ACTIVATE_B seulement si B passe tous les gates ET ameliore le net vs A (paper-only)",
        "arm_b_env": env_b,
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — CLI mince
    import argparse

    ap = argparse.ArgumentParser(description="V26 L9 — A/B replay des flags (REPLAY, paper-only)")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--horizon-min", type=float, default=DEFAULT_HORIZON_MIN)
    args = ap.parse_args(argv)
    report = run_ab_replay(load_jsonl(args.candidates), load_jsonl(args.marks), horizon_min=args.horizon_min)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

__all__ = [
    "CONTEXT", "ArmMetrics", "load_jsonl", "marks_by_coin",
    "simulate_exit_on_path", "run_ab_replay", "DEFAULT_ARM_B_ENV",
]
