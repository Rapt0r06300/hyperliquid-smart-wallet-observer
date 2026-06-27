"""
Intégration du scan rapide pour DydxLiveObserver — opt-in, READ-ONLY / PAPER.

Relie `WalletHarvester` (découverte multi-sources) + `FastScanner` (WS temps réel)
au live observer, derrière le flag `DYDX_FAST_SCANNER`.

Apport quand activé :
- abonne en WebSocket les wallets shortlistés ;
- désabonne les wallets évincés si le client WS le supporte ;
- détecte en < 1 s quels wallets viennent de trader ;
- expose `wallets_that_just_moved()` ;
- expose les diagnostics WS pour savoir si le flux est réellement vivant.

SÉCURITÉ : aucune méthode d'ordre/signature/dépôt. Lecture, abonnement,
agrégation. Un fill n'est jamais un ordre.
"""

from __future__ import annotations

import logging
from types import MethodType
from typing import Optional

from hyper_smart_observer.dydx_v4.fast_scanner import DEFAULT_MAX_AGE_MS, FastScanner
from hyper_smart_observer.dydx_v4.wallet_harvester import WalletHarvester

logger = logging.getLogger(__name__)


class FastScanIntegration:
    """Orchestre harvester + scanner pour le live observer (opt-in)."""

    def __init__(
        self,
        ws_client=None,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        hot_capacity: int = 500,
        harvester: Optional[WalletHarvester] = None,
    ) -> None:
        self.scanner = FastScanner(
            ws_client=ws_client, max_age_ms=max_age_ms, hot_capacity=hot_capacity
        )
        self.harvester = harvester or WalletHarvester(max_track=hot_capacity)
        self._ws = ws_client
        self._cosmos_enabled = False
        self._wire_unsubscribe()
        if ws_client is not None:
            try:
                ws_client._on_message_cb = self.note_ws_message
            except Exception as e:  # pragma: no cover - dépend de l'impl WS
                logger.debug("hook WS échec (ignoré): %s", e)

    def _wire_unsubscribe(self) -> None:
        """Brancher l'unsubscribe réel si le client WS le supporte."""
        ws = self._ws
        if ws is None or not hasattr(ws, "unsubscribe_subaccount"):
            return

        def _unsubscribe(scanner_self, address: str) -> None:
            try:
                ws.unsubscribe_subaccount(address, 0)
            except Exception as e:  # pragma: no cover - dépend réseau
                logger.debug("unsubscribe %s échec: %s", address[:12], e)

        self.scanner._unsubscribe = MethodType(_unsubscribe, self.scanner)

    def note_ws_message(self, msg) -> None:
        """Pousser un message WS dans le scanner."""
        try:
            self.scanner.handle_ws_message(msg)
        except Exception as e:  # pragma: no cover
            logger.debug("note_ws_message: %s", e)

    def track_shortlist(self, shortlist) -> int:
        """
        Abonner en WS les wallets shortlistés. Accepte des objets type WalletScore.
        Retourne le nombre de wallets soumis au hot-set.
        """
        pairs: list[tuple[str, float]] = []
        for w in shortlist or []:
            addr = getattr(w, "address", None)
            if not isinstance(addr, str) or not addr:
                continue
            score = getattr(w, "total_score", 0.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            pairs.append((addr, score))
        if pairs:
            self.scanner.track_wallets(pairs)
        return len(pairs)

    def track_harvester_top(self, n: Optional[int] = None) -> int:
        """Abonner en WS le top du harvester."""
        pairs = self.harvester.top_for_scanner(n=n)
        if pairs:
            self.scanner.track_wallets(pairs)
        return len(pairs)

    def enable_cosmos_discovery(self, cosmos_client, **scan_kwargs) -> None:
        """Brancher la source on-chain Cosmos sur le harvester. READ-ONLY."""
        if self._cosmos_enabled:
            return
        try:
            self.harvester.add_cosmos_source(cosmos_client, **scan_kwargs)
            self._cosmos_enabled = True
            logger.info("fast_scan: source on-chain Cosmos branchée (READ-ONLY)")
        except Exception as e:  # pragma: no cover
            logger.warning("enable_cosmos_discovery échec (ignoré): %s", e)

    def refresh_discovery(self, n: Optional[int] = None) -> int:
        """Découverte toutes sources puis abonnement du top en WS."""
        try:
            new = self.harvester.harvest_once()
            self.track_harvester_top(n=n)
            return new
        except Exception as e:  # pragma: no cover
            logger.debug("refresh_discovery: %s", e)
            return 0

    def wallets_that_just_moved(self, limit: int = 1000) -> set[str]:
        """Adresses uniques ayant produit un fill frais depuis le dernier appel."""
        moved: set[str] = set()
        for fill in self.scanner.drain_fresh(limit=limit):
            moved.add(fill.address)
        return moved

    def stats(self) -> dict:
        s = self.scanner.stats()
        s["harvested_addresses"] = len(self.harvester.index)
        s["ws_attached"] = self._ws is not None
        s["ws_unsubscribe_wired"] = bool(
            self._ws is not None and hasattr(self._ws, "unsubscribe_subaccount")
        )
        if self._ws is not None:
            try:
                diag = self._ws.diagnostics()
                s["ws"] = diag.to_dict() if hasattr(diag, "to_dict") else diag
            except Exception as e:
                s["ws"] = {"diagnostics_error": str(e), "read_only": True, "paper_only": True}
        return s


__all__ = ["FastScanIntegration"]
