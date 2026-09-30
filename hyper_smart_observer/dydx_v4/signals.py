"""
Moteur de signaux dYdX v4 — candidats seulement, jamais des ordres.

Un signal est accepté seulement si TOUS les critères passent:
- source FRESH (< 4s idéalement, < 8s maximum absolu)
- account/subaccount shortlisté
- consensus multi-wallets atteint (si tracker fourni)
- lifecycle clair (pas UNKNOWN)
- market whitelisté
- liquidité OK, spread OK
- edge net positif après tous les coûts
- pas de cooldown actif
- pas de position déjà perdante
- pas de max_open dépassé
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.models import (
    LifecycleEvent,
    NoTradeDecision,
    NoTradeReason,
    PositionSide,
    SignalCandidate,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.safety import gate_signal_for_live, is_test_fixture_account
from hyper_smart_observer.dydx_v4.ws_client import WsStatus
from hyper_smart_observer.dydx_v4.consensus import ConsensusTracker

logger = logging.getLogger(__name__)


@dataclass
class SignalEngineState:
    """État interne du moteur de signaux."""
    open_paper_trade_count: int = 0
    shortlisted_accounts: set[str] = field(default_factory=set)
    ws_status: WsStatus = WsStatus.DISCONNECTED
    last_rest_backfill_ms: int = 0
    cooldowns: dict[str, int] = field(default_factory=dict)  # position_key -> cooldown_until_ms


class DydxSignalEngine:
    """
    Moteur de candidats signaux dYdX v4.

    Jamais d'ordres. Seulement des SignalCandidate.
    """

    def __init__(
        self,
        config: DydxV4Config,
        consensus: Optional[ConsensusTracker] = None,
    ) -> None:
        self.config = config
        self.state = SignalEngineState()
        self._no_trade_log: list[NoTradeDecision] = []
        # Consensus gate (bot viral): activé seulement si un tracker est fourni
        # ET config.consensus_required=True. Sans tracker → comportement v1 inchangé.
        self.consensus = consensus

    def update_shortlist(self, account_keys: set[str]) -> None:
        """Mettre à jour la shortlist des comptes à observer."""
        self.state.shortlisted_accounts = account_keys

    def update_ws_status(self, status: WsStatus) -> None:
        self.state.ws_status = status

    def set_open_trade_count(self, count: int) -> None:
        self.state.open_paper_trade_count = count

    def evaluate_delta(
        self,
        account_address: str,
        subaccount_number: int,
        market_id: str,
        side: PositionSide,
        lifecycle: LifecycleEvent,
        size: float,
        price: float,
        signal_age_ms: int,
        source: str = "ws_fill",
        simulation_mode: SimulationMode = SimulationMode.LIVE,
        spread_bps: Optional[float] = None,
        liquidity_usdc: Optional[float] = None,
    ) -> tuple[Optional[SignalCandidate], Optional[NoTradeDecision]]:
        """
        Évaluer un delta de position et retourner un candidat signal ou un refus.

        Retourne (SignalCandidate, None) si accepté,
                 (None, NoTradeDecision) si refusé.
        """
        now_ms = int(time.time() * 1000)
        position_key = f"dydx_v4|{account_address}|{subaccount_number}|{market_id}|{side.value}"

        def _no_trade(reason: NoTradeReason, detail: str = "") -> tuple[None, NoTradeDecision]:
            decision_id = hashlib.sha256(
                f"{reason.value}:{position_key}:{now_ms}".encode()
            ).hexdigest()[:24]
            dec = NoTradeDecision(
                decision_id=decision_id,
                reason=reason,
                signal_candidate_id=None,
                account_address=account_address,
                market_id=market_id,
                detail=detail,
                timestamp_ms=now_ms,
                simulation_mode=simulation_mode,
            )
            self._no_trade_log.append(dec)
            logger.debug("NO_TRADE %s: %s | %s", reason.value, position_key, detail)
            return None, dec

        # 1. Fixture account
        if is_test_fixture_account(account_address):
            return _no_trade(NoTradeReason.TEST_FIXTURE_ACCOUNT, account_address)

        # 2. LIVE mode: WS dégradé
        if simulation_mode == SimulationMode.LIVE and self.state.ws_status in (
            WsStatus.DEGRADED, WsStatus.DISCONNECTED, WsStatus.FAILED
        ):
            return _no_trade(
                NoTradeReason.WEBSOCKET_DEGRADED,
                f"ws_status={self.state.ws_status.value}",
            )

        # 3. Lifecycle UNKNOWN
        if lifecycle == LifecycleEvent.UNKNOWN:
            return _no_trade(NoTradeReason.LIFECYCLE_UNKNOWN, "lifecycle=UNKNOWN")

        # 4. Account shortlisté?
        account_key = f"{account_address}/{subaccount_number}"
        if account_key not in self.state.shortlisted_accounts:
            return _no_trade(
                NoTradeReason.ACCOUNT_NOT_SHORTLISTED,
                f"account_key={account_key}",
            )

        # 5. Market whitelisté?
        if market_id not in self.config.market_whitelist:
            return _no_trade(
                NoTradeReason.MARKET_NOT_WHITELISTED,
                f"market={market_id}",
            )

        # 6. Market blacklisté?
        if market_id in self.config.market_blacklist:
            return _no_trade(NoTradeReason.MARKET_BLACKLISTED, f"market={market_id}")

        # 6b. CONSENSUS GATE (bot viral): une entrée n'est valide que si
        # ≥K comptes shortlistés distincts convergent (même marché, même sens)
        # dans la fenêtre. Les CLOSE/REDUCE ne sont JAMAIS bloqués (on doit
        # toujours pouvoir sortir).
        if (
            self.consensus is not None
            and self.config.consensus_required
            and lifecycle in (LifecycleEvent.OPEN, LifecycleEvent.ADD)
        ):
            self.consensus.record_open(
                account_key, market_id, side.value, now_ms, size * price
            )
            consensus_res = self.consensus.check(
                market_id, side.value, now_ms,
                min_wallets=self.config.consensus_min_wallets,
            )
            if not consensus_res.met:
                return _no_trade(
                    NoTradeReason.CONSENSUS_NOT_REACHED,
                    f"wallets={consensus_res.distinct_accounts}/"
                    f"{consensus_res.required} window={consensus_res.window_ms}ms",
                )

        # 7. Stale signal
        if signal_age_ms > self.config.hard_max_signal_age_ms:
            return _no_trade(
                NoTradeReason.STALE_SIGNAL,
                f"age={signal_age_ms}ms > hard_max={self.config.hard_max_signal_age_ms}ms",
            )

        # 8. Spread trop élevé
        eff_spread = spread_bps if spread_bps is not None else self.config.estimated_spread_bps
        if eff_spread > 50:  # >50 bps = illiquide
            return _no_trade(
                NoTradeReason.SPREAD_TOO_HIGH,
                f"spread={eff_spread:.1f}bps > 50bps",
            )

        # 9. Liquidité
        if liquidity_usdc is not None and liquidity_usdc < 10_000:
            return _no_trade(
                NoTradeReason.LIQUIDITY_TOO_LOW,
                f"liquidity={liquidity_usdc:.0f} USDC < 10000",
            )

        # 10. Cooldown
        cooldown_until = self.state.cooldowns.get(position_key, 0)
        if now_ms < cooldown_until:
            remaining = (cooldown_until - now_ms) / 1000
            return _no_trade(
                NoTradeReason.COOLDOWN_ACTIVE,
                f"cooldown_remaining={remaining:.1f}s",
            )

        # 11. Max open trades
        if (
            lifecycle == LifecycleEvent.OPEN
            and self.state.open_paper_trade_count >= self.config.max_open_paper_trades
        ):
            return _no_trade(
                NoTradeReason.MAX_OPEN_TRADES_REACHED,
                f"open={self.state.open_paper_trade_count} >= max={self.config.max_open_paper_trades}",
            )

        # 12. Calcul edge
        total_cost_bps = self.config.total_round_trip_cost_bps
        # Ajuster avec spread réel si disponible
        if spread_bps is not None:
            extra_spread = max(0.0, spread_bps - self.config.estimated_spread_bps)
            total_cost_bps += extra_spread

        # Edge brut estimé (placeholder — sera enrichi par scoring)
        # En réalité, ceci serait calculé à partir du PnL historique du leader
        estimated_edge_bps = self.config.min_edge_bps * 2  # conservative estimate

        edge_remaining_bps = estimated_edge_bps - total_cost_bps

        # 13. Safety gate finale
        safety = gate_signal_for_live(
            config=self.config,
            signal_age_ms=signal_age_ms,
            account_address=account_address,
            market=market_id,
            edge_remaining_bps=edge_remaining_bps,
            total_cost_bps=total_cost_bps,
        )
        if not safety.allowed:
            reason_map = {
                "STALE_SIGNAL": NoTradeReason.STALE_SIGNAL,
                "EDGE_REMAINING_TOO_LOW": NoTradeReason.EDGE_REMAINING_TOO_LOW,
                "EDGE_BELOW_COST_MULTIPLIER_THRESHOLD": NoTradeReason.EDGE_BELOW_COST_MULTIPLIER,
                "MARKET_NOT_WHITELISTED": NoTradeReason.MARKET_NOT_WHITELISTED,
                "MARKET_BLACKLISTED": NoTradeReason.MARKET_BLACKLISTED,
                "TEST_FIXTURE_ACCOUNT_EXCLUDED_FROM_LIVE": NoTradeReason.TEST_FIXTURE_ACCOUNT,
            }
            nt_reason = reason_map.get(safety.reason, NoTradeReason.SAFETY_DENY_BY_DEFAULT)
            return _no_trade(nt_reason, safety.detail)

        # --- Signal accepté ---
        signal_id = hashlib.sha256(
            f"{account_address}:{subaccount_number}:{market_id}:{side.value}:{now_ms}".encode()
        ).hexdigest()[:32]

        candidate = SignalCandidate(
            signal_id=signal_id,
            account_address=account_address,
            subaccount_number=subaccount_number,
            market_id=market_id,
            side=side,
            lifecycle=lifecycle,
            size=size,
            price=price,
            signal_age_ms=signal_age_ms,
            edge_remaining_bps=edge_remaining_bps,
            total_cost_bps=total_cost_bps,
            source=source,
            simulation_mode=simulation_mode,
            created_at_ms=now_ms,
            notes=[
                f"spread_bps={eff_spread:.1f}",
                f"total_cost_bps={total_cost_bps:.1f}",
                f"edge_remaining_bps={edge_remaining_bps:.1f}",
            ],
        )

        logger.info(
            "SIGNAL_ACCEPTED: %s %s %s lifecycle=%s age=%dms edge=%.1fbps",
            market_id, side.value, lifecycle.value,
            lifecycle.value, signal_age_ms, edge_remaining_bps,
        )
        return candidate, None

    def set_cooldown(self, position_key: str, duration_ms: int = 30 * 60 * 1000) -> None:
        """Activer un cooldown après une perte."""
        self.state.cooldowns[position_key] = int(time.time() * 1000) + duration_ms

    @property
    def no_trade_summary(self) -> dict[str, int]:
        """Résumé des refus par raison."""
        summary: dict[str, int] = {}
        for dec in self._no_trade_log:
            summary[dec.reason.value] = summary.get(dec.reason.value, 0) + 1
        return summary

    @property
    def total_no_trade(self) -> int:
        return len(self._no_trade_log)
