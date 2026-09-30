"""V9 — Historique réalisé par leader (pour le gate de qualité de la shortlist).

Calcule, depuis les deltas de position RÉELS (PositionDeltaModel), les allers-retours
fermés de chaque leader et le mouvement signé (bps) entrée->sortie. Sert à qualifier
les leaders (winrate, edge réalisé) avant de les copier. Aucune donnée inventée.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
EXIT_ACTIONS = {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}


def round_trip_moves(deltas: Iterable[dict]) -> dict[str, list[float]]:
    """deltas chronologiques (dict: wallet, coin, side LONG/SHORT, action, price)
    -> {wallet: [move_bps des allers-retours fermés]}. Une position par (wallet,coin,side).
    """
    book: dict[tuple, float] = {}
    out: dict[str, list[float]] = defaultdict(list)
    for d in deltas:
        wallet = str(d.get("wallet") or "")
        coin = str(d.get("coin") or "").upper()
        side = str(d.get("side") or "").upper()
        action = str(d.get("action") or "").upper()
        price = d.get("price")
        if not wallet or side not in {"LONG", "SHORT"} or price in (None, 0):
            continue
        price = float(price)
        if price <= 0:
            continue
        key = (wallet, coin, side)
        if action in ENTRY_ACTIONS:
            book.setdefault(key, price)               # première entrée fait foi
        elif action in EXIT_ACTIONS and key in book:
            entry = book.pop(key)
            move = (price - entry) / entry
            if side == "SHORT":
                move = -move
            out[wallet].append(move * 10_000.0)
    return dict(out)


def wallet_round_trip_moves_from_session(session, wallets, *, max_rows: int = 20_000) -> dict[str, list[float]]:
    """Charge les deltas réels des wallets et renvoie leurs mouvements d'allers-retours."""
    addrs = [w for w in dict.fromkeys(wallets) if w]
    if not addrs:
        return {}
    try:
        from hl_observer.storage.models import PositionDeltaModel
    except Exception:
        return {}
    rows = (
        session.query(PositionDeltaModel)
        .filter(PositionDeltaModel.wallet_address.in_(addrs))
        .order_by(PositionDeltaModel.detected_at_ms.asc())
        .limit(int(max_rows))
        .all()
    )
    deltas = [
        {
            "wallet": r.wallet_address,
            "coin": r.coin,
            "side": (r.side or r.new_side or r.previous_side),
            "action": r.action,
            "price": r.price,
        }
        for r in rows
    ]
    return round_trip_moves(deltas)


__all__ = ["round_trip_moves", "wallet_round_trip_moves_from_session"]
