"""Le gel économique V21 : chaque invariant rompu doit se NOMMER, jamais passer.

POURQUOI CE MODULE MÉRITE SES TESTS. C'est la porte d'entrée du moteur gelé : elle décide
si un jeu de paramètres figé est exploitable avant toute évaluation. Un gel accepté à tort
rendrait un PnL calculé sur des paramètres qui ne sont pas ceux qu'on croit — et le contrat
`paper_read_only` / `real_execution` passe par ici. Un refus muet ou trop permissif n'est
donc pas un détail de forme.

MÉTHODE. Les tests construisent un gel VALIDE avec la vraie fonction d'empreinte
(`parameter_hash`), puis cassent **un** invariant à la fois et exigent le code de refus
exact. Un test qui vérifierait seulement « ça lève » laisserait passer un refus qui se
trompe de cause, et donc une recherche à l'aveugle le jour où ça casse.

ORDRE DES CHRONOLOGIES. Les bornes doivent être strictement enchaînées
(train → validation → OOS → gel) : si la validation commençait avant la fin du train, le
même instant servirait à choisir ET à juger — c'est la définition d'une fuite de données.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_v21_frozen import (  # noqa: E402
    MAX_GROSS_EXPOSURE_USD,
    PROTOCOL,
)
from hl_observer.backtesting.copy_vault_v21_verification_du_gel import (  # noqa: E402
    _verified_freeze,
    verifier_le_gel,
)
from hl_observer.simulation.economic_freeze_registry import parameter_hash  # noqa: E402


def _parametres() -> dict:
    return {
        "protocol": PROTOCOL,
        "paper_read_only": True,
        "real_execution": False,
        "training_selection_eligible": True,
        "minimum_leader_fill_notional_usd": 250.0,
        "signed_depth_imbalance_minimum": 0.25,
        "core_notional_usd": 100.0,
        "probe_notional_usd": 25.0,
        "daily_profit_lock_usd": 10.0,
        "stop_loss_bps": 30.0,
        "take_profit_bps": 60.0,
        "horizon_ms": 3_600_000,
        "vault_daily_limit": 4,
        "coin_daily_limit": 2,
        "max_open_positions": 3,
        "bonferroni_trial_count": 12,
        "bounds": {
            "train_start_ms": 1_700_000_000_000,
            "train_end_ms": 1_700_086_400_000,
            "validation_start_ms": 1_700_086_400_001,
            "validation_end_ms": 1_700_172_800_000,
            "oos_start_ms": 1_700_172_800_001,
            "oos_end_ms": 1_700_259_200_000,
        },
    }


def _gel(parametres: dict | None = None, **remplacements) -> dict:
    parametres = dict(parametres or _parametres())
    row = {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "family": "copy_vault",
        "selected_before_final_evaluation": True,
        "parameters": parametres,
        "parameters_sha256": parameter_hash(parametres),
        "frozen_at_ms": 1_700_259_200_001,
    }
    row.update(remplacements)
    return row


def test_un_gel_coherent_est_accepte_et_rendu_tel_quel():
    rendu = verifier_le_gel(_gel())
    assert rendu["family"] == "copy_vault"
    assert rendu["parameters"]["protocol"] == PROTOCOL
    # L'ancien nom reste expose : les appelants existants ne doivent pas casser.
    assert _verified_freeze is verifier_le_gel


def test_le_gel_imbrique_sous_la_clef_freeze_est_accepte():
    """Le reçu du moteur enveloppe parfois le gel : les deux formes doivent passer."""
    assert verifier_le_gel({"freeze": _gel()})["family"] == "copy_vault"


@pytest.mark.parametrize(
    ("remplacement", "code"),
    [
        ({"schema_version": "autre.v9"}, "COPY_V21_FREEZE_INVALID"),
        ({"family": "market"}, "COPY_V21_FREEZE_INVALID"),
        ({"selected_before_final_evaluation": False}, "COPY_V21_FREEZE_INVALID"),
        ({"parameters": "pas un mapping"}, "COPY_V21_FREEZE_INVALID"),
        ({"frozen_at_ms": 0}, "COPY_V21_FREEZE_TIMESTAMP_INVALID"),
    ],
)
def test_chaque_invariant_de_l_enveloppe_porte_son_code(remplacement, code):
    with pytest.raises(ValueError, match=code):
        verifier_le_gel(_gel(**remplacement))


def test_le_contrat_de_securite_est_refuse_nommement():
    """LE garde-fou : un gel qui pretend pouvoir executer reellement est rejete."""
    for casse in ({"real_execution": True}, {"paper_read_only": False}):
        parametres = _parametres()
        parametres.update(casse)
        with pytest.raises(ValueError, match="COPY_V21_SAFETY_CONTRACT_MISMATCH"):
            verifier_le_gel(_gel(parametres))


def test_une_empreinte_qui_ne_correspond_pas_est_refusee():
    """Les parametres ont ete modifies APRES le gel : le PnL ne porterait pas sur eux."""
    row = _gel()
    row["parameters_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="COPY_V21_FREEZE_HASH_MISMATCH"):
        verifier_le_gel(row)


def test_un_protocole_different_est_refuse():
    parametres = _parametres()
    parametres["protocol"] = PROTOCOL + "-modifie"
    with pytest.raises(ValueError, match="COPY_V21_PROTOCOL_MISMATCH"):
        verifier_le_gel(_gel(parametres))


@pytest.mark.parametrize(
    "casse",
    [
        {"stop_loss_bps": 0.0},                     # non strictement positif
        {"horizon_ms": float("inf")},               # non fini
        {"signed_depth_imbalance_minimum": 1.5},    # hors [-1, 1]
        {"vault_daily_limit": 2.5},                 # un compteur doit etre entier
        {"minimum_leader_fill_notional_usd": "250"},  # type inattendu
    ],
)
def test_un_parametre_absurde_est_refuse_sans_arrondi(casse):
    parametres = _parametres()
    parametres.update(casse)
    with pytest.raises(ValueError, match="COPY_V21_FREEZE_PARAMETERS_INVALID"):
        verifier_le_gel(_gel(parametres))


def test_un_parametre_obligatoire_absent_est_refuse():
    parametres = _parametres()
    del parametres["take_profit_bps"]
    with pytest.raises(ValueError, match="COPY_V21_FREEZE_PARAMETERS_INVALID"):
        verifier_le_gel(_gel(parametres))


def test_le_notionnel_papier_ne_depasse_jamais_le_plafond_d_exposition():
    parametres = _parametres()
    parametres["core_notional_usd"] = float(MAX_GROSS_EXPOSURE_USD) + 1.0
    with pytest.raises(ValueError, match="COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED"):
        verifier_le_gel(_gel(parametres))


@pytest.mark.parametrize(
    "casse",
    [
        {"validation_start_ms": 1_700_000_000_000},   # commence AVANT la fin du train
        {"oos_start_ms": 1_700_086_400_000},          # OOS avant la fin de validation
        {"train_end_ms": 1_699_000_000_000},          # fin avant le debut
        {"oos_end_ms": 0},                            # borne non positive
    ],
)
def test_une_chronologie_qui_fuite_est_refusee(casse):
    """Si la validation commence avant la fin du train, le meme instant choisit ET juge."""
    parametres = _parametres()
    parametres["bounds"] = {**parametres["bounds"], **casse}
    with pytest.raises(ValueError, match="COPY_V21_FREEZE_BOUNDS_INVALID"):
        verifier_le_gel(_gel(parametres))


def test_un_gel_pose_avant_la_fin_de_l_OOS_est_refuse():
    """Geler avant la fin de la periode jugee laisserait choisir en connaissant le resultat."""
    with pytest.raises(ValueError, match="COPY_V21_FREEZE_BOUNDS_INVALID"):
        verifier_le_gel(_gel(frozen_at_ms=1_700_172_800_000))


def test_des_bornes_absentes_ou_mal_typees_sont_refusees():
    for bornes in (None, "deux dates", {}, {"train_start_ms": 1}):
        parametres = _parametres()
        parametres["bounds"] = bornes
        with pytest.raises(ValueError, match="COPY_V21_FREEZE_BOUNDS_INVALID"):
            verifier_le_gel(_gel(parametres))
