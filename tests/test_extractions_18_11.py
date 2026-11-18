"""LES DEUX EXTRACTIONS DU 18/11/2026 : les noms doivent rester là où on les cherche.

`test_invariants_architecture.py::test_pas_de_nouveau_fichier_geant` a refusé deux fichiers que mes
ajouts du jour avaient fait franchir leur plafond :

    backtesting/copy_vault_local_lab.py    5 027 lignes  (plafond historique 5 009)
    backtesting/copy_vault_book_loader.py    820 lignes  (plafond général      800)

Son message dit la bonne chose — « corriger le câblage au lieu de relever le plafond » — donc deux
modules cohérents ont été extraits plutôt que deux plafonds relevés.

Le risque d'une extraction n'est pas le code déplacé : c'est un import qui ne suit pas. Ces tests
vérifient que chaque nom reste accessible où ses appelants le cherchent, et que les deux chemins
désignent bien le même objet — pas une copie qui divergera.
"""
from __future__ import annotations

import pytest


def test_le_labo_expose_toujours_l_identite_de_campagne():
    """Les tests et le code appellent `local_lab._nom_de_campagne` : le nom doit survivre."""
    from hl_observer.backtesting import copy_vault_identite_campagne as IC
    from hl_observer.backtesting import copy_vault_local_lab as LL

    assert LL._nom_de_campagne is IC.nom_de_campagne, "le même objet, pas une copie"
    assert LL._digest_de_campagne is IC.digest_de_campagne


def test_le_chargeur_REEXPORTE_les_validateurs_de_carnet():
    """`tests/test_liquidity_contracts_081_090.py` les importe du chargeur, pas du module neuf."""
    from hl_observer.backtesting import copy_vault_book_loader as BL
    from hl_observer.backtesting import copy_vault_carnet_validation as CV

    assert BL.validate_complete_causal_l2 is CV.validate_complete_causal_l2
    assert BL.future_book_access_receipt is CV.future_book_access_receipt
    assert "validate_complete_causal_l2" in BL.__all__
    assert "future_book_access_receipt" in BL.__all__


def test_les_deux_nouveaux_modules_s_importent_A_FROID():
    """Un module extrait qui dépend circulairement de son origine casse à l'import seul."""
    import subprocess
    import sys

    for module in (
        "hl_observer.backtesting.copy_vault_identite_campagne",
        "hl_observer.backtesting.copy_vault_carnet_validation",
    ):
        issue = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True, text=True, timeout=120,
        )
        assert issue.returncode == 0, f"{module} : {issue.stderr[-400:]}"


# ───────────────────── le comportement, pas seulement les noms ─────────────────────

def test_l_identite_de_campagne_separe_bien_deux_tranches():
    from hl_observer.backtesting.copy_vault_identite_campagne import (
        digest_de_campagne,
        est_tranchee,
        nom_de_campagne,
    )

    digest = "a" * 64
    sans = nom_de_campagne(digest, None)
    avec = nom_de_campagne(digest, (1_000, 1_999))
    autre = nom_de_campagne(digest, (2_000, 2_999))
    assert sans == digest and est_tranchee(sans) is False
    assert avec != autre and est_tranchee(avec) is True
    # les reçus portent le digest NU : on doit pouvoir le retrouver depuis les deux noms
    assert digest_de_campagne(sans) == digest_de_campagne(avec) == digest


def test_un_carnet_du_FUTUR_est_rejete_et_non_corrige():
    """La frontière qui empêche de lire l'avenir pour décider du passé."""
    from hl_observer.backtesting.copy_vault_carnet_validation import validate_complete_causal_l2

    carnet = {"ts_ms": 2_000, "bid": 99.0, "ask": 101.0,
              "bids5": [[99.0, 10.0]], "asks5": [[101.0, 10.0]]}
    assert validate_complete_causal_l2(carnet, as_of_ms=1_000)["status"] == "REJECTED"
    assert validate_complete_causal_l2(carnet, as_of_ms=2_000)["status"] == "PROVEN"


def test_un_carnet_INCOMPLET_est_UNMEASURABLE_et_non_rejete():
    """« Cette donnée ne dit rien » et « cette donnée dit non » ne se confondent pas."""
    from hl_observer.backtesting.copy_vault_carnet_validation import validate_complete_causal_l2

    resultat = validate_complete_causal_l2({"ts_ms": 1_000, "bid": 99.0}, as_of_ms=1_000)
    assert resultat["status"] == "UNMEASURABLE" and resultat["reason"] == "L2_INCOMPLETE"


def test_un_carnet_a_UN_SEUL_cote_est_refuse():
    """Son spread serait inventé."""
    from hl_observer.backtesting.copy_vault_carnet_validation import validated_recorded_levels

    valide, raison = validated_recorded_levels(
        {"bids5": [[99.0, 10.0]]}, bid=99.0, ask=101.0)
    assert valide is None and raison == "L2_SIDE_MISSING"


def test_un_carnet_SANS_niveaux_reste_utilisable():
    """Le meilleur prix suffit pour certaines mesures : l'absence de niveaux n'est pas un défaut."""
    from hl_observer.backtesting.copy_vault_carnet_validation import validated_recorded_levels

    valide, raison = validated_recorded_levels({}, bid=99.0, ask=101.0)
    assert valide == (None, None) and raison is None


@pytest.mark.parametrize("coupure", (0, -1, 1.0, "1000", None))
def test_une_coupure_INVALIDE_rend_UNMEASURABLE_jamais_PROVEN(coupure):
    from hl_observer.backtesting.copy_vault_carnet_validation import validate_complete_causal_l2

    carnet = {"ts_ms": 1_000, "bid": 99.0, "ask": 101.0,
              "bids5": [[99.0, 10.0]], "asks5": [[101.0, 10.0]]}
    resultat = validate_complete_causal_l2(carnet, as_of_ms=coupure)
    assert resultat["status"] == "UNMEASURABLE" and resultat["reason"] == "CUTOFF_INVALID"


def test_le_recu_d_acces_au_futur_porte_toujours_sa_trace():
    from hl_observer.backtesting.copy_vault_carnet_validation import future_book_access_receipt

    carnet = {"ts_ms": 1_000, "bid": 99.0, "ask": 101.0,
              "bids5": [[99.0, 10.0]], "asks5": [[101.0, 10.0]]}
    recu = future_book_access_receipt(carnet, as_of_ms=1_000)
    assert recu["verdict"] == "PROVEN"
    assert recu["future_snapshot_never_admitted"] is True
    assert recu["paper_read_only"] is True and recu["real_execution"] is False
# ───────── deux tranches ne fabriquent pas le même identifiant de candidat ─────────
# `candidate_id` combinait le digest de la source — identique pour toutes les tranches — et un
# numéro de séquence tiré du `CHECKPOINT.json` de la campagne, qui repart à 1 dans chaque tranche.
# Deux tranches produisaient donc `cv-{digest12}-000000000001`, et la garde d'immuabilité du
# registre levait `IMMUTABLE_COPY_VAULT_CANDIDATE_CONFLICT` sur la seconde — elle avait raison :
# deux objets différents ne peuvent pas porter le même nom.

def test_deux_tranches_ont_des_empreintes_de_tranche_differentes():
    from hl_observer.backtesting.copy_vault_identite_campagne import empreinte_de_tranche

    a = empreinte_de_tranche((1_000, 1_999))
    b = empreinte_de_tranche((2_000, 2_999))
    assert a != b and len(a) == len(b) == 8, "longueur fixe : les identifiants restent alignés"


def test_SANS_tranche_l_empreinte_est_VIDE_donc_le_format_reste_l_ancien():
    from hl_observer.backtesting.copy_vault_identite_campagne import empreinte_de_tranche

    assert empreinte_de_tranche(None) == ""


def test_la_meme_tranche_donne_toujours_la_meme_empreinte():
    """Sinon une reprise ne retrouverait pas ses propres candidats."""
    from hl_observer.backtesting.copy_vault_identite_campagne import empreinte_de_tranche

    assert empreinte_de_tranche((7, 9)) == empreinte_de_tranche((7, 9))


def test_l_identifiant_de_candidat_PORTE_la_tranche():
    import inspect

    from hl_observer.backtesting import copy_vault_local_lab as LL

    source = inspect.getsource(LL.run_local_campaign)
    assert 'candidate_id = (' in source
    assert '_marqueur_de_tranche' in source
    # le marqueur vaut "" sans tranche : le format d'origine est alors reconstruit à l'identique
    assert '_marqueur_de_tranche = f"{_empreinte_tranche}-" if _empreinte_tranche else ""' in source


def test_le_format_SANS_tranche_est_byte_pour_byte_l_ancien():
    """La non-régression qui protège les reçus déjà écrits."""
    from hl_observer.backtesting.copy_vault_identite_campagne import empreinte_de_tranche

    digest, sequence = "a" * 64, 1
    marqueur = empreinte_de_tranche(None)
    marqueur = f"{marqueur}-" if marqueur else ""
    assert f"cv-{digest[:12]}-{marqueur}{sequence:012d}" == "cv-aaaaaaaaaaaa-000000000001"


def test_le_format_AVEC_tranche_est_distinct_et_lisible():
    from hl_observer.backtesting.copy_vault_identite_campagne import empreinte_de_tranche

    digest = "a" * 64
    empreinte = empreinte_de_tranche((1_000, 1_999))
    identifiant = f"cv-{digest[:12]}-{empreinte}-{1:012d}"
    assert identifiant != "cv-aaaaaaaaaaaa-000000000001"
    assert identifiant.startswith("cv-aaaaaaaaaaaa-") and identifiant.endswith("-000000000001")


# ───────── un candidat gelé porte sa fenêtre, sinon il n'est comparable à rien ─────────

def test_le_recu_du_candidat_gele_PORTE_sa_tranche():
    """Dix-neuf tranches gèlent sous le MÊME `selection_digest` et la même `classification`."""
    import inspect

    from hl_observer.backtesting import copy_vault_local_lab as LL

    source = inspect.getsource(LL.record_frozen_candidate)
    assert '"tranche": economic_result.get("tranche")' in source
    assert '"verdict_partiel": economic_result.get("verdict_partiel") is True' in source

