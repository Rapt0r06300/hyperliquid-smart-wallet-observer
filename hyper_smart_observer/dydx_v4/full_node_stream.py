"""
Ingéreur Full Node gRPC Streaming dYdX v4 — le VRAI firehose, READ-ONLY / PAPER.

Pourquoi : l'Indexer public ne donne que des trades anonymisés (sans adresse) ou
des flux par-wallet (qu'il faut connaître à l'avance). Pour « scrapper TOUS les
événements de TOUS les wallets en temps réel avec l'adresse », dYdX expose le
**Full Node gRPC Streaming** : service `dydxprotocol.clob.Query/StreamOrderbookUpdates`.

Clé : en s'abonnant à TOUS les `clob_pair_id`, chaque message `StreamOrderbookFill`
contient les `orders` impliqués, et chaque order porte
`order_id.subaccount_id.owner` → **l'adresse du wallet**. On récupère donc tous les
fills de tous les wallets, avec adresse, en < 1 bloc. C'est la découverte + le
signal frais, sans polling.

Prérequis (côté infra, à toi) : un full node dYdX lancé avec
`--grpc-streaming-enabled=true` (voir docs/migration/DYDX_FULL_NODE_STREAMING_RUNBOOK.md).

Ce module : parsing PUR (testable) + client gRPC fin (dépend de `grpcio` + `v4-proto`,
import-gardé). Aucune méthode d'ordre/signature. Un fill n'est jamais un ordre.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# exec_mode des fills confirmés par consensus (DeliverTx). Voir doc dYdX.
EXEC_MODE_FINALIZE = 7


@dataclass
class StreamedFill:
    """Fill normalisé issu du full node stream (avec adresse du wallet)."""
    owner: str               # adresse dydx1… du wallet
    subaccount_number: int
    clob_pair_id: Optional[int]
    market: Optional[str]
    side: str                # "BUY" | "SELL"
    subticks: Optional[int]  # prix encodé (à convertir avec le tick du marché)
    cum_fill_quantums: Optional[int]
    block_height: Optional[int] = None


def _first(d: dict, *keys):
    """Récupérer la première clé présente (gère camelCase et snake_case)."""
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def _norm_side(value) -> str:
    """Normaliser le côté: 1/SIDE_BUY/BUY → BUY ; 2/SIDE_SELL/SELL → SELL."""
    if value in (1, "1", "SIDE_BUY", "BUY", "buy"):
        return "BUY"
    if value in (2, "2", "SIDE_SELL", "SELL", "sell"):
        return "SELL"
    return str(value or "").upper()


def parse_stream_fill(
    fill: dict,
    clob_to_market: Optional[dict] = None,
    block_height: Optional[int] = None,
) -> list[StreamedFill]:
    """
    Extraire les fills par-wallet d'un `StreamOrderbookFill` (déjà décodé en dict,
    p.ex. via MessageToDict du proto, ou JSON du flux WebSocket).

    Chaque `orders[i]` est zippé avec `fill_amounts[i]` (quantité cumulée remplie).
    On ne garde que les orders avec une adresse `owner` exploitable.
    """
    clob_to_market = clob_to_market or {}
    orders = _first(fill, "orders") or []
    fill_amounts = _first(fill, "fillAmounts", "fill_amounts") or []
    out: list[StreamedFill] = []
    if not isinstance(orders, list):
        return out
    for i, order in enumerate(orders):
        if not isinstance(order, dict):
            continue
        oid = _first(order, "orderId", "order_id") or {}
        sub = _first(oid, "subaccountId", "subaccount_id") or {}
        owner = _first(sub, "owner")
        if not isinstance(owner, str) or not owner:
            continue
        try:
            number = int(_first(sub, "number") or 0)
        except (TypeError, ValueError):
            number = 0
        clob_raw = _first(oid, "clobPairId", "clob_pair_id")
        try:
            clob = int(clob_raw) if clob_raw is not None else None
        except (TypeError, ValueError):
            clob = None
        market = clob_to_market.get(clob) if clob is not None else None
        side = _norm_side(_first(order, "side"))
        subticks_raw = _first(order, "subticks")
        try:
            subticks = int(subticks_raw) if subticks_raw is not None else None
        except (TypeError, ValueError):
            subticks = None
        amt = None
        if i < len(fill_amounts):
            try:
                amt = int(fill_amounts[i])
            except (TypeError, ValueError):
                amt = None
        out.append(StreamedFill(
            owner=owner, subaccount_number=number, clob_pair_id=clob, market=market,
            side=side, subticks=subticks, cum_fill_quantums=amt, block_height=block_height,
        ))
    return out


def parse_stream_response(
    response: dict,
    clob_to_market: Optional[dict] = None,
    only_finalized: bool = True,
) -> list[StreamedFill]:
    """
    Parser un `StreamOrderbookUpdatesResponse` (dict) → liste de StreamedFill.

    On ne garde que les `order_fill` (les autres updates concernent le carnet) et,
    si `only_finalized`, uniquement les fills confirmés (exec_mode == 7).
    """
    clob_to_market = clob_to_market or {}
    updates = _first(response, "updates") or []
    out: list[StreamedFill] = []
    if not isinstance(updates, list):
        return out
    for upd in updates:
        if not isinstance(upd, dict):
            continue
        exec_mode = _first(upd, "execMode", "exec_mode")
        if only_finalized and exec_mode not in (EXEC_MODE_FINALIZE, str(EXEC_MODE_FINALIZE)):
            continue
        block_height = _first(upd, "blockHeight", "block_height")
        order_fill = _first(upd, "orderFill", "order_fill")
        if not isinstance(order_fill, dict):
            continue
        out.extend(parse_stream_fill(order_fill, clob_to_market, block_height))
    return out


class FullNodeStreamClient:
    """
    Client gRPC fin vers le full node streaming. READ-ONLY.

    Nécessite `grpcio` + le package `v4-proto`. Import-gardé : si absent, le client
    log et reste inactif (le moteur retombe sur l'Indexer). À brancher sur un node
    avec `--grpc-streaming-enabled` (cf. runbook).
    """

    def __init__(
        self,
        endpoint: str,
        clob_pair_ids: list[int],
        on_fill: Callable[[StreamedFill], None],
        clob_to_market: Optional[dict] = None,
        only_finalized: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.clob_pair_ids = list(clob_pair_ids)
        self.on_fill = on_fill
        self.clob_to_market = clob_to_market or {}
        self.only_finalized = only_finalized
        self._stop = False

    def run_forever(self) -> None:  # pragma: no cover - dépend de l'infra node
        """Boucle de consommation gRPC (bloquante). À lancer dans un thread."""
        try:
            import grpc  # noqa: F401
            from google.protobuf.json_format import MessageToDict
            from v4_proto.dydxprotocol.clob import query_pb2, query_pb2_grpc
            from v4_proto.dydxprotocol.subaccounts import subaccount_pb2
        except Exception as e:
            logger.error(
                "Full node stream indisponible: installer grpcio + v4-proto, et "
                "lancer un node avec --grpc-streaming-enabled. Détail: %s", e
            )
            return

        while not self._stop:
            try:
                channel = grpc.insecure_channel(self.endpoint)
                stub = query_pb2_grpc.QueryStub(channel)
                request = query_pb2.StreamOrderbookUpdatesRequest(
                    clob_pair_id=self.clob_pair_ids,
                    subaccount_ids=[],  # fills de TOUS les wallets via les clob pairs
                )
                logger.info("Full node stream connecté: %s (clob_pairs=%d)",
                            self.endpoint, len(self.clob_pair_ids))
                for response in stub.StreamOrderbookUpdates(request):
                    if self._stop:
                        break
                    resp_dict = MessageToDict(response, preserving_proto_field_name=False)
                    for f in parse_stream_response(resp_dict, self.clob_to_market, self.only_finalized):
                        try:
                            self.on_fill(f)
                        except Exception as cb_err:
                            logger.debug("on_fill error: %s", cb_err)
            except Exception as e:
                logger.warning("Full node stream interrompu (%s), reconnexion…", e)
                import time as _t
                _t.sleep(3.0)

    def stop(self) -> None:
        self._stop = True


__all__ = [
    "EXEC_MODE_FINALIZE",
    "StreamedFill",
    "parse_stream_fill",
    "parse_stream_response",
    "FullNodeStreamClient",
]
