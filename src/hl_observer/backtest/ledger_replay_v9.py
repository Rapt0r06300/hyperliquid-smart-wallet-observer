"""Replay V9 sur le ledger RÉEL — diagnostic PnL de copie, sans fabrication.

Reconstruit les positions des leaders depuis le journal de décisions réel
(`simulation_decisions_append_only.jsonl`) et calcule le PnL qu'aurait produit la
copie V9 : on entre au prix RÉEL d'ouverture du leader, on sort au prix RÉEL de
fermeture du leader. Sépare le PnL BRUT (pur mouvement du leader) du PnL NET
(après nos coûts de copie). C'est un backtest honnête : aucune donnée inventée,
aucun look-ahead pour la décision d'entrée (filtres structurels V9 uniquement).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from hl_observer.markets.universe import is_exotic_market


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
EXIT_ACTIONS = {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    notional_usdt: float = 50.0
    fee_bps: float = 2.5
    spread_bps: float = 3.0
    slippage_bps: float = 1.5
    max_signal_age_ms: int = 30_000
    hard_backfill_age_ms: int = 60_000
    allow_exotic: bool = False

    @property
    def round_trip_cost_bps(self) -> float:
        return 2 * self.fee_bps + self.spread_bps + 2 * self.slippage_bps


@dataclass(slots=True)
class ReplayResult:
    entries: int = 0
    matched_round_trips: int = 0
    still_open: int = 0
    wins_gross: int = 0
    wins_net: int = 0
    gross_pnl_usdt: float = 0.0
    net_pnl_usdt: float = 0.0
    cost_usdt: float = 0.0
    skipped_exotic: int = 0
    skipped_stale: int = 0
    skipped_dup: int = 0
    per_coin_net: dict[str, float] = field(default_factory=dict)

    @property
    def winrate_gross(self) -> float:
        return self.wins_gross / self.matched_round_trips if self.matched_round_trips else 0.0

    @property
    def winrate_net(self) -> float:
        return self.wins_net / self.matched_round_trips if self.matched_round_trips else 0.0


def _signed_move(side: str, entry: float, exit_: float) -> float:
    if entry <= 0:
        return 0.0
    m = (exit_ - entry) / entry
    return -m if side.upper() == "SHORT" else m


def replay_ledger_v9(rows: list[dict], *, config: ReplayConfig | None = None) -> ReplayResult:
    cfg = config or ReplayConfig()
    res = ReplayResult()
    rows = sorted(rows, key=lambda r: int(r.get("timestamp_ms") or 0))
    book: dict[str, dict] = {}
    seen: set[tuple] = set()

    for r in rows:
        coin = str(r.get("coin") or "").upper()
        side = str(r.get("leader_side") or "").upper()
        action = str(r.get("leader_action") or "").upper()
        wallet = str(r.get("wallet_address") or "")
        price = r.get("leader_price")
        age = r.get("signal_age_ms")
        if not coin or side not in {"LONG", "SHORT"} or price in (None, 0):
            continue
        price = float(price)

        if not cfg.allow_exotic and is_exotic_market(coin):
            res.skipped_exotic += 1
            continue
        ident = (wallet, coin, side, action, round(price, 6), int(r.get("timestamp_ms") or 0))
        if ident in seen:
            res.skipped_dup += 1
            continue
        seen.add(ident)

        key = f"{wallet}|{coin}|{side}"

        if action in ENTRY_ACTIONS:
            if isinstance(age, (int, float)) and age > cfg.hard_backfill_age_ms:
                res.skipped_stale += 1
                continue
            if key not in book:  # une seule position par leader/coin/side
                book[key] = {"entry": price, "coin": coin, "side": side}
                res.entries += 1
        elif action in EXIT_ACTIONS:
            pos = book.pop(key, None)
            if pos is None:
                continue  # sortie orpheline -> ignorée (pas de bruit)
            move = _signed_move(side, pos["entry"], price)
            gross = cfg.notional_usdt * move
            cost = cfg.notional_usdt * (cfg.round_trip_cost_bps / 10_000.0)
            net = gross - cost
            res.matched_round_trips += 1
            res.gross_pnl_usdt += gross
            res.net_pnl_usdt += net
            res.cost_usdt += cost
            res.wins_gross += int(gross > 0)
            res.wins_net += int(net > 0)
            res.per_coin_net[coin] = round(res.per_coin_net.get(coin, 0.0) + net, 6)

    res.still_open = len(book)
    res.gross_pnl_usdt = round(res.gross_pnl_usdt, 4)
    res.net_pnl_usdt = round(res.net_pnl_usdt, 4)
    res.cost_usdt = round(res.cost_usdt, 4)
    return res


def load_ledger_rows(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


__all__ = ["ReplayConfig", "ReplayResult", "replay_ledger_v9", "load_ledger_rows"]
