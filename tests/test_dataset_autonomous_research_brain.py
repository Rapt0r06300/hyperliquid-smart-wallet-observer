from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.max_data_policy import (
    choose_max_data_job,
    targets_reached_from_brain,
)
from hl_observer.ops.autonomous_research_brain import build_decision, decide_family


def _campaign(**overrides):
    payload = {
        "family": "copy_vault",
        "objective_status": "NON_ATTEINT",
        "objective_reasons": ["TARGET_NET_USD_NOT_REACHED"],
        "net_pnl_usd": -1.0,
        "signal_count": 100,
        # Ces nombres doivent rester sans influence sur le classement paramétrique.
        "oos": {"net_pnl_usd": 999999.0, "sample_count": 100},
        "forward": {"net_pnl_usd": -999999.0, "sample_count": 100},
    }
    payload.update(overrides)
    return payload


def test_preuve_absente_demande_de_completer_les_donnees() -> None:
    decision = decide_family("lead_lag", None)
    assert decision["priority"] == 100
    assert decision["phase"] == "BUILD_EVIDENCE"
    assert decision["holdout_used_for_ranking"] is False


def test_net_negatif_declenche_recherche_de_mecanisme_pas_tuning_holdout() -> None:
    decision = decide_family("lead_lag", _campaign(family="lead_lag", net_pnl_usd=-3.0))
    assert decision["phase"] == "MECHANISM_SEARCH"
    assert decision["holdout_used_for_ranking"] is False


def test_net_diagnostic_positif_mais_preuve_incomplete_reste_en_recherche_robuste() -> None:
    decision = decide_family("lead_lag", _campaign(family="lead_lag", net_pnl_usd=2.0))
    assert decision["phase"] == "ROBUST_TRAIN_REFINEMENT"
    assert decision["priority"] == 80


def test_promu_train_only_demande_confirmation_independante() -> None:
    strict = {
        "promoted_count": 3,
        "strict_train_only": True,
        "robustness_verdict": "OK",
        "validation_rows_seen_by_scout": 0,
    }
    decision = decide_family("copy_vault", _campaign(net_pnl_usd=1.0), strict_copy=strict)
    assert decision["phase"] == "INDEPENDENT_CONFIRMATION"
    assert decision["priority"] == 90


def test_pbo_surajuste_demande_plus_de_donnees_pas_plus_de_parametres() -> None:
    strict = {
        "promoted_count": 4,
        "strict_train_only": True,
        "robustness_verdict": "SUR_AJUSTE",
        "pbo": 0.75,
    }
    decision = decide_family("copy_vault", _campaign(net_pnl_usd=2.0), strict_copy=strict)
    assert decision["phase"] == "EXPAND_DATA_NOT_PARAMETERS"
    assert decision["priority"] == 55


def test_objectif_atteint_gèle_au_lieu_de_retuner() -> None:
    decision = decide_family(
        "cross_venue_dislocation_v2",
        _campaign(
            family="cross_venue_dislocation_v2",
            objective_status="ATTEINT",
            objective_reasons=[],
            net_pnl_usd=12.0,
        ),
    )
    assert decision["phase"] == "FREEZE_AND_CONFIRM_FORWARD"
    assert decision["priority"] == 20
    assert decision["holdout_gate"] == "PASS"


def test_brain_ne_prend_pas_la_magnitude_oos_forward_comme_score(tmp_path: Path) -> None:
    report = tmp_path / "runtime" / "reports" / "economic_campaigns"
    report.mkdir(parents=True)
    for family, net in (
        ("copy_vault", -1.0),
        ("lead_lag", -2.0),
        ("cross_venue_dislocation_v2", -3.0),
    ):
        payload = _campaign(family=family, net_pnl_usd=net)
        payload["oos"]["net_pnl_usd"] = {"copy_vault": 1e9, "lead_lag": -1e9, "cross_venue_dislocation_v2": 0}[family]
        payload["forward"]["net_pnl_usd"] = -payload["oos"]["net_pnl_usd"]
        (report / f"{family}.json").write_text(json.dumps(payload), encoding="utf-8")

    decision = build_decision(tmp_path)
    policy = decision["holdout_policy"]
    assert policy["numeric_oos_used_for_parameter_ranking"] is False
    assert policy["numeric_forward_used_for_parameter_ranking"] is False
    assert decision["next_recommended_job"]["mode"] == "historical-deep"


def test_missing_mesure_passe_avant_recherche_parametrique(tmp_path: Path) -> None:
    report = tmp_path / "runtime" / "reports" / "economic_campaigns"
    report.mkdir(parents=True)
    (report / "copy_vault.json").write_text(
        json.dumps(
            _campaign(
                objective_reasons=["UNMEASURED:net_pnl_usd"],
                net_pnl_usd=None,
            )
        ),
        encoding="utf-8",
    )
    decision = build_decision(tmp_path)
    assert decision["next_recommended_job"]["mode"] == "economic"
    assert decision["family_decisions"][0]["priority"] == 100


def _plan(remaining: float) -> dict[str, object]:
    return {
        "remaining_download_gib": remaining,
        "download_gib": remaining,
        "missing_asset_count": 0,
    }


def test_max_data_escalade_vers_la_suite_de_la_famille_prioritaire() -> None:
    decisions = [
        {"family": "copy_vault", "priority": 40, "phase": "DIAGNOSE"},
        {"family": "lead_lag", "priority": 100, "phase": "MECHANISM_SEARCH"},
        {"family": "cross_venue_dislocation_v2", "priority": 20, "phase": "FREEZE_AND_CONFIRM_FORWARD"},
    ]
    plans = {
        "economic-full": _plan(9.8),
        "lead-lag-full": _plan(9.8),
        "microstructure-full": _plan(5.9),
        "research-lab-full": _plan(61.0),
        "sqlite-all-safe": _plan(60.7),
        "full-archive": _plan(158.9),
    }
    result = choose_max_data_job(
        family_decisions=decisions,
        suite_plans=plans,
        completed_suites=["economic-full"],
        free_disk_gib=250.0,
        all_targets_reached=False,
    )
    assert result["status"] == "READY"
    assert result["recommended_suite"] == "lead-lag-full"
    assert result["recommended_mode"] == "historical-deep"
    assert result["holdout_used_for_ranking"] is False
    assert result["target_contract"]["aggregate_substitution_allowed"] is False


def test_max_data_saute_une_suite_trop_grosse_sans_saturer_le_disque() -> None:
    decisions = [{"family": "copy_vault", "priority": 100, "phase": "COMPLETE_EVIDENCE"}]
    plans = {
        "economic-full": _plan(90.0),
        "copy-vault-full": _plan(4.0),
        "microstructure-full": _plan(6.0),
    }
    result = choose_max_data_job(
        family_decisions=decisions,
        suite_plans=plans,
        free_disk_gib=40.0,
        all_targets_reached=False,
        reserve_gib=25.0,
    )
    assert result["recommended_suite"] == "copy-vault-full"
    assert result["rejected_before_selection"][0]["reason"] == "INSUFFICIENT_DISK"


def test_max_data_sarrete_quand_les_trois_objectifs_independants_sont_prouves() -> None:
    decisions = [
        {"family": family, "priority": 20, "phase": "FREEZE_AND_CONFIRM_FORWARD"}
        for family in ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")
    ]
    assert targets_reached_from_brain(decisions) is True
    result = choose_max_data_job(
        family_decisions=decisions,
        suite_plans={"full-archive": _plan(158.9)},
        free_disk_gib=500.0,
        all_targets_reached=True,
    )
    assert result["status"] == "STOP_PROOF_REACHED"
    assert result["recommended_suite"] is None
    assert result["target_contract"]["target_net_usd_per_family"] == 4.0


def test_un_seul_module_atteint_ne_peut_pas_compter_comme_trois() -> None:
    decisions = [
        {"family": "copy_vault", "priority": 20, "phase": "FREEZE_AND_CONFIRM_FORWARD"},
        {"family": "lead_lag", "priority": 100, "phase": "MECHANISM_SEARCH"},
        {"family": "cross_venue_dislocation_v2", "priority": 100, "phase": "COMPLETE_EVIDENCE"},
    ]
    assert targets_reached_from_brain(decisions) is False
