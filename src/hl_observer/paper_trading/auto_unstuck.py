"""V26 L3 — Auto-Unstuck (porté de passivbot docs/risk_management.md §3.A).

Au lieu de laisser pourrir une position coincée (sous l'eau, vieille, exposée),
on réalise des pertes PARTIELLES contrôlées :

1. cible = la position stuck **la moins sous l'eau** d'abord (retour au vert rapide) ;
2. close partiel ``fraction`` (défaut 10 %) au mark réel, coûts inclus ;
3. budget de pertes unstuck plafonné (``allowance USD`` sur fenêtre 24 h) —
   budget épuisé ⇒ plus d'unstuck tant que la fenêtre n'a pas tourné.

Chaque unstuck = événement ledger explicite ``UNSTUCK_PARTIAL`` (traçabilité
dashboard = audit). Opt-in : ``HYPERSMART_V26_AUTO_UNSTUCK=1`` (défaut OFF).
Paper-only : un close partiel simulé n'est jamais un ordre.
"""

from __future__ import annotations
from hl_observer.strategies.strategy_mode import mode_of_position

import os
from typing import Any

MASTER_FLAG = "HYPERSMART_V26_AUTO_UNSTUCK"
UNDERWATER_ENV = "HYPERSMART_V26_UNSTUCK_UNDERWATER_BPS"   # stuck si perte latente >= X bps
MIN_AGE_ENV = "HYPERSMART_V26_UNSTUCK_MIN_AGE_MIN"          # et âge >= X minutes
FRACTION_ENV = "HYPERSMART_V26_UNSTUCK_FRACTION"            # part de la position close
BUDGET_ENV = "HYPERSMART_V26_UNSTUCK_BUDGET_USD"            # pertes unstuck max / fenêtre
BUDGET_WINDOW_ENV = "HYPERSMART_V26_UNSTUCK_BUDGET_WINDOW_MIN"
MAX_PER_PASS_ENV = "HYPERSMART_V26_UNSTUCK_MAX_PER_PASS"

_DEF = {
    UNDERWATER_ENV: 120.0,      # -1.2% latent
    MIN_AGE_ENV: 45.0,          # 45 min
    FRACTION_ENV: 0.10,         # 10% par unstuck (passivbot: chip away)
    BUDGET_ENV: 10.0,           # ~1% d'une equity 1000 (aligné allowance passivbot)
    BUDGET_WINDOW_ENV: 1440.0,  # 24 h
    MAX_PER_PASS_ENV: 1.0,      # 1 unstuck max par passe (prudence)
}

EXIT_METHOD = "UNSTUCK_PARTIAL"


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def _signed_pnl_bps(side: str, avg: float, mark: float) -> float:
    if avg <= 0:
        return 0.0
    move = (mark - avg) / avg * 10_000.0
    return -move if side.upper() == "SHORT" else move


def _identity(key: object, pos: dict) -> tuple[str, str, str] | None:
    if isinstance(key, str):
        parts = key.split("|")
        if len(parts) >= 3:
            return parts[0], parts[1].upper(), parts[2].upper()
    coin = str(pos.get("coin") or "").upper()
    side = str(pos.get("side") or pos.get("direction") or "").upper()
    if coin and side in {"LONG", "SHORT"}:
        return str(pos.get("wallet_address") or ""), coin, side
    return None


def unstuck_budget_spent_usd(ledger_events: list[dict], now_ms: int, window_min: float) -> float:
    """Pertes unstuck déjà réalisées dans la fenêtre (depuis le ledger, vérité unique)."""
    cutoff = int(now_ms) - int(window_min * 60_000)
    spent = 0.0
    for ev in ledger_events or []:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("exit_method") or "") != EXIT_METHOD:
            continue
        if int(ev.get("observed_at_ms") or 0) < cutoff:
            continue
        pnl = float(ev.get("estimated_net_pnl_usdc") or 0.0)
        if pnl < 0:
            spent += -pnl
    return round(spent, 6)


def apply_auto_unstuck(
    positions: dict[Any, dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    mid_prices: dict[str, float] | None,
    *,
    now_ms: int,
    cost_bps: float = 12.0,
    env: dict | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
) -> list[dict[str, Any]]:
    """Une passe d'auto-unstuck. Mutations : réduit ``size`` des positions traitées.

    Retourne la liste des actions (vide si flag OFF / rien de stuck / budget épuisé).
    """
    if not flag_on(env) or not positions:
        return []
    marks = mid_prices or {}
    underwater_min = _f(UNDERWATER_ENV, env)
    min_age_ms = int(_f(MIN_AGE_ENV, env) * 60_000)
    fraction = min(0.5, max(0.01, _f(FRACTION_ENV, env)))
    budget = _f(BUDGET_ENV, env)
    spent = unstuck_budget_spent_usd(ledger_events, now_ms, _f(BUDGET_WINDOW_ENV, env))
    remaining_budget = budget - spent
    if remaining_budget <= 0:
        return [{"action": "UNSTUCK_SKIPPED", "reason": "BUDGET_EXHAUSTED", "spent_usd": spent, "budget_usd": budget}]

    # 1) candidats stuck : sous l'eau ET assez vieux
    stuck: list[tuple[float, object, dict, str, str, str, float]] = []
    for key, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        ident = _identity(key, pos)
        if ident is None:
            continue
        wallet, coin, side = ident
        size = abs(float(pos.get("size") or 0.0))
        avg = float(pos.get("avg_price") or 0.0)
        mark = float(marks.get(coin) or 0.0)
        if size <= 0 or avg <= 0 or mark <= 0:
            continue
        pnl_bps = _signed_pnl_bps(side, avg, mark)
        opened = int(float(pos.get("opened_at_ms") or 0))
        age_ms = max(0, int(now_ms) - opened) if opened > 0 else 0
        if pnl_bps <= -abs(underwater_min) and age_ms >= min_age_ms:
            stuck.append((pnl_bps, key, pos, wallet, coin, side, mark))

    if not stuck:
        return []

    # 2) priorité passivbot : la MOINS sous l'eau d'abord (pnl_bps le plus haut)
    stuck.sort(key=lambda x: x[0], reverse=True)
    max_per_pass = max(1, int(_f(MAX_PER_PASS_ENV, env)))
    actions: list[dict[str, Any]] = []

    for pnl_bps, key, pos, wallet, coin, side, mark in stuck[:max_per_pass]:
        size = abs(float(pos.get("size") or 0.0))
        avg = float(pos.get("avg_price") or 0.0)
        close_size = size * fraction
        gross = (mark - avg) * close_size if side == "LONG" else (avg - mark) * close_size
        exit_cost = abs(close_size * mark) * cost_bps / 10_000.0
        net = gross - exit_cost
        # respect strict du budget : si cette perte dépasse le restant, on réduit la part
        if net < 0 and -net > remaining_budget:
            scale = remaining_budget / (-net)
            if scale < 0.2:  # part résiduelle trop petite pour être utile -> skip honnête
                actions.append({"action": "UNSTUCK_SKIPPED", "reason": "BUDGET_TOO_SMALL_FOR_MIN_CHIP", "coin": coin})
                continue
            close_size *= scale
            gross *= scale
            exit_cost *= scale
            net = gross - exit_cost
        new_size = max(0.0, size - close_size)
        matched_key = f"{wallet}|{coin}|{side}"
        ledger_events.append({
            "coin": coin,
            "leader_side": side,
            "matched_position_key": matched_key,
            "strategy_mode": mode_of_position(pos),
            "paper_action_type": "CLOSE",
            "exit_method": EXIT_METHOD,
            "reason": "UNSTUCK_PARTIAL_CLOSE_LOCAL_REPLAY_NOT_AN_ORDER",
            "estimated_net_pnl_usdc": round(net, 6),
            "gross_pnl_usdc": round(gross, 6),
            "fee_cost_usdc": round(exit_cost, 6),
            "average_entry_price": round(avg, 8),
            "exit_price": round(mark, 8),
            "notional_closed_usdt": round(abs(close_size * mark), 6),
            "unstuck_pnl_bps_at_action": round(pnl_bps, 4),
            "unstuck_fraction": round(fraction, 4),
            "unstuck_budget_spent_before_usd": round(spent, 6),
            "unstuck_budget_usd": round(budget, 6),
            "size_before": round(size, 10),
            "size_closed": round(close_size, 10),
            "size_after": round(new_size, 10),
            "reduce_fraction": round(close_size / size, 6) if size > 0 else 0.0,
            "research_only": True,
            "paper_mode": paper_mode,
            "observed_at_ms": int(now_ms),
            "status": "LOCAL_REPLAY",
        })
        if new_size <= 1e-12:
            positions.pop(key, None)
        else:
            pos["size"] = new_size if float(pos.get("size") or 0.0) >= 0 else -new_size
        if net < 0:
            remaining_budget -= -net
        actions.append({
            "action": "UNSTUCK_PARTIAL_CLOSE",
            "coin": coin,
            "side": side,
            "net_pnl_usdc": round(net, 6),
            "size_closed": round(close_size, 10),
            "remaining_budget_usd": round(remaining_budget, 6),
        })

    return actions


__all__ = ["MASTER_FLAG", "EXIT_METHOD", "flag_on", "unstuck_budget_spent_usd", "apply_auto_unstuck"]
