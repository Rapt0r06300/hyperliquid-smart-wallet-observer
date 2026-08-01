"""[CABLAGE étage F] FILL → LEDGER → PnL : le candidat autorisé est exécuté en paper et comptabilisé au VRAI
ledger d'événements. On compose :
  - simulation.orderbook_execution_simulator.simulate_orderbook_execution : fill contre le carnet (slippage,
    partial/missed, fill_ratio) — un carnet trop mince → MISSED_FILL honnête, jamais un fill fabriqué ;
  - simulation.paper_ledger.PaperLedger : open/increase/reduce/close + mark-to-market, PnL réconcilié
    (equity = start + realized + unrealized − fees + funding).
Le slippage est dans le prix de fill ; les frais sont chargés par le ledger (fee_bps) — pas de double comptage.
Les flips (net opposé qui dépasse la position) sont réduits jusqu'à zéro et le résidu est SIGNALÉ, pas exécuté
en aveugle (le vrai flip-as-two-operations est une pépite dédiée). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.simulation.orderbook_execution_simulator import simulate_orderbook_execution
from hl_observer.simulation.paper_ledger import PaperLedger


class ExecuteurPaper:
    """Détient un PaperLedger et applique un candidat netté au chemin réel fill→ledger. Suit le côté ouvert par
    coin pour router chaque net vers open/increase/reduce/close. mark-to-market et PnL réconcilié exposés."""

    def __init__(self, *, starting_balance_usdc: float = 1000.0, fee_bps: float = 4.5,
                 min_fill_ratio: float = 0.85) -> None:
        self.ledger = PaperLedger(starting_balance_usdc=starting_balance_usdc)
        self.fee_bps = float(fee_bps)
        self.min_fill_ratio = float(min_fill_ratio)
        self._side: dict[str, Any] = {}

    def executer(self, candidat: dict[str, Any], *, book: dict[str, Any], mid: float,
                 ts_ms: int) -> dict[str, Any]:
        coin = candidat["coin"]
        cote = candidat["cote"]
        notional = float(candidat["notional"])
        fill = simulate_orderbook_execution(
            side="BUY" if cote == "BUY" else "SELL", notional_usdc=notional, mid_price=float(mid),
            asks=tuple(book.get("asks", ())), bids=tuple(book.get("bids", ())),
            fee_bps=self.fee_bps, min_fill_ratio=self.min_fill_ratio)
        if fill.missed or fill.average_fill_price is None or fill.filled_notional_usdc <= 0:
            ev = self.ledger.no_trade(coin=coin, reason="MISSED_FILL", timestamp_ms=ts_ms)
            return {"execute": False, "raison": "MISSED_FILL", "fill": fill, "event": ev,
                    "fill_ratio": fill.fill_ratio}
        fill_price = float(fill.average_fill_price)
        filled = float(fill.filled_notional_usdc)
        cur = self._side.get(coin)
        want = "LONG" if cote == "BUY" else "SHORT"
        residu_flip = 0.0
        if cur is None or cur == want:
            ev = self.ledger.open_position(coin=coin, side=want, notional_usdc=filled,
                                           fill_price=fill_price, timestamp_ms=ts_ms, fee_bps=self.fee_bps)
            self._side[coin] = want
            action = "OPEN" if cur is None else "INCREASE"
        else:
            pos = self.ledger.positions.get("%s:%s" % (coin, cur))
            qty_demandee = filled / fill_price
            qty_pos = float(pos.quantity) if pos is not None else 0.0
            qty_reduce = min(qty_demandee, qty_pos)
            residu_flip = round(max(0.0, qty_demandee - qty_pos) * fill_price, 8)   # signalé, pas exécuté
            ev = self.ledger.reduce_or_close(coin=coin, side=cur, quantity=qty_reduce,
                                             fill_price=fill_price, timestamp_ms=ts_ms, fee_bps=self.fee_bps)
            action = "REDUCE_OR_CLOSE"
            if ("%s:%s" % (coin, cur)) not in self.ledger.positions:
                self._side[coin] = None
        return {"execute": True, "action": action, "fill": fill, "event": ev,
                "fill_price": fill_price, "filled_notional": filled, "residu_flip_non_execute": residu_flip}

    def marquer(self, marks: dict[str, float], *, ts_ms: int) -> Any:
        return self.ledger.mark_to_market(marks, timestamp_ms=ts_ms)

    def pnl(self) -> dict[str, Any]:
        rec = self.ledger.reconciliation()
        return {"equity": self.ledger.equity_usdc, "realized": self.ledger.realized_pnl_usdc,
                "unrealized": self.ledger.unrealized_pnl_usdc, "fees": self.ledger.fees_paid_usdc,
                "drawdown": self.ledger.drawdown_usdc, "reconcilie": bool(rec.ok)}


__all__ = ["ExecuteurPaper"]
