"""P3 — Scoring leader par marché + shortlist PF net + anti faux-consensus.

- Winrate d'un leader SUR CE COIN < 40% → score du signal réduit (un bon trader
  BTC peut être nul sur les memecoins).
- Shortlist = leaders à profit factor net > 1 sur fenêtre glissante (pas au volume).
- Anti faux-consensus: 3 wallets qui tradent identiquement = souvent 1 humain →
  on compte les CLUSTERS, pas les adresses. Pur.
"""

from __future__ import annotations


def leader_market_winrate(closed_trades: list[dict], wallet: str, coin: str) -> dict:
    """Winrate d'un wallet sur un coin depuis ses trades clos."""
    rows = [
        t for t in (closed_trades or [])
        if isinstance(t, dict)
        and str(t.get("wallet") or "").lower() == str(wallet).lower()
        and str(t.get("coin") or "").upper() == str(coin).upper()
    ]
    n = len(rows)
    wins = sum(1 for t in rows if float(t.get("net_pnl_usdc") or 0.0) > 0)
    return {"wallet": wallet, "coin": str(coin).upper(), "n": n,
            "winrate": (wins / n) if n else None, "wins": wins}


def market_score_multiplier(closed_trades: list[dict], wallet: str, coin: str, *, min_trades: int = 4, weak_winrate: float = 0.40) -> float:
    """Multiplicateur ∈ [0.5, 1.0]: réduit si le leader est faible sur CE coin."""
    wr = leader_market_winrate(closed_trades, wallet, coin)
    if wr["n"] < min_trades or wr["winrate"] is None:
        return 1.0  # pas assez d'historique → neutre (pas de pénalité inventée)
    return 0.5 if wr["winrate"] < weak_winrate else 1.0


def profit_factor_net(closed_trades: list[dict], wallet: str) -> dict:
    rows = [t for t in (closed_trades or []) if isinstance(t, dict) and str(t.get("wallet") or "").lower() == str(wallet).lower()]
    gains = sum(float(t.get("net_pnl_usdc") or 0.0) for t in rows if float(t.get("net_pnl_usdc") or 0.0) > 0)
    losses = -sum(float(t.get("net_pnl_usdc") or 0.0) for t in rows if float(t.get("net_pnl_usdc") or 0.0) < 0)
    pf = (gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
    return {"wallet": wallet, "n": len(rows), "gains": round(gains, 4), "losses": round(losses, 4),
            "profit_factor_net": pf if pf != float("inf") else 999.0}


def shortlist_by_net_pf(closed_trades: list[dict], wallets: list[str], *, min_pf: float = 1.0, min_trades: int = 5) -> tuple[str, ...]:
    scored = []
    for w in wallets or []:
        pf = profit_factor_net(closed_trades, w)
        if pf["n"] >= min_trades and pf["profit_factor_net"] >= min_pf:
            scored.append((pf["profit_factor_net"], w))
    scored.sort(reverse=True)
    return tuple(w for _, w in scored)


def count_consensus_clusters(votes: list[dict], *, time_window_ms: int = 3_000) -> dict:
    """Regroupe les wallets qui votent identiquement (coin/side) dans une fenêtre.

    Chaque groupe fenêtré = 1 cluster (potentiellement 1 seul acteur). Le vrai
    consensus = nombre de clusters distincts, pas de wallets.
    """
    buckets: dict[tuple, list[dict]] = {}
    for v in votes or []:
        if not isinstance(v, dict):
            continue
        coin = str(v.get("coin") or "").upper()
        side = str(v.get("side") or "").upper()
        ts = int(v.get("ts_ms") or 0)
        bucket_ts = ts // max(1, time_window_ms)
        buckets.setdefault((coin, side, bucket_ts), []).append(v)
    clusters = len(buckets)
    wallets = len({str(v.get("wallet") or "") for v in votes if isinstance(v, dict)})
    return {"raw_wallets": wallets, "consensus_clusters": clusters,
            "inflation_ratio": round(wallets / clusters, 3) if clusters else 0.0}


def is_vault_leader(wallet_meta: dict) -> bool:
    """Vault HL = leader copiable (stratégie étiquetée, high-water mark)."""
    if not isinstance(wallet_meta, dict):
        return False
    return bool(wallet_meta.get("is_vault")) or "vault" in str(wallet_meta.get("type") or "").lower()


__all__ = ["leader_market_winrate", "market_score_multiplier", "profit_factor_net",
           "shortlist_by_net_pf", "count_consensus_clusters", "is_vault_leader"]
