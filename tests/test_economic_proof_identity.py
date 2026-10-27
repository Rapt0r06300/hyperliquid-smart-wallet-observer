from __future__ import annotations

from hl_observer.simulation.economic_proof_identity import (
    SCHEMA,
    canonical_trade_event,
)


def test_cross_family_proof_identity_preserves_native_symbol_case():
    common = {
        "direction": 1,
        "entry_ts_ms": 1_000,
        "exit_ts_ms": 2_000,
        "execution_id": "execution-1",
        "source_lineage_id": "leader-fill-1",
    }

    lower = canonical_trade_event({**common, "coin": "kPEPE"})
    upper = canonical_trade_event({**common, "coin": "KPEPE"})

    assert SCHEMA.endswith("v3_native_instrument_identity")
    assert lower is not None and upper is not None
    assert lower["coin"] == "kPEPE"
    assert upper["coin"] == "KPEPE"
    assert lower["global_event_id"] != upper["global_event_id"]
    assert lower["source_lineage_hash"] != upper["source_lineage_hash"]
