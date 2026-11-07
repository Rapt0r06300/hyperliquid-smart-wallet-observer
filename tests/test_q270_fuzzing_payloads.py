"""Q-270 — Fuzzing des payloads externes (champs manquants/types inattendus).

Vérifie que UnifiedEvent rejette proprement les payloads malformés
au lieu de crasher silencieusement.
"""
from __future__ import annotations

import pytest

from hl_observer.data_contract.unified_event import EventType, UnifiedEvent

_VALID_KWARGS = dict(
    source="copy_vault",
    venue="hyperliquid",
    symbol_canonical="BTC",
    event_type=EventType.BBO_SNAPSHOT,
    exchange_ts_ms=1_700_000_000_000,
    recv_wall_ts_ms=1_700_000_000_050,
    recv_mono_ns=100_000_000,
    write_wall_ts_ms=1_700_000_000_060,
    event_id="evt-001",
    connection_id="conn-001",
    sequence=1,
    schema_version="1.0",
    raw_evidence_ref="ref-001",
)


def _make(**overrides):
    kw = {**_VALID_KWARGS, **overrides}
    return UnifiedEvent(**kw)


def test_valid_payload_accepted():
    evt = _make()
    assert evt.source == "copy_vault"


@pytest.mark.parametrize("field", [
    "source", "venue", "symbol_canonical", "event_id",
    "connection_id", "schema_version", "raw_evidence_ref",
])
def test_empty_string_rejected(field):
    with pytest.raises(ValueError):
        _make(**{field: ""})


@pytest.mark.parametrize("field", [
    "source", "venue", "symbol_canonical", "event_id",
    "connection_id", "schema_version", "raw_evidence_ref",
])
def test_whitespace_only_rejected(field):
    with pytest.raises(ValueError):
        _make(**{field: "   "})


def test_bad_event_type_rejected():
    with pytest.raises((TypeError, ValueError)):
        _make(event_type="NOT_A_TYPE")


@pytest.mark.parametrize("field", [
    "exchange_ts_ms", "recv_wall_ts_ms", "recv_mono_ns",
    "write_wall_ts_ms", "sequence",
])
def test_negative_int_rejected(field):
    with pytest.raises(ValueError):
        _make(**{field: -1})


@pytest.mark.parametrize("field", [
    "exchange_ts_ms", "recv_wall_ts_ms", "sequence",
])
def test_bool_rejected_as_int(field):
    with pytest.raises(ValueError):
        _make(**{field: True})


def test_missing_field_raises():
    kw = {**_VALID_KWARGS}
    del kw["source"]
    with pytest.raises(TypeError):
        UnifiedEvent(**kw)
