"""IA-5 — Analyste shadow-only: explique chaque décision en clair.

Distillé de polymarket_agents (agent analyste, PAS exécutant). Génère une
explication lisible d'un trade/refus depuis ses features — SANS aucune autorité
hot-path (règle matrice: l'IA n'approuve jamais un ordre). Zéro dépendance: pur
template déterministe. Un backend Ollama local pourra être branché plus tard,
mais l'explication de base ne dépend d'aucun réseau ni API payante.
"""

from __future__ import annotations


def explain_decision(decision: dict) -> str:
    """Explication en français d'une décision (accept/refus) depuis ses champs."""
    d = decision if isinstance(decision, dict) else {}
    action = str(d.get("action") or d.get("paper_action_type") or "?").upper()
    coin = str(d.get("coin") or "?").upper()
    side = str(d.get("side") or d.get("leader_side") or "").upper()
    edge = d.get("edge_remaining_bps")
    age = d.get("signal_age_ms")
    consensus = d.get("leader_wallets_count") or d.get("consensus_wallets")
    liq = d.get("liquidity_score")
    reason = str(d.get("reason") or "")

    bits = [f"{action} {coin}" + (f" {side}" if side else "")]
    if edge is not None:
        bits.append(f"edge net {float(edge):.0f} bps")
    if consensus is not None:
        bits.append(f"{int(float(consensus))} wallet(s)")
    if age is not None:
        bits.append(f"âge {float(age)/1000:.1f}s")
    if liq is not None:
        bits.append(f"liquidité {float(liq):.2f}")
    head = " · ".join(bits)

    if "NO_TRADE" in action or reason:
        verdict = _refusal_verdict(reason)
        return f"{head} → REFUSÉ: {verdict}"
    return f"{head} → pris (evidence-first, shadow-only, aucune autorité d'exécution)"


def _refusal_verdict(reason: str) -> str:
    r = reason.upper()
    if "EDGE" in r:
        return "avantage net insuffisant après frais — bon réflexe si les coûts dominent"
    if "OLD" in r or "STALE" in r:
        return "signal trop vieux — copier tard = perdre sur le slippage"
    if "LIQUIDITY" in r:
        return "marché trop peu liquide — le fill coûterait trop cher"
    if "CONSENSUS" in r:
        return "consensus insuffisant — un seul acteur peut se tromper"
    if "NOTIONAL" in r:
        return "taille trop petite — les frais mangeraient le brut"
    if "PORTFOLIO" in r or "CORR" in r:
        return "portefeuille déjà trop exposé dans ce sens"
    return reason or "raison non spécifiée"


def summarize_session(closed_trades: list[dict]) -> str:
    rows = [t for t in (closed_trades or []) if isinstance(t, dict)]
    if not rows:
        return "Aucun trade clos à analyser pour l'instant."
    wins = [t for t in rows if float(t.get("net_pnl_usdc") or 0) > 0]
    net = sum(float(t.get("net_pnl_usdc") or 0) for t in rows)
    worst = min(rows, key=lambda t: float(t.get("net_pnl_usdc") or 0))
    return (f"{len(rows)} trades clos, {len(wins)} gagnants, PnL net {net:.2f} USDC. "
            f"Pire trade: {str(worst.get('coin') or '?')} {float(worst.get('net_pnl_usdc') or 0):.2f}. "
            f"Analyse shadow, aucune promesse de PnL.")


__all__ = ["explain_decision", "summarize_session"]
