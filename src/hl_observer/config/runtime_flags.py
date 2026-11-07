"""Q-007 — Source unique type-safe pour les flags runtime HYPERSMART_.

Toutes les lectures d'env vars HYPERSMART_ passent par ce module.
Les défauts sont alignés sur LANCER_HYPERSMART.cmd (capital 350 USDT).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(raw.strip()))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class SecurityInvariants:
    hl_env: str = "paper"
    mainnet_execution: bool = False
    testnet_execution: bool = False
    mode: str = "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"

    @property
    def paper_only(self) -> bool:
        return (
            self.hl_env == "paper"
            and not self.mainnet_execution
            and not self.testnet_execution
        )

    def assert_paper(self) -> None:
        if not self.paper_only:
            raise RuntimeError(
                f"PAPER invariant violated: HL_ENV={self.hl_env}, "
                f"mainnet={self.mainnet_execution}, testnet={self.testnet_execution}"
            )


@dataclass(frozen=True, slots=True)
class SizingFlags:
    capital_usd: float = 350.0
    leverage: int = 5
    max_total_exposure_usd: float = 100.0
    max_open_positions: int = 2
    max_position_usd: float = 50.0
    min_paper_notional_usd: float = 40.0
    max_net_directional_pct: float = 60.0
    max_coin_notional_pct: float = 60.0
    kelly_sizing_enabled: bool = True
    kelly_fraction: float = 0.25


@dataclass(frozen=True, slots=True)
class SignalFlags:
    max_signal_age_ms: int = 10_000
    reduce_max_signal_age_ms: int = 15_000
    min_edge_bps: float = 16.0
    min_liquidity_score: float = 0.55
    max_copy_degradation_bps: float = 24.0
    fusion_copy_min_wallets: int = 2
    cost_buffer_bps: float = 24.0


@dataclass(frozen=True, slots=True)
class ProtectionFlags:
    risk_gate_enabled: bool = True
    entry_gate_enabled: bool = True
    exit_engine_enabled: bool = True
    auto_unstuck_enabled: bool = True
    fair_value_veto: bool = True
    graded_halt: bool = True
    protections_v26: bool = True
    market_quality: bool = True
    halt_amber_loss_usd: float = 12.0
    halt_red_loss_usd: float = 25.0
    session_loss_guard_usd: float = 15.0
    session_hard_loss_usd: float = 25.0


def load_security() -> SecurityInvariants:
    return SecurityInvariants(
        hl_env=os.environ.get("HL_ENV", "paper").strip().lower(),
        mainnet_execution=_bool("HL_ENABLE_MAINNET_EXECUTION", False),
        testnet_execution=_bool("HL_ENABLE_TESTNET_EXECUTION", False),
        mode=os.environ.get("HYPERSMART_MODE", "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"),
    )


def load_sizing() -> SizingFlags:
    return SizingFlags(
        capital_usd=_float("HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT", 350.0),
        leverage=_int("HYPERSMART_SIMULATION_LEVERAGE", 5),
        max_total_exposure_usd=_float("HYPERSMART_MAX_TOTAL_EXPOSURE_USDT", 100.0),
        max_open_positions=_int("HYPERSMART_MAX_OPEN_POSITIONS", 2),
        max_position_usd=_float("HYPERSMART_MAX_POSITION_USDT", 50.0),
        min_paper_notional_usd=_float("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", 40.0),
        max_net_directional_pct=_float("HYPERSMART_MAX_NET_DIRECTIONAL_PCT", 60.0),
        max_coin_notional_pct=_float("HYPERSMART_MAX_COIN_NOTIONAL_PCT", 60.0),
        kelly_sizing_enabled=_bool("HYPERSMART_KELLY_SIZING_ENABLED", True),
        kelly_fraction=_float("HYPERSMART_V26_KELLY_FRACTION", 0.25),
    )


def load_signals() -> SignalFlags:
    return SignalFlags(
        max_signal_age_ms=_int("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", 10_000),
        reduce_max_signal_age_ms=_int("HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS", 15_000),
        min_edge_bps=_float("HYPERSMART_SIMULATION_MIN_EDGE_BPS", 16.0),
        min_liquidity_score=_float("HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", 0.55),
        max_copy_degradation_bps=_float("HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", 24.0),
        fusion_copy_min_wallets=_int("HYPERSMART_FUSION_COPY_MIN_WALLETS", 2),
        cost_buffer_bps=_float("HYPERSMART_FUSION_COPY_COST_BUFFER_BPS", 24.0),
    )


def load_protections() -> ProtectionFlags:
    return ProtectionFlags(
        risk_gate_enabled=_bool("HYPERSMART_RISK_GATE_ENABLED", True),
        entry_gate_enabled=_bool("HYPERSMART_ENTRY_GATE_ENABLED", True),
        exit_engine_enabled=_bool("HYPERSMART_EXIT_ENGINE_ENABLED", True),
        auto_unstuck_enabled=_bool("HYPERSMART_V26_AUTO_UNSTUCK", True),
        fair_value_veto=_bool("HYPERSMART_V26_FAIR_VALUE_VETO", True),
        graded_halt=_bool("HYPERSMART_V26_GRADED_HALT", True),
        protections_v26=_bool("HYPERSMART_V26_PROTECTIONS", True),
        market_quality=_bool("HYPERSMART_V26_MARKET_QUALITY", True),
        halt_amber_loss_usd=_float("HYPERSMART_V26_HALT_AMBER_LOSS_USD", 12.0),
        halt_red_loss_usd=_float("HYPERSMART_V26_HALT_RED_LOSS_USD", 25.0),
        session_loss_guard_usd=_float("HYPERSMART_SESSION_LOSS_GUARD_USDC", 15.0),
        session_hard_loss_usd=_float("HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC", 25.0),
    )


__all__ = [
    "SecurityInvariants",
    "SizingFlags",
    "SignalFlags",
    "ProtectionFlags",
    "load_security",
    "load_sizing",
    "load_signals",
    "load_protections",
]
