from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from hl_observer.backtesting.cross_venue_certified import FOUR_FILL_CONTRACT_VERSION, SOURCE_MODE
from hl_observer.ops import self_hosted_return
from hl_observer.ops.final_economic_certification import certify_workspace
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


def _campaign(family: str) -> dict:
    row = {
        "family": family,
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": True,
        "parameter_freeze": {
            "campaign_id": f"freeze-{family}",
            "frozen_at_ms": 1_799_999_999_999,
            "selected_before_final_evaluation": True,
            "parameters_sha256": "e" * 64,
            "path": f"runtime/reports/economic_campaigns/freezes/{family}/freeze.json",
        },
        "dataset_provenance": {"dataset_fingerprint": "d" * 64},
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


def _trade(family: str, *, segment: str, entry_ms: int, exit_ms: int, native_id: str) -> dict:
    if family == "lead_lag":
        return {
            "trade_id": native_id,
            "coin": "ETH",
            "direction": "LONG",
            "entry_ts_ns": entry_ms * 1_000_000,
            "exit_ts_ns": exit_ms * 1_000_000,
            "walk_forward_segment": segment,
        }
    if family == "cross_venue_dislocation_v2":
        return {
            "trade_id": native_id,
            "coin": "ETH",
            "basis_in_bps": 10.0,
            "ts_in": float(entry_ms),
            "ts_out": float(exit_ms),
            "walk_forward_segment": segment,
        }
    return {
        "trade_id": native_id,
        "coin": "ETH",
        "direction": 1,
        "entry_ts_ms": entry_ms,
        "exit_ts_ms": exit_ms,
        "walk_forward_segment": segment,
    }


def _write_workspace(root: Path, *, weak_family: str | None = None) -> None:
    campaign_dir = root / "runtime" / "reports" / "economic_campaigns"
    raw_dir = campaign_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    starts = {
        "copy_vault": 1_800_000_000_000,
        "lead_lag": 1_800_000_010_000,
        "cross_venue_dislocation_v2": 1_800_000_020_000,
    }
    for family in FAMILIES:
        campaign = _campaign(family)
        if family == weak_family:
            campaign["forward"]["net_pnl_usd"] = -1.0
            campaign.update(evaluate_objective(campaign))
        (campaign_dir / f"{family}.json").write_text(json.dumps(campaign), encoding="utf-8")
        start = starts[family]
        trades = [
            _trade(family, segment="oos", entry_ms=start, exit_ms=start + 100, native_id=f"{family}-oos"),
            _trade(family, segment="forward", entry_ms=start + 1_000, exit_ms=start + 1_100, native_id=f"{family}-forward"),
        ]
        payload = {"trades": trades}
        if family == "lead_lag":
            payload = {"executable_campaign": {"trades": trades}}
        (raw_dir / f"{family}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_job_result(result_dir: Path, workspace: Path, *, project_sha: str) -> None:
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps(
            {
                "schema": "alina.autonomous_research_result.v1",
                "job_id": "canonical-return-test",
                "status": "SUCCESS",
                "suite": "economic-full",
                "mode": "economic",
                "request_digest": "f" * 64,
                "project_sha": project_sha,
                "workspace": str(workspace),
                "exit_code": 0,
                "paper_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )


def _contains_forbidden_raw_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in {"trades", "raw_payload", "fills", "dataset_rows"}:
                return True
            if _contains_forbidden_raw_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_raw_key(item) for item in value)
    return False


def test_alina_return_est_strictement_derive_de_la_certification_canonique(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    result_dir = tmp_path / "result"
    _write_workspace(workspace)
    project_sha = "1" * 40
    _write_job_result(result_dir, workspace, project_sha=project_sha)
    monkeypatch.setattr(self_hosted_return, "build_decision", lambda _root: {})

    canonical = certify_workspace(workspace)
    returned = self_hosted_return.build_return(result_dir)

    assert returned["technical_status"] == "SUCCESS"
    assert returned["project_sha"] == project_sha
    assert returned["economic_certification"] == canonical
    assert returned["economic_certification"]["all_families_certified"] is True
    for family in FAMILIES:
        certification = returned["economic_certification"]["families"][family]
        assert certification == canonical["families"][family]
        assert certification["proof_provenance"]["dataset_fingerprint"] == "d" * 64
        assert certification["proof_provenance"]["parameters_sha256"] == "e" * 64
        assert certification["proof_provenance"]["campaign_id"] == f"freeze-{family}"
        assert certification["proof_provenance"]["complete"] is True
    assert returned["paper_only"] is True
    assert returned["real_execution"] is False
    assert _contains_forbidden_raw_key(returned) is False


def test_alina_return_ne_surclasse_jamais_un_more_data_ou_kill(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    result_dir = tmp_path / "result"
    _write_workspace(workspace, weak_family="lead_lag")
    _write_job_result(result_dir, workspace, project_sha="2" * 40)
    monkeypatch.setattr(self_hosted_return, "build_decision", lambda _root: {})

    canonical = certify_workspace(workspace)
    returned = self_hosted_return.build_return(result_dir)

    assert canonical["all_families_certified"] is False
    assert returned["economic_certification"] == canonical
    assert returned["economic_certification"]["all_families_certified"] is False
    assert returned["economic_certification"]["families"]["lead_lag"]["certified"] is False
    assert returned["message_fr"].startswith("Retour compact prêt")
    assert _contains_forbidden_raw_key(returned) is False
