"""Microstructure de marché — algorithmes PURS, testés (avec données synthétiques). Exécution du
backlog : order_flow_imbalance (IDEA-11), kyle_lambda (IDEA-14), vpin (IDEA-13),
lee_ready_sign (IDEA-19), slippage_from_depth (IDEA-55). Ces fonctions n'ont besoin de données L2/
tick que pour TOURNER en prod ; elles sont construites et vérifiées ici. Aucun ordre.
"""
from __future__ import annotations


def order_flow_imbalance(bid_p, bid_s, ask_p, ask_s) -> float:
    """OFI cumulé (Cont et al.) sur des snapshots de meilleur bid/ask. Positif = pression acheteuse."""
    n = min(len(bid_p), len(bid_s), len(ask_p), len(ask_s))
    ofi = 0.0
    for t in range(1, n):
        if bid_p[t] > bid_p[t - 1]:
            ofi += bid_s[t]
        elif bid_p[t] == bid_p[t - 1]:
            ofi += bid_s[t] - bid_s[t - 1]
        else:
            ofi -= bid_s[t - 1]
        if ask_p[t] > ask_p[t - 1]:
            ofi += ask_s[t - 1]
        elif ask_p[t] == ask_p[t - 1]:
            ofi -= ask_s[t] - ask_s[t - 1]
        else:
            ofi -= ask_s[t]
    return ofi


def kyle_lambda(price_changes, signed_volumes) -> float:
    """Lambda de Kyle : impact-prix par unité de volume signé (pente OLS Δprix ~ volume)."""
    n = min(len(price_changes), len(signed_volumes))
    if n < 2:
        return 0.0
    mx = sum(signed_volumes[:n]) / n
    my = sum(price_changes[:n]) / n
    num = sum((signed_volumes[i] - mx) * (price_changes[i] - my) for i in range(n))
    den = sum((signed_volumes[i] - mx) ** 2 for i in range(n))
    return num / den if den > 0 else 0.0


def vpin(buy_volumes, sell_volumes) -> float:
    """VPIN : toxicité moyenne du flux = moyenne de |achat-vente|/(achat+vente) par bucket."""
    n = min(len(buy_volumes), len(sell_volumes))
    vals = []
    for i in range(n):
        tot = buy_volumes[i] + sell_volumes[i]
        if tot > 0:
            vals.append(abs(buy_volumes[i] - sell_volumes[i]) / tot)
    return sum(vals) / len(vals) if vals else 0.0


def lee_ready_sign(trade_price, mid, *, prev_trade=None) -> int:
    """Sens d'un trade (Lee-Ready) : +1 acheteur agressif, -1 vendeur, tick-rule si au mid."""
    if trade_price > mid:
        return 1
    if trade_price < mid:
        return -1
    if prev_trade is not None:
        if trade_price > prev_trade:
            return 1
        if trade_price < prev_trade:
            return -1
    return 0


def slippage_from_depth(order_size, levels, *, side: str = "BUY") -> float:
    """Slippage (bps) en 'walkant' le carnet. `levels` : [(prix, taille)] du meilleur au pire."""
    if not levels or float(order_size) <= 0:
        return 0.0
    best = float(levels[0][0])
    remaining = float(order_size)
    cost = filled = 0.0
    for price, size in levels:
        take = min(remaining, float(size))
        cost += take * float(price)
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    if filled <= 0 or best <= 0:
        return 0.0
    avg = cost / filled
    slip = (avg - best) / best if str(side).upper() == "BUY" else (best - avg) / best
    return slip * 10000.0
