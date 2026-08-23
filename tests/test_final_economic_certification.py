from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import (
    FOUR_FILL_CONTRACT_VERSION,
    SOURCE_MODE,
)
from hl_observer.ops.final_economic_certification import (
    certify_campaign,
    certify_workspace,
)
from hl_observer.simulation.economic_objective import evaluate_objective


FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def _segment(*, net: float, hash_char: str, post_freeze: bool = False, no_lookahead: bool = False) -> dict:
    return {
        "sample_count": 1,
        "gross_pnl_usd": net + 0.4,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": net,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 1,
        "trade_ids_sha256": hash_char * 64,
        "post_freeze": post_freeze,
        "no_lookahead": no_lookahead,
    }


def _certified_campaign(family: str) -> dict:
    row = {
        "family": family,
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": True,
        "opened_positions": 2,
        "closed_positions": 2,
        "gross_pnl_usd": 5.0,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "net_pnl_usd": 4.6,
        "liquidatable_net": True,
        "duplicate_trade_ids": 0,
        "trade_ids_count": 2,
        "trade_ids_sha256": "a" * 64,
        "oos": _segment(net=2.1, hash_char="b", no_lookahead=True),
        "forward": _segment(net=2.1, hash_char="c", post_freeze=True),
        "placebos": {"beaten": True},
    }
    if family == "copy_vault":
        row["vault_generalization"] = {"sample_count": 20, "net_bps": 1.0}
    if family == "cross_venue_dislocation_v2":
        row["all_positions_two_leg_closed"] = True
        row["period"] = {
            "collection_meta": {
                "source_mode": SOURCE_MODE,
                "certified_snapshots": 2,
                "mapping_verified": True,
                "skew_verified": True,
                "four_fill_contract_version": FOUR_FILL_CONTRACT_VERSION,
            }
        }
    row.update(evaluate_objective(row))
    assert row["objective_status"] == "ATTEINT"
    return row


def _raw_trade(
    family: str,
    *,
    segment: str,
    entry_ms: int,
    exit_ms: int,
    coin: str = "ETH",
    direction: int = 1,
    native_id: str = "native",
) -> dict:
    if family == "lead_lag":
        return {
            "trade_id": native_id,
            "coin": coin,
            "direction": "LONG" if direction > 0 else "SHORT",
            "entry_ts_ns": entry_ms * 1_000_000,
            "exit_ts_ns": exit_ms * 1_000_000,
            "walk_forward_segment": segment,
        }
    if family == "cross_venue_dislocation_v2":
        return {
            "trade_id": native_id,
            "coin": coin,
            "basis_in_bps": 10.0 if direction > 0 else -10.0,
            "ts_in": float(entry_ms),
            "ts_out": float(exit_ms),
            "walk_forward_segment": segment,
        }
    return {
        "trade_id": native_id,
        "coin": coin,
        "direction": direction,
        "entry_ts_ms": entry_ms,
        "exit_ts_ms": exit_ms,
        "walk_forward_segment": segment,
    }


def _write_raw_proof(
    root: Path,
    family: str,
    *,
    first_entry_ms: int,
    shared: tuple[int, int] | None = None,
    duplicate_across_segments: bool = False,
) -> None:
    raw_dir = root / "runtime" / "reports" / "economic_campaigns" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    first = shared or (first_entry_ms, first_entry_ms + 100)
    second = first if duplicate_across_segments else (first_entry_ms + 1_000, first_entry_ms + 1_100)
    trades = [
        _raw_trade(
            family,
            segment="oos",
            entry_ms=first[0],
            exit_ms=first[1],
            native_id=f"{family}-native-oos",
        ),
        _raw_trade(
            family,
            segment="forward",
            entry_ms=second[0],
            exit_ms=second[1],
            native_id=f"{family}-native-forward-DIFFERENT",
        ),
    ]
    payload = {"trades": trades}
    if family == "lead_lag":
        payload = {"executable_campaign": {"trades": trades}}
    (raw_dir / f"{family}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_certified_workspace(root: Path) -> None:
    campaign_dir = root / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    starts = {
        "copy_vault": 1_800_000_000_000,
        "lead_lag": 1_800_000_010_000,
        "cross_venue_dislocation_v2": 1_800_000_020_000,
    }
    for family in FAMILIES:
        (campaign_dir / f"{family}.json").write_text(
            json.dumps(_certified_campaign(family)), encoding="utf-8"
        )
        _write_raw_proof(root, family, first_entry_ms=starts[family])


def test_certification_recalcule_la_gate_et_certifie_une_preuve_complete() -> None:
    row = _certified_campaign("lead_lag")
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is True
    assert result["eligible_net_pnl_usd"] >= 4.0
    assert result["proof_net_pnl_usd"] >= 4.0
    assert result["liquidatable_net"] is True
    assert result["costs_complete"] is True
    assert result["oos_positive"] is True
    assert result["forward_positive"] is True
    assert result["forward_post_freeze"] is True
    assert result["placebo_beaten"] is True
    assert result["reasons"] == []


def test_certification_refuse_un_statut_atteint_falsifie() -> None:
    row = _certified_campaign("lead_lag")
    row["forward"]["post_freeze"] = False
    row["objective_status"] = "ATTEINT"
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is False
    assert result["status"] == "NO_GO"
    assert "OBJECTIVE_STATUS_DRIFT" in result["reasons"]
    assert "FORWARD_NOT_PROVEN_POST_FREEZE" in result["reasons"]


def test_certification_refuse_eligible_net_falsifie() -> None:
    row = _certified_campaign("lead_lag")
    row["eligible_net_pnl_usd"] = 999.0
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is False
    assert "ELIGIBLE_NET_DRIFT" in result["reasons"]


def test_certification_refuse_famille_incoherente() -> None:
    row = _certified_campaign("lead_lag")
    row["family"] = "copy_vault"
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is False
    assert any(reason.startswith("FAMILY_MISMATCH:") for reason in result["reasons"])


def test_certification_refuse_couts_incomplets() -> None:
    row = _certified_campaign("lead_lag")
    row["latency_cost_usd"] = None
    row.update(evaluate_objective(row))
    result = certify_campaign("lead_lag", row)
    assert result["certified"] is False
    assert result["costs_complete"] is False
    assert "COSTS_INCOMPLETE" in result["reasons"]
    assert "UNMEASURED:latency_cost_usd" in result["reasons"]


def test_certification_absente_reste_fail_closed() -> None:
    result = certify_campaign("lead_lag", None)
    assert result["certified"] is False
    assert result["eligible_net_pnl_usd"] is None
    assert result["reasons"] == ["CAMPAIGN_MISSING_OR_UNREADABLE"]


def test_workspace_exige_les_trois_familles_sans_compensation(tmp_path: Path) -> None:
    _write_certified_workspace(tmp_path)
    campaign_dir = tmp_path / "runtime" / "reports" / "economic_campaigns"

    certified = certify_workspace(tmp_path)
    assert certified["all_families_certified"] is True
    assert certified["status"] == "ALL_FAMILIES_CERTIFIED"
    assert certified["cross_family_pnl_compensation_allowed"] is False
    assert certified["cross_family_trade_reuse_allowed"] is False
    assert certified["cross_family_trade_reuse_audit"]["no_reuse"] is True
    assert certified["paper_only"] is True
    assert certified["real_execution"] is False
    assert all(row["certified"] for row in certified["families"].values())

    weak = _certified_campaign("lead_lag")
    weak["forward"]["net_pnl_usd"] = -10.0
    weak.update(evaluate_objective(weak))
    (campaign_dir / "lead_lag.json").write_text(json.dumps(weak), encoding="utf-8")

    refused = certify_workspace(tmp_path)
    assert refused["all_families_certified"] is False
    assert refused["status"] == "NO_GO"
    assert refused["families"]["lead_lag"]["certified"] is False
    assert refused["families"]["copy_vault"]["certified"] is True
    assert refused["families"]["cross_venue_dislocation_v2"]["certified"] is True


def test_workspace_refuse_si_une_famille_manque_ou_est_illisible(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "runtime" / "reports" / "economic_campaigns"
    campaign_dir.mkdir(parents=True)
    (campaign_dir / "copy_vault.json").write_text(
        json.dumps(_certified_campaign("copy_vault")), encoding="utf-8"
    )
    (campaign_dir / "lead_lag.json").write_text("{json-invalide", encoding="utf-8")

    result = certify_workspace(tmp_path)
    assert result["all_families_certified"] is False
    assert result["families"]["copy_vault"]["certified"] is False
    assert "GLOBAL_TRADE_IDENTITY_PROOF_INCOMPLETE" in result["families"]["copy_vault"]["reasons"]
    assert result["families"]["lead_lag"]["reasons"] == ["CAMPAIGN_MISSING_OR_UNREADABLE"]
    assert result["families"]["cross_venue_dislocation_v2"]["reasons"] == ["CAMPAIGN_MISSING_OR_UNREADABLE"]


def _assert_pair_collision(tmp_path: Path, left: str, right: str) -> None:
    _write_certified_workspace(tmp_path)
    shared = (1_800_001_000_000, 1_800_001_000_100)
    _write_raw_proof(tmp_path, left, first_entry_ms=1, shared=shared)
    _write_raw_proof(tmp_path, right, first_entry_ms=2, shared=shared)
    result = certify_workspace(tmp_path)
    assert result["all_families_certified"] is False
    assert "CROSS_FAMILY_TRADE_REUSE" in result["families"][left]["reasons"]
    assert "CROSS_FAMILY_TRADE_REUSE" in result["families"][right]["reasons"]
    pair = result["cross_family_trade_reuse_audit"]["pairwise"]
    key = "__".join(sorted((left, right)))
    assert pair[key]["collision_count"] == 1


def test_workspace_refuse_collision_copy_lead_meme_si_ids_natifs_different(tmp_path: Path) -> None:
    _assert_pair_collision(tmp_path, "copy_vault", "lead_lag")


def test_workspace_refuse_collision_copy_cross_meme_si_ids_natifs_different(tmp_path: Path) -> None:
    _assert_pair_collision(tmp_path, "copy_vault", "cross_venue_dislocation_v2")


def test_workspace_refuse_collision_lead_cross_meme_si_ids_natifs_different(tmp_path: Path) -> None:
    _assert_pair_collision(tmp_path, "lead_lag", "cross_venue_dislocation_v2")


def test_workspace_refuse_collision_trois_familles(tmp_path: Path) -> None:
    _write_certified_workspace(tmp_path)
    shared = (1_800_002_000_000, 1_800_002_000_100)
    for index, family in enumerate(FAMILIES):
        _write_raw_proof(tmp_path, family, first_entry_ms=10 + index, shared=shared)
    result = certify_workspace(tmp_path)
    assert result["all_families_certified"] is False
    assert result["cross_family_trade_reuse_audit"]["total_cross_family_collisions"] == 3
    assert all("CROSS_FAMILY_TRADE_REUSE" in result["families"][family]["reasons"] for family in FAMILIES)


def test_workspace_refuse_reutilisation_oos_forward_dans_une_meme_famille(tmp_path: Path) -> None:
    _write_certified_workspace(tmp_path)
    _write_raw_proof(
        tmp_path,
        "copy_vault",
        first_entry_ms=1_800_003_000_000,
        duplicate_across_segments=True,
    )
    result = certify_workspace(tmp_path)
    assert result["all_families_certified"] is False
    assert "GLOBAL_TRADE_IDENTITY_PROOF_INCOMPLETE" in result["families"]["copy_vault"]["reasons"]
    assert "GLOBAL_TRADE_IDENTITY_DUPLICATE" in result["families"]["copy_vault"]["reasons"]
    assert result["cross_family_trade_reuse_audit"]["intra_family_duplicate_global_events"]["copy_vault"] == 1
