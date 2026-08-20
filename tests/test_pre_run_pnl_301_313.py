from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import FOUR_FILL_CONTRACT_VERSION, SOURCE_MODE
from hl_observer.ops.canonical_775_guard import (
    DONE_TECHNICAL_775_SOURCE_LOSS_HONEST,
    IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST,
    ROADMAP_ID,
    ROADMAP_TOTAL,
    validate_manifest,
)
from hl_observer.simulation.economic_family_gate import evaluate_all_families
from hl_observer.simulation.economic_objective import TARGET_NET_USD


def _segment(net: float, count: int, char: str, *, no_lookahead=False, post_freeze=False):
    fees = spread = slippage = latency = 0.1; gross = net + fees + spread + slippage + latency
    return {"gross_pnl_usd": gross, "fees_usd": fees, "spread_cost_usd": spread, "slippage_cost_usd": slippage, "latency_cost_usd": latency, "net_pnl_usd": net, "sample_count": count, "liquidatable_net": True, "duplicate_trade_ids": 0, "trade_ids_count": count, "trade_ids_sha256": char * 64, "no_lookahead": no_lookahead, "post_freeze": post_freeze}


def _cross_meta():
    return {"source_mode": SOURCE_MODE, "certified_snapshots": 4, "mapping_verified": True, "skew_verified": True, "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION}


def _proof(family: str, *, oos_net: float = 2.2, forward_net: float = 2.2):
    row = {"family": family, "paper_read_only": True, "real_execution": False, "starting_capital_usd": 1000.0, "parameters_frozen": True, "opened_positions": 4, "closed_positions": 4, "gross_pnl_usd": 5.8, "fees_usd": 0.5, "spread_cost_usd": 0.4, "slippage_cost_usd": 0.3, "latency_cost_usd": 0.2, "net_pnl_usd": 4.4, "liquidatable_net": True, "duplicate_trade_ids": 0, "trade_ids_count": 4, "trade_ids_sha256": "a" * 64, "oos": _segment(oos_net, 2, "b", no_lookahead=True), "forward": _segment(forward_net, 2, "c", post_freeze=True), "placebos": {"beaten": True}}
    if family == "copy_vault": row["vault_generalization"] = {"sample_count": 20, "net_bps": 3.0}
    if family == "cross_venue_dislocation_v2":
        row["all_positions_two_leg_closed"] = True; row["period"] = {"collection_meta": _cross_meta()}
    return row


def test_301_couts_incomplets_interdisent_la_promotion():
    rows = [_proof("copy_vault"), _proof("lead_lag"), _proof("cross_venue_dislocation_v2")]; rows[1]["forward"] = dict(rows[1]["forward"]); rows[1]["forward"]["slippage_cost_usd"] = None
    result = evaluate_all_families(rows)
    assert result["objective_status"] == "NON_ATTEINT" and result["all_families_independently_reached"] is False
    assert "FAMILY_TARGET_NOT_REACHED:lead_lag" in result["objective_reasons"]


def test_cible_quatre_dollars_est_constante_et_independante_par_famille():
    assert TARGET_NET_USD == 4.0
    result = evaluate_all_families([_proof("copy_vault", oos_net=4, forward_net=4), _proof("lead_lag", oos_net=.4, forward_net=.5), _proof("cross_venue_dislocation_v2", oos_net=4, forward_net=4)])
    assert result["display_total_proof_net_usd"] > 4.0 and result["global_compensation_allowed"] is False
    assert result["objective_status"] == "NON_ATTEINT" and result["family_status"]["lead_lag"] == "NON_ATTEINT"


def test_les_trois_familles_doivent_toutes_etre_presentes_une_seule_fois():
    missing = evaluate_all_families([_proof("copy_vault"), _proof("lead_lag")]); assert "MISSING_FAMILY:cross_venue_dislocation_v2" in missing["objective_reasons"]
    duplicate = evaluate_all_families([_proof("copy_vault"), _proof("lead_lag"), _proof("cross_venue_dislocation_v2"), _proof("arbitrage")]); assert "DUPLICATE_FAMILY:cross_venue_dislocation_v2" in duplicate["objective_reasons"]


def test_preuve_complete_des_trois_familles_peut_seule_passer():
    result = evaluate_all_families([_proof("copy_vault"), _proof("lead_lag"), _proof("cross_venue_dislocation_v2")])
    assert result["target_net_usd_per_family"] == 4.0 and result["all_families_independently_reached"] is True and result["objective_status"] == "ATTEINT"


def test_garde_775_refuse_explicitement_l_ancien_master_v6():
    old = {"roadmap_id": "MASTER_V6_AUD_DATA_BUG", "total": 590, "status": "DONE", "legacy_master_v6_equivalent": True, "anchors": {"301": "Partition Parquet"}}
    result = validate_manifest(old); assert result["ok"] is False; assert "WRONG_ROADMAP_TOTAL" in result["issues"] and "CANONICAL_ANCHOR_MISMATCH:301" in result["issues"]


def test_manifest_775_courant_est_honnete_et_valide_dans_sa_phase():
    manifest = json.loads(Path("docs/PRE_RUN_775_CANONICAL_STATUS.json").read_text(encoding="utf-8")); result = validate_manifest(manifest)
    assert manifest["roadmap_id"] == ROADMAP_ID and manifest["total"] == ROADMAP_TOTAL
    assert manifest["status"] in {
        IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST,
        DONE_TECHNICAL_775_SOURCE_LOSS_HONEST,
    }
    assert manifest["literal_source_unrecoverable"] is True and manifest["exact_literal_reconstruction_claimed"] is False
    assert result["terminal_recovery"] is True and result["ok"] is True

    derived = manifest["derived_technical_controls"]
    if manifest["status"] == DONE_TECHNICAL_775_SOURCE_LOSS_HONEST:
        assert manifest["technical_completion_claimed"] is True
        assert manifest["technical_completion_done"] == ROADMAP_TOTAL == 775
        assert derived["done"] == 455
        assert derived["base_requirements_done"] == 91
        assert derived["next_unverified_id"] is None
    else:
        assert manifest["technical_completion_claimed"] is False
        assert 320 <= manifest["technical_completion_done"] < ROADMAP_TOTAL
        assert 0 <= derived["done"] < 455
        assert derived["next_unverified_id"] is not None


def test_done_775_exige_775_libelles_et_775_preuves():
    fake_done = {"roadmap_id": ROADMAP_ID, "total": ROADMAP_TOTAL, "status": "DONE", "legacy_master_v6_equivalent": False, "anchors": {"301": "Interdire promotion par PnL sans coûts", "314": "Reconstruction OPEN/ADD/REDUCE/CLOSE parfaite"}, "labels": ["x"] * 774, "proofs": {str(i): "pytest" for i in range(1, 775)}}
    result = validate_manifest(fake_done); assert result["ok"] is False; assert "DONE_REQUIRES_775_LITERAL_LABELS" in result["issues"] and "DONE_REQUIRES_775_EXECUTABLE_PROOFS" in result["issues"]
