from __future__ import annotations

from hl_observer.ops.paper_pipeline_e2e import build_copy_vault_e2e_receipt


HASH = "a" * 64
REFS = {stage: f"safe://event-1/{stage.lower()}" for stage in ("SAFE", "WALLET", "SIGNAL", "RISK", "PAPER", "LEDGER", "OOS")}


def _event() -> dict[str, object]:
    return {
        "seq": 1,
        "ts_ms": 1_000,
        "coin": "BTC",
        "mid": 100.0,
        "strategy": "copy_vault",
        "side": 1,
        "edge_bps": 30.0,
        "source_status": "SAFE",
        "real_execution": False,
        "stage_refs": REFS,
    }


def test_copy_vault_e2e_receipt_proves_technical_chain_but_not_economics():
    receipt = build_copy_vault_e2e_receipt(
        [_event()],
        safe_manifest_sha256=HASH,
        oos_manifest_sha256=HASH,
        source_release="copy-vault-safe-release",
    )

    assert receipt["verdict"] == "PROVEN_TECHNICAL"
    assert receipt["closure_allowed"] is True
    assert receipt["economic_verdict"] == "UNMEASURABLE"
    assert receipt["stages"] == ["SAFE", "WALLET", "SIGNAL", "RISK", "PAPER", "LEDGER", "OOS"]
    assert receipt["real_execution"] is False


def test_copy_vault_e2e_receipt_rejects_missing_provenance_and_real_execution():
    event = _event()
    event["stage_refs"] = {"SAFE": REFS["SAFE"]}
    event["real_execution"] = True

    receipt = build_copy_vault_e2e_receipt(
        [event],
        safe_manifest_sha256="bad",
        oos_manifest_sha256=HASH,
        source_release="copy-vault-safe-release",
    )

    assert receipt["verdict"] == "UNMEASURABLE"
    assert receipt["closure_allowed"] is False
    assert "SAFE_MANIFEST_HASH_INVALID" in receipt["errors"]
    assert "EVENT_0_REAL_EXECUTION_FORBIDDEN" in receipt["errors"]
