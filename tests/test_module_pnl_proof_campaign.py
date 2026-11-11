import pytest

from hl_observer.control_plane.module_pnl_proof import prove_module


def test_proof_is_safe_only_and_net_of_costs():
    result = prove_module(
        "copy_vault",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 10,
            "fees": 2,
            "slippage": 1,
            "funding_financing": 1,
        }],
    )
    assert result["net_pnl"] == 6
    assert result["threshold_met"]


def test_default_threshold_is_current_five_usd_daily_contract():
    result = prove_module(
        "copy_vault",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 6,
            "fees": 1,
            "slippage": 0,
            "funding_financing": 0,
        }],
    )
    assert result["threshold_usd"] == 5.0
    assert result["threshold_met"]


def test_rejects_partial():
    with pytest.raises(ValueError):
        prove_module(
            "copy_vault",
            [{"quality_status": "PARTIAL", "replay_compatible": True}],
        )


def test_independent_verdict_classifies_missing_and_non_safe():
    from hl_observer.control_plane.module_pnl_proof import independent_module_verdict

    assert independent_module_verdict("copy_vault", [])["status"] == "MORE_DATA"
    result = independent_module_verdict(
        "copy_vault",
        [{"quality_status": "PARTIAL", "replay_compatible": True}],
    )
    assert result["status"] == "UNMEASURABLE"

def test_independent_verdict_emits_certificate_without_aggregation():
    from hl_observer.control_plane.module_pnl_proof import independent_module_verdict

    result = independent_module_verdict(
        "copy_vault",
        [{
            "quality_status": "SAFE",
            "replay_compatible": True,
            "gross_pnl": 10,
            "fees": 2,
            "slippage": 1,
            "funding_financing": 1,
        }],
    )
    assert result["status"] == "PROVEN"
    assert len(result["certificate_digest"]) == 64


def _safe_row(gross, fees=0.0, slippage=0.0, funding=0.0):
    return {"quality_status": "SAFE", "replay_compatible": True, "gross_pnl": gross, "fees": fees,
            "slippage": slippage, "funding_financing": funding}


def test_le_repere_cinq_usd_n_est_pas_une_porte_de_preuve():
    """Spec canonique : pas de seuil de profit terminal ; l'atteinte du repère est rapportée à part."""
    from hl_observer.control_plane.module_pnl_proof import independent_module_verdict

    sous_le_repere = independent_module_verdict("copy_vault", [_safe_row(4.0, fees=1.0)])
    assert sous_le_repere["net_pnl"] == 3.0
    assert sous_le_repere["status"] == "PROVEN" and sous_le_repere["reason"] == "NET_POSITIVE_AFTER_COSTS"
    assert sous_le_repere["reference_threshold_met"] is False
    assert sous_le_repere["threshold_is_evaluation_only"] is True

    for brut, frais in ((1.0, 1.0), (1.0, 2.0)):          # net nul ou négatif : jamais prouvé
        perdant = independent_module_verdict("copy_vault", [_safe_row(brut, fees=frais)])
        assert perdant["status"] == "REJECTED" and perdant["reason"] == "NET_NOT_POSITIVE_AFTER_COSTS"


def test_augmenter_un_cout_ne_peut_jamais_augmenter_le_net():
    """Métamorphique : à décisions identiques, tout coût supplémentaire réduit ou conserve le net."""
    base = prove_module("copy_vault", [_safe_row(10.0, 2.0, 1.0, 1.0), _safe_row(-3.0, 0.5, 0.2, -0.1)])
    for champ in ("fees", "slippage", "funding_financing"):
        lignes = [_safe_row(10.0, 2.0, 1.0, 1.0), _safe_row(-3.0, 0.5, 0.2, -0.1)]
        lignes[0][champ] += 0.75
        assert prove_module("copy_vault", lignes)["net_pnl"] == pytest.approx(base["net_pnl"] - 0.75)


@pytest.mark.parametrize("paused", ["lead_lag", "cross_venue_dislocation_v2", "carry"])
def test_paused_module_cannot_emit_pnl_proof(paused):
    with pytest.raises(ValueError, match="inactive"):
        prove_module(paused, [{"quality_status": "SAFE", "replay_compatible": True}])
