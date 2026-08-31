from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.economics.hardcode_scanner import (
    PROPOSAL_DISPOSITION,
)
from hl_observer.economics.hardcode_scanner import (
    SCHEMA_VERSION as HARDCODE_SCAN_SCHEMA,
)
from hl_observer.simulation.economic_objective import evaluate_objective
from hl_observer.simulation.economic_proof_audit import (
    INDEPENDENT_AUDIT_SCHEMA,
    audit_family,
    audit_reports,
    write_audit,
)

AUDIT_AS_OF_MS = int(datetime(2026, 8, 31, tzinfo=UTC).timestamp() * 1000)


def _hardcode_scan(*, parse_errors: int = 0) -> dict:
    errors = [
        {"path": "src/example.py", "reason": "SYNTHETIC_PARSE_ERROR"}
        for _ in range(parse_errors)
    ]
    body = {
        "schema_version": HARDCODE_SCAN_SCHEMA,
        "disposition": PROPOSAL_DISPOSITION,
        "auto_rewrite": False,
        "file_hashes": {"src/example.py": "a" * 64},
        "summary": {
            "files_scanned": 1,
            "proposal_count": 0,
            "suppressed_count": 0,
            "parse_error_count": parse_errors,
            "by_category": {},
        },
        "findings": [],
        "suppressions": [],
        "parse_errors": errors,
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(repr(body).encode()).hexdigest(),
    }


def _audit(campaign: dict, raw: dict, *, hardcode_scan: dict | None = None) -> dict:
    return audit_family(
        campaign,
        raw,
        hardcode_scan=hardcode_scan or _hardcode_scan(),
        audit_as_of_ms=AUDIT_AS_OF_MS,
    )


def _hash_ids(*trade_ids: str) -> str:
    return hashlib.sha256("\n".join(sorted(trade_ids)).encode("utf-8")).hexdigest()


def _segment(trade_id: str, net: float) -> dict:
    return {
        "gross_pnl_usd": 3.0,
        "fees_usd": 0.25,
        "spread_cost_usd": 0.25,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net,
        "sample_count": 1,
        "trade_ids_count": 1,
        "duplicate_trade_ids": 0,
        "trade_ids_sha256": _hash_ids(trade_id),
        "liquidatable_net": True,
    }


def _trade(
    trade_id: str,
    segment: str,
    signal_ms: int,
    *,
    assumption_snapshot_hash: str,
) -> dict:
    reality_model_version = "copy_vault_exact_checkpoint_executable_bbo.v2"
    cost_component_receipts = {
        "fees": {
            "component": "fees",
            "amount_usd": 0.25,
            "zero_reason": None,
            "formula_id": "copy_vault.round_trip_fee.v1",
            "reality_model_version": reality_model_version,
            "provenance_ids": ["fee.taker.hyperliquid.bps"],
            "certification_eligible": True,
        },
        "spread": {
            "component": "spread",
            "amount_usd": 0.25,
            "zero_reason": None,
            "formula_id": "copy_vault.executable_bid_ask_spread.v1",
            "reality_model_version": reality_model_version,
            "provenance_ids": ["entry_book.bid_ask", "exit_book.bid_ask"],
            "certification_eligible": True,
        },
        "slippage": {
            "component": "slippage",
            "amount_usd": 0.0,
            "zero_reason": "NOT_APPLICABLE",
            "formula_id": "copy_vault.full_top_capacity.v1",
            "reality_model_version": reality_model_version,
            "provenance_ids": ["entry_capacity_usd", "exit_capacity_usd"],
            "certification_eligible": True,
        },
        "latency": {
            "component": "latency",
            "amount_usd": 0.0,
            "zero_reason": "MEASURED_ZERO",
            "formula_id": "copy_vault.adverse_latency.v1",
            "reality_model_version": reality_model_version,
            "provenance_ids": ["reference_ts_ms", "entry_ts_ms"],
            "certification_eligible": True,
        },
    }
    return {
        "trade_id": trade_id,
        "vault": "0x" + "1" * 40,
        "coin": "BTC",
        "walk_forward_segment": segment,
        "signal_ts_ms": signal_ms,
        "entry_ts_ms": signal_ms + 10,
        "exit_ts_ms": signal_ms + 100,
        "gross_pnl_usd": 3.0,
        "fees_usd": 0.25,
        "spread_cost_usd": 0.25,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "cost_component_receipts": cost_component_receipts,
        "net_pnl_usd": 2.5,
        "liquidatable_net": True,
        "paper_read_only": True,
        "real_execution": False,
        "assumption_snapshot_hash": assumption_snapshot_hash,
        "reference_lag_ms": 5.0,
        "entry_target_lag_ms": 10.0,
        "exit_target_lag_ms": 10.0,
        "observed_latency_ms": 10.0,
    }


def _positive_copy_evidence() -> tuple[dict, dict]:
    oos_id = "oos-trade"
    forward_id = "forward-trade"
    oos = {**_segment(oos_id, 2.5), "no_lookahead": True}
    forward = {**_segment(forward_id, 2.5), "post_freeze": True}
    economic_contract = build_copy_vault_contract(
        mode=EconomicRunMode.CERTIFIABLE,
        notional_usd=150.0,
        copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0,
        max_target_lag_ms=30_000.0,
    ).receipt()
    snapshot_hash = economic_contract["assumption_snapshot_hash"]
    campaign = {
        "family": "copy_vault",
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "economic_contract": economic_contract,
        "assumption_snapshot_hash": snapshot_hash,
        "parameters_frozen": True,
        "parameter_freeze": {"campaign_id": "freeze-1", "frozen_at_ms": 1_000},
        "opened_positions": 2,
        "closed_positions": 2,
        "gross_pnl_usd": 6.0,
        "fees_usd": 0.5,
        "spread_cost_usd": 0.5,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": 5.0,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 2,
        "trade_ids_sha256": _hash_ids(oos_id, forward_id),
        "oos": oos,
        "forward": forward,
        "placebos": {"beaten": True},
        "vault_generalization": {"sample_count": 20, "net_bps": 1.0},
    }
    campaign.update(evaluate_objective(campaign))
    raw = {
        "schema_version": "hypersmart.copy_vault_executable_campaign.v1",
        "paper_read_only": True,
        "real_execution": False,
        "trades": [
            _trade(
                oos_id,
                "oos",
                900,
                assumption_snapshot_hash=snapshot_hash,
            ),
            _trade(
                forward_id,
                "forward",
                1_100,
                assumption_snapshot_hash=snapshot_hash,
            ),
        ],
    }
    return campaign, raw


def test_audit_economic_proof_reconcilie_une_preuve_positive_complete():
    campaign, raw = _positive_copy_evidence()

    result = _audit(campaign, raw)

    assert result["ledger_valid"] is True
    assert result["classification"] == "VALID_POSITIVE"
    assert result["objective_status"] == "ATTEINT"
    assert result["proof_net_pnl_usd"] == 5.0
    assert result["aggregate_recomputed"]["net_pnl_usd"] == 5.0
    independent = result["independent_economic_audit"]
    assert independent["schema_version"] == INDEPENDENT_AUDIT_SCHEMA
    assert independent["ready"] is True
    assert set(independent["controls"]) == {
        "reconciliation_identities",
        "missing_costs",
        "stale_assumptions",
        "duplicate_charging",
        "hidden_hardcodes",
        "unsupported_zeros",
        "dependency_mismatch",
        "source_freshness",
    }


def test_audit_economic_proof_refuse_un_trade_forward_anterieur_au_gel():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][1]["signal_ts_ms"] = 999

    result = _audit(campaign, raw)

    assert result["ledger_valid"] is False
    assert result["classification"] == "INVALID"
    assert any(reason.startswith("FORWARD_NOT_POST_FREEZE") for reason in result["issues"])


def test_audit_economic_proof_refuse_les_identites_dupliquees():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][1]["trade_id"] = raw["trades"][0]["trade_id"]

    result = _audit(campaign, raw)

    assert result["ledger_valid"] is False
    assert any(reason.startswith("DUPLICATE_RAW_TRADE_IDS") for reason in result["issues"])


def test_audit_economic_proof_detecte_un_resume_desynchronise_du_ledger():
    campaign, raw = _positive_copy_evidence()
    campaign["net_pnl_usd"] = 9.0

    result = _audit(campaign, raw)

    assert result["ledger_valid"] is False
    assert any("CAMPAIGN_NET_PNL_USD_MISMATCH" in reason for reason in result["issues"])


def test_audit_economic_proof_refuse_un_snapshot_economique_desynchronise():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][1]["assumption_snapshot_hash"] = "0" * 64

    result = _audit(campaign, raw)

    assert result["ledger_valid"] is False
    assert "TRADE_ASSUMPTION_SNAPSHOT_MISMATCH:forward-trade" in result["issues"]


def test_audit_reports_ecrit_les_deux_artefacts(tmp_path):
    campaign, raw = _positive_copy_evidence()
    report_dir = tmp_path / "runtime" / "reports" / "economic_campaigns"
    raw_dir = report_dir / "raw"
    raw_dir.mkdir(parents=True)
    for family in ("copy_vault", "lead_lag", "cross_venue_dislocation_v2"):
        family_campaign = deepcopy(campaign)
        family_campaign["family"] = family
        family_raw = deepcopy(raw)
        if family == "lead_lag":
            family_raw = {
                "paper_read_only": True,
                "real_execution": False,
                "executable_campaign": {"trades": []},
            }
        (report_dir / f"{family}.json").write_text(
            json.dumps(family_campaign), encoding="utf-8"
        )
        (raw_dir / f"{family}.json").write_text(
            json.dumps(family_raw), encoding="utf-8"
        )

    audit = audit_reports(
        tmp_path,
        hardcode_scan=_hardcode_scan(),
        audit_as_of_ms=AUDIT_AS_OF_MS,
    )
    json_path, markdown_path = write_audit(tmp_path, audit)

    assert audit["missing_families"] == []
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert "copy_vault" in markdown_path.read_text(encoding="utf-8")


def test_audit_independant_refuse_une_identite_economique_cassee():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][0]["net_pnl_usd"] = 2.0

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["reconciliation_identities"]
    assert control["ready"] is False
    assert "TRADE_RECONCILIATION_FAILED:oos-trade" in control["issues"]


def test_audit_independant_refuse_un_recu_de_cout_manquant():
    campaign, raw = _positive_copy_evidence()
    del raw["trades"][0]["cost_component_receipts"]["fees"]

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["missing_costs"]
    assert control["ready"] is False
    assert "COST_COMPONENTS_MISSING:oos-trade:fees" in control["issues"]


def test_audit_independant_refuse_une_hypothese_perimee():
    campaign, raw = _positive_copy_evidence()
    assumptions = campaign["economic_contract"]["assumption_snapshot"]["assumptions"]
    fee = next(row for row in assumptions if row["assumption_id"] == "fee.taker.hyperliquid.bps")
    fee["revalidate_after"] = "2026-08-01T00:00:00Z"

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["stale_assumptions"]
    assert control["ready"] is False
    assert any(reason.startswith("ASSUMPTION_STALE:fee.taker.hyperliquid.bps") for reason in control["issues"])


def test_audit_independant_refuse_un_double_comptage_de_cout():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][0]["cost_component_receipts"]["fees"]["amount_usd"] = 0.5

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["duplicate_charging"]
    assert control["ready"] is False
    assert "COST_RECEIPT_AMOUNT_MISMATCH:oos-trade:fees" in control["issues"]
    assert "COST_RECEIPT_DEDUCTION_COUNT_INVALID:oos-trade" in control["issues"]


def test_audit_independant_refuse_un_scan_de_hardcodes_incomplet():
    campaign, raw = _positive_copy_evidence()

    result = _audit(campaign, raw, hardcode_scan=_hardcode_scan(parse_errors=1))

    control = result["independent_economic_audit"]["controls"]["hidden_hardcodes"]
    assert control["ready"] is False
    assert "HARDCODE_SCAN_PARSE_ERRORS" in control["issues"]


def test_audit_independant_refuse_un_zero_non_justifie():
    campaign, raw = _positive_copy_evidence()
    raw["trades"][0]["cost_component_receipts"]["slippage"]["zero_reason"] = None

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["unsupported_zeros"]
    assert control["ready"] is False
    assert "ZERO_REASON_MISSING_OR_INVALID:oos-trade:slippage" in control["issues"]


def test_audit_independant_refuse_une_dependance_de_formule_cassee():
    campaign, raw = _positive_copy_evidence()
    campaign["economic_contract"]["formula_manifest"][0]["parent_ids"].append(
        "assumption.absente"
    )

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["dependency_mismatch"]
    assert control["ready"] is False
    assert any("FORMULA_NODES_MISSING" in reason for reason in control["issues"])


def test_audit_independant_refuse_une_source_externe_sans_fraicheur():
    campaign, raw = _positive_copy_evidence()
    assumptions = campaign["economic_contract"]["assumption_snapshot"]["assumptions"]
    fee = next(row for row in assumptions if row["assumption_id"] == "fee.taker.hyperliquid.bps")
    fee["observed_at"] = None

    result = _audit(campaign, raw)

    control = result["independent_economic_audit"]["controls"]["source_freshness"]
    assert control["ready"] is False
    assert "EXTERNAL_SOURCE_OBSERVED_AT_MISSING:fee.taker.hyperliquid.bps" in control["issues"]
