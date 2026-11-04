"""Contrat immuable du protocole d'exécution Copy-Vault.

Ce module regroupe uniquement les constantes et les règles d'identité connues
avant le replay. Il évite de mélanger le contrat causal avec le moteur de
simulation et conserve une seule source de vérité pour le collecteur et les
tests.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.instrument_identity import preserve_native_instrument_symbol

PROTOCOL_NAME = "copy_vault_executable_walk_forward_v8_explicit_l2_gap_identity"
UNBOUND_L2_SOURCE_PROTOCOL = "copy_vault_unbound_ws_l2_v1"
INSTRUMENT_IDENTITY_SCHEMA = "hyperliquid_native_instrument_identity.v1"
CHECKPOINT_WRITER_STATE_SCHEMA = "hypersmart.copy_vault_checkpoint_tail.v3"
CHECKPOINT_INTEGRITY_SCHEMA = "hypersmart.copy_vault_checkpoint_integrity.v1"
TRAIN_ECONOMIC_GATE_VERSION = "copy_vault_train_economic_gate_v2"
EXECUTION_PRICING_POLICY = "observed_side_specific_l2_vwap_full_size_v1"
MIN_COMPLETE_PROOF_DAYS = 2
POST_FREEZE_PROOF_POLICY = "FIRST_TWO_COMPLETE_UTC_DAYS_AFTER_FREEZE_V1"
CHECKPOINT_COLLECTOR_PROTOCOL = (
    f"copy_vault_checkpoint_companion_v3_native_symbol_identity_for_{PROTOCOL_NAME}"
)
METAORDER_GAP_MS = 60_000
COPY_DELAY_MS = 60_000
MAX_REFERENCE_LAG_MS = 30_000
MAX_TARGET_LAG_MS = 30_000
HORIZONS_MS = (300_000, 900_000, 1_800_000, 3_600_000)
MAX_OPEN_POSITIONS = 6
PAPER_EQUITY_USD = 200.0
PAPER_LEVERAGE = 1.0
MAX_GROSS_EXPOSURE_USD = PAPER_EQUITY_USD * PAPER_LEVERAGE
PAPER_TARGET_NET_USD_PER_DAY = 5.0
PAPER_EXECUTION_STYLE = "maker"
PAPER_FEE_POLICY = "EXPLICIT_VENUE_SNAPSHOT_REQUIRED"
PAPER_L2_FRESHNESS_MS = 90_000
# Runtime paper sizing is intentionally distinct from the replay contract's
# unlevered diagnostic profile.  It is still bounded and never enables real execution.
RUNTIME_PAPER_LEVERAGE = 10.0
RUNTIME_PAPER_MAX_POSITION_USD = 50.0
RUNTIME_PAPER_MAX_TOTAL_EXPOSURE_USD = 100.0
RUNTIME_PAPER_MAX_OPEN_POSITIONS = 20
DIAGNOSTIC_NOTIONAL_USD = 150.0
NOTIONAL_USD = min(DIAGNOSTIC_NOTIONAL_USD, MAX_GROSS_EXPOSURE_USD)
MIN_TRAIN_TRADES = 8
TRAIN_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
COPYABLE_ENTRY_ACTIONS = frozenset({"OPEN", "ADD"})
_OPEN_DIRECTION_BY_LABEL = {
    "open long": 1,
    "open short": -1,
}


@dataclass(frozen=True, slots=True)
class CopyVaultPaperProfile:
    """Single explicit paper contract shared by replay, lab and reporting.

    The profile is descriptive only.  It never authorizes an order or creates a
    missing observation; an absent fee, book or timestamp remains unmeasurable.
    """

    capital_usd: float = PAPER_EQUITY_USD
    leverage: float = PAPER_LEVERAGE
    target_net_usd_per_day: float = PAPER_TARGET_NET_USD_PER_DAY
    execution_style: str = PAPER_EXECUTION_STYLE
    fee_policy: str = PAPER_FEE_POLICY
    l2_freshness_ms: int = PAPER_L2_FRESHNESS_MS

    @property
    def max_gross_exposure_usd(self) -> float:
        return self.capital_usd * self.leverage

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital_usd": self.capital_usd,
            "leverage": self.leverage,
            "target_net_usd_per_day": self.target_net_usd_per_day,
            "execution_style": self.execution_style,
            "fee_policy": self.fee_policy,
            "l2_freshness_ms": self.l2_freshness_ms,
            "max_gross_exposure_usd": self.max_gross_exposure_usd,
            "paper_only": True,
            "real_execution": False,
        }


def paper_profile() -> CopyVaultPaperProfile:
    """Return the immutable Copy-Vault paper profile used by all local paths."""

    return CopyVaultPaperProfile()


def canonical_copy_vault_coin(value: Any) -> str:
    """Preserve the venue-native, case-sensitive Hyperliquid instrument name."""

    return preserve_native_instrument_symbol(value)


def expected_open_direction(row: Mapping[str, Any]) -> int | None:
    """Retourne le sens signé uniquement pour un open leader explicite."""

    label = " ".join(str(row.get("dir") or "").strip().casefold().split())
    return _OPEN_DIRECTION_BY_LABEL.get(label)


def canonical_metaorder_id(
    *, vault: str, coin: str, direction: int, signal_ts_ms: int, first_event_id: str
) -> str:
    """Construit l'identité immuable depuis les faits du premier slice observé."""

    if type(direction) is not int or direction not in (-1, 1):
        raise ValueError("direction must be the exact integer -1 or 1")
    if type(signal_ts_ms) is not int or signal_ts_ms <= 0:
        raise ValueError("signal_ts_ms must be an exact positive integer")

    material = {
        "vault": str(vault or "").lower(),
        "coin": canonical_copy_vault_coin(coin),
        "direction": direction,
        "signal_ts_ms": signal_ts_ms,
        "first_event_id": str(first_event_id or ""),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def classify_live_entry_action(row: Mapping[str, Any]) -> str | None:
    """Classe un open explicite à partir de la position de départ exchange."""

    direction = expected_open_direction(row)
    if direction is None:
        return None
    raw_start = row.get("start_position", row.get("startPosition"))
    if isinstance(raw_start, bool):
        return None
    try:
        start = float(raw_start)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(start):
        return None
    if abs(start) <= 1e-12:
        return "OPEN"
    if (start > 0 and direction > 0) or (start < 0 and direction < 0):
        return "ADD"
    return None


def protocol_signature() -> dict[str, Any]:
    economic = build_copy_vault_contract(
        notional_usd=NOTIONAL_USD,
        copy_delay_ms=COPY_DELAY_MS,
        max_reference_lag_ms=MAX_REFERENCE_LAG_MS,
        max_target_lag_ms=MAX_TARGET_LAG_MS,
    )
    return {
        "calibration_protocol": PROTOCOL_NAME,
        "unbound_l2_source_protocol": UNBOUND_L2_SOURCE_PROTOCOL,
        "train_economic_gate": TRAIN_ECONOMIC_GATE_VERSION,
        "execution_pricing_policy": EXECUTION_PRICING_POLICY,
        "minimum_complete_proof_days": MIN_COMPLETE_PROOF_DAYS,
        "post_freeze_proof_policy": POST_FREEZE_PROOF_POLICY,
        "checkpoint_collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
        "checkpoint_writer_state_schema": CHECKPOINT_WRITER_STATE_SCHEMA,
        "checkpoint_integrity_schema": CHECKPOINT_INTEGRITY_SCHEMA,
        "metaorder_identity_policy": "immutable_first_observed_fill",
        "checkpoint_binding_policy": "exact_metaorder_stage_and_protocol",
        "metaorder_gap_ms": METAORDER_GAP_MS,
        "copy_delay_ms": COPY_DELAY_MS,
        "max_reference_lag_ms": MAX_REFERENCE_LAG_MS,
        "max_target_lag_ms": MAX_TARGET_LAG_MS,
        "horizons_ms": list(HORIZONS_MS),
        "diagnostic_notional_usd": DIAGNOSTIC_NOTIONAL_USD,
        "notional_usd": NOTIONAL_USD,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "paper_equity_usd": PAPER_EQUITY_USD,
        "paper_leverage": PAPER_LEVERAGE,
        "max_gross_exposure_usd": MAX_GROSS_EXPOSURE_USD,
        "paper_profile": paper_profile().as_dict(),
        "runtime_paper_profile": {
            "leverage": RUNTIME_PAPER_LEVERAGE,
            "max_position_usd": RUNTIME_PAPER_MAX_POSITION_USD,
            "max_total_exposure_usd": RUNTIME_PAPER_MAX_TOTAL_EXPOSURE_USD,
            "max_open_positions": RUNTIME_PAPER_MAX_OPEN_POSITIONS,
            "paper_only": True,
            "real_execution": False,
        },
        "capital_margin_policy": "gross_notional_leq_paper_equity_times_leverage_v1",
        "fee_source": "hl_observer.economics.families:build_copy_vault_contract",
        "economic_contract": economic.receipt(),
        "assumption_snapshot_hash": economic.registry.snapshot_hash(),
        "book_source": (
            "runtime/data/copy_vault_l2_tape.jsonl:"
            "HYPERLIQUID_L2_WS_or_INFO_L2BOOK_causal"
        ),
        "fill_source": "LIVE_WS_non_snapshot_with_receive_time_for_all_protocol_segments",
        "historical_source_policy": "REST_BACKFILL_and_historical_books_audit_only",
        "causal_observation_required_all_segments": True,
        "causal_book_gap_identity_policy": (
            "same_connection_and_explicit_gap_epoch_required_for_causal_stream_triplets_v1"
        ),
        "forward_signal_policy": "causal_live_first_fill_observed_after_physical_freeze",
        "purge_policy": "copy_delay_plus_candidate_horizon_plus_max_target_lag",
    }


def same_timestamp_direction_receipt(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Preserve native event order for opposing fills at equal timestamps."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        timestamp = row.get("ts_ms", row.get("timestamp_ms"))
        event_id = str(row.get("event_id", row.get("fill_id", ""))).strip()
        direction = str(row.get("direction", row.get("side", ""))).strip().upper()
        if type(timestamp) is not int or timestamp <= 0 or not event_id or direction not in {"BUY", "SELL", "LONG", "SHORT"}:
            return {"status": "UNMEASURABLE", "reason": "fill_identity_timestamp_or_direction_invalid"}
        normalized.append({"ts_ms": timestamp, "event_id": event_id, "direction": direction})
    if len({row["event_id"] for row in normalized}) != len(normalized):
        return {"status": "UNMEASURABLE", "reason": "duplicate_fill_id"}
    ordered = sorted(normalized, key=lambda row: (row["ts_ms"], row["event_id"]))
    return {
        "status": "PROVEN",
        "ordered_fills": tuple((row["event_id"], row["direction"]) for row in ordered),
        "same_timestamp_tie_break": "native_event_id_lexicographic",
        "opposing_directions_preserved": len({row["direction"] for row in ordered}) > 1,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "CHECKPOINT_COLLECTOR_PROTOCOL",
    "CHECKPOINT_INTEGRITY_SCHEMA",
    "CHECKPOINT_WRITER_STATE_SCHEMA",
    "COPYABLE_ENTRY_ACTIONS",
    "COPY_DELAY_MS",
    "DIAGNOSTIC_NOTIONAL_USD",
    "EXECUTION_PRICING_POLICY",
    "HORIZONS_MS",
    "MAX_OPEN_POSITIONS",
    "MAX_REFERENCE_LAG_MS",
    "MAX_TARGET_LAG_MS",
    "METAORDER_GAP_MS",
    "MIN_COMPLETE_PROOF_DAYS",
    "MIN_TRAIN_TRADES",
    "NOTIONAL_USD", "PAPER_EQUITY_USD", "PAPER_LEVERAGE", "MAX_GROSS_EXPOSURE_USD",
    "PAPER_TARGET_NET_USD_PER_DAY", "PAPER_EXECUTION_STYLE", "PAPER_FEE_POLICY",
    "PAPER_L2_FRESHNESS_MS", "CopyVaultPaperProfile", "paper_profile",
    "RUNTIME_PAPER_LEVERAGE", "RUNTIME_PAPER_MAX_POSITION_USD",
    "RUNTIME_PAPER_MAX_TOTAL_EXPOSURE_USD", "RUNTIME_PAPER_MAX_OPEN_POSITIONS",
    "PROTOCOL_NAME",
    "POST_FREEZE_PROOF_POLICY",
    "TRAIN_ECONOMIC_GATE_VERSION",
    "TRAIN_FRACTION",
    "UNBOUND_L2_SOURCE_PROTOCOL",
    "VALIDATION_FRACTION",
    "canonical_metaorder_id",
    "classify_live_entry_action",
    "expected_open_direction",
    "same_timestamp_direction_receipt",
    "protocol_signature",
]
