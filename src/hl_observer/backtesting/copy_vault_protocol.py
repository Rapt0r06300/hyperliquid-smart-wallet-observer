"""Contrat immuable du protocole d'exécution Copy-Vault.

Ce module regroupe uniquement les constantes et les règles d'identité connues
avant le replay. Il évite de mélanger le contrat causal avec le moteur de
simulation et conserve une seule source de vérité pour le collecteur et les
tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

PROTOCOL_NAME = "copy_vault_executable_walk_forward_v7_exact_checkpoint_binding"
TRAIN_ECONOMIC_GATE_VERSION = "copy_vault_train_economic_gate_v2"
CHECKPOINT_COLLECTOR_PROTOCOL = (
    f"copy_vault_checkpoint_companion_v2_for_{PROTOCOL_NAME}"
)
METAORDER_GAP_MS = 60_000
COPY_DELAY_MS = 60_000
MAX_REFERENCE_LAG_MS = 30_000
MAX_TARGET_LAG_MS = 30_000
HORIZONS_MS = (300_000, 900_000, 1_800_000, 3_600_000)
NOTIONAL_USD = 150.0
MAX_OPEN_POSITIONS = 6
MIN_TRAIN_TRADES = 8
TRAIN_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
COPYABLE_ENTRY_ACTIONS = frozenset({"OPEN", "ADD"})
_OPEN_DIRECTION_BY_LABEL = {
    "open long": 1,
    "open short": -1,
}


def expected_open_direction(row: Mapping[str, Any]) -> int | None:
    """Retourne le sens signé uniquement pour un open leader explicite."""

    label = " ".join(str(row.get("dir") or "").strip().casefold().split())
    return _OPEN_DIRECTION_BY_LABEL.get(label)


def canonical_metaorder_id(
    *, vault: str, coin: str, direction: int, signal_ts_ms: int, first_event_id: str
) -> str:
    """Construit l'identité immuable depuis les faits du premier slice observé."""

    material = {
        "vault": str(vault or "").lower(),
        "coin": str(coin or "").upper(),
        "direction": int(direction),
        "signal_ts_ms": int(signal_ts_ms),
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
    try:
        start = float(raw_start)
    except (TypeError, ValueError, OverflowError):
        return None
    if abs(start) <= 1e-12:
        return "OPEN"
    if (start > 0 and direction > 0) or (start < 0 and direction < 0):
        return "ADD"
    return None


def protocol_signature() -> dict[str, Any]:
    return {
        "calibration_protocol": PROTOCOL_NAME,
        "train_economic_gate": TRAIN_ECONOMIC_GATE_VERSION,
        "checkpoint_collector_protocol": CHECKPOINT_COLLECTOR_PROTOCOL,
        "metaorder_identity_policy": "immutable_first_observed_fill",
        "checkpoint_binding_policy": "exact_metaorder_stage_and_protocol",
        "metaorder_gap_ms": METAORDER_GAP_MS,
        "copy_delay_ms": COPY_DELAY_MS,
        "max_reference_lag_ms": MAX_REFERENCE_LAG_MS,
        "max_target_lag_ms": MAX_TARGET_LAG_MS,
        "horizons_ms": list(HORIZONS_MS),
        "notional_usd": NOTIONAL_USD,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "fee_source": "hl_observer.config.frais_venues:frais_taker_bps(HL)",
        "book_source": (
            "runtime/data/copy_vault_l2_tape.jsonl:"
            "HYPERLIQUID_L2_WS_or_INFO_L2BOOK_causal"
        ),
        "fill_source": "LIVE_WS_non_snapshot_with_receive_time_for_all_protocol_segments",
        "historical_source_policy": "REST_BACKFILL_and_historical_books_audit_only",
        "causal_observation_required_all_segments": True,
        "forward_signal_policy": "causal_live_first_fill_observed_after_physical_freeze",
        "purge_policy": "copy_delay_plus_candidate_horizon_plus_max_target_lag",
    }


__all__ = [
    "CHECKPOINT_COLLECTOR_PROTOCOL",
    "COPYABLE_ENTRY_ACTIONS",
    "COPY_DELAY_MS",
    "HORIZONS_MS",
    "MAX_OPEN_POSITIONS",
    "MAX_REFERENCE_LAG_MS",
    "MAX_TARGET_LAG_MS",
    "METAORDER_GAP_MS",
    "MIN_TRAIN_TRADES",
    "NOTIONAL_USD",
    "PROTOCOL_NAME",
    "TRAIN_ECONOMIC_GATE_VERSION",
    "TRAIN_FRACTION",
    "VALIDATION_FRACTION",
    "canonical_metaorder_id",
    "classify_live_entry_action",
    "expected_open_direction",
    "protocol_signature",
]
