"""LE CORRECTIF D'ESSAIS MULTIPLES DOIT VOIR LES AUTRES TRANCHES.

Chercher un gagnant à travers dix-neuf tranches multiplie les chances d'en trouver un par hasard.
Une tranche qui se croirait seule publierait un seuil de signification trop permissif — et c'est
exactement ce qui serait arrivé, pour deux raisons successives trouvées le 18/11/2026 :

1. avant la correction, les dix-neuf tranches partageaient le dossier `{selection_digest}`, donc
   leurs essais se mélangeaient dans un seul `TRIALS.jsonl` et `seen` leur était commun ;
2. après avoir nommé les dossiers `{digest}-t{début}-{fin}`, `_prior_copy_vault_trial_count`
   passait ce nom à `_load_campaign_trials` comme digest — or ce lecteur **lève** sur un digest
   différent au lieu de filtrer. La deuxième tranche aurait planté.

Ces tests verrouillent le comportement voulu : la campagne courante s'exclut par son nom complet,
les autres tranches comptent, et un dossier tranché se lit avec le digest nu.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting import copy_vault_local_lab as LL
from hl_observer.backtesting.copy_vault_local_lab import parameter_hash

DIGEST = "a" * 64
AUTRE = "b" * 64


def _essai(digest: str, *, numero: int, parametres: dict) -> dict:
    return {
        "schema": "hypersmart.copy_vault_local_trial.v1",
        "selection_digest": digest,
        "sequence_index": numero,
        "trial_number": numero,
        "parameter_signature": parameter_hash(parametres),
        "parameters": parametres,
        "paper_read_only": True,
        "real_execution": False,
    }


def _registre(racine) -> None:
    """Le registre d'hypotheses doit exister : absent, la fonction rend `None` (« je ne sais pas »)
    et non zero. C'est un comportement voulu, verrouille par le dernier test de ce fichier."""
    chemin = racine / "runtime" / "codex_research" / "HYPOTHESIS_LEDGER.jsonl"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if not chemin.exists():
        chemin.write_text("", encoding="utf-8")


def _campagne(racine, nom: str, digest: str, essais: int) -> None:
    _registre(racine)
    dossier = racine / "runtime" / "codex_research" / "copy_vault_continuous_lab" / nom
    dossier.mkdir(parents=True, exist_ok=True)
    with open(dossier / "TRIALS.jsonl", "w", encoding="utf-8", newline="") as flux:
        for index in range(1, essais + 1):
            flux.write(json.dumps(_essai(digest, numero=index,
                                         parametres={"stop_loss_bps": 10 * index})) + "\n")


# ───────────────────────── le digest d'un dossier ─────────────────────────

def test_le_digest_est_extrait_d_un_dossier_TRANCHE():
    assert LL._digest_de_campagne(f"{DIGEST}-t1794528000000-1794531599999") == DIGEST


def test_le_digest_d_un_dossier_NON_tranche_est_lui_meme():
    assert LL._digest_de_campagne(DIGEST) == DIGEST


def test_un_dossier_inattendu_rend_son_nom_sans_lever():
    """Mieux vaut un digest qui ne correspondra à rien qu'une exception sur un dossier étranger."""
    assert LL._digest_de_campagne("brouillon") == "brouillon"


# ───────────────── un dossier tranché se lit, et ne fait pas lever ─────────────────

def test_une_campagne_TRANCHEE_est_comptee_sans_lever(tmp_path):
    """Le défaut n°2 : passer le nom du dossier comme digest faisait lever le lecteur de reçus."""
    _campagne(tmp_path, f"{DIGEST}-t1000-1999", DIGEST, 3)
    total = LL._prior_copy_vault_trial_count(tmp_path, exclude_campaign_name="autre-chose")
    assert total == 3


def test_les_essais_des_AUTRES_tranches_sont_comptes(tmp_path):
    """Le point qui compte pour l'honnêteté : la tranche 2 sait que la tranche 1 a cherché."""
    _campagne(tmp_path, f"{DIGEST}-t1000-1999", DIGEST, 4)
    _campagne(tmp_path, f"{DIGEST}-t2000-2999", DIGEST, 6)
    vu_par_la_seconde = LL._prior_copy_vault_trial_count(
        tmp_path, exclude_campaign_name=f"{DIGEST}-t2000-2999")
    assert vu_par_la_seconde == 4, "les 4 essais de la première tranche doivent compter"


def test_la_campagne_COURANTE_ne_se_compte_pas_elle_meme(tmp_path):
    _campagne(tmp_path, f"{DIGEST}-t1000-1999", DIGEST, 5)
    assert LL._prior_copy_vault_trial_count(
        tmp_path, exclude_campaign_name=f"{DIGEST}-t1000-1999") == 0


def test_une_campagne_d_une_AUTRE_source_compte_aussi(tmp_path):
    _campagne(tmp_path, AUTRE, AUTRE, 2)
    _campagne(tmp_path, f"{DIGEST}-t1000-1999", DIGEST, 3)
    assert LL._prior_copy_vault_trial_count(
        tmp_path, exclude_campaign_name=f"{DIGEST}-t1000-1999") == 2


def test_l_exclusion_par_DIGEST_reste_acceptee_pour_les_appelants_anciens(tmp_path):
    _campagne(tmp_path, DIGEST, DIGEST, 7)
    assert LL._prior_copy_vault_trial_count(tmp_path, exclude_selection_digest=DIGEST) == 0
    assert LL._prior_copy_vault_trial_count(tmp_path, exclude_selection_digest=AUTRE) == 7


def test_le_nom_de_campagne_PRIME_sur_le_digest_quand_les_deux_sont_donnes(tmp_path):
    """L'appelant réel passe les deux : le nom est le plus précis, il doit gagner."""
    _campagne(tmp_path, DIGEST, DIGEST, 2)
    _campagne(tmp_path, f"{DIGEST}-t1000-1999", DIGEST, 5)
    total = LL._prior_copy_vault_trial_count(
        tmp_path, exclude_selection_digest=DIGEST,
        exclude_campaign_name=f"{DIGEST}-t1000-1999")
    assert total == 2, "seule la tranche courante est retirée ; la campagne entière compte"


def test_un_recu_INCOHERENT_leve_toujours(tmp_path):
    """La réparation ne doit pas avoir transformé un lecteur strict en lecteur indulgent."""
    _registre(tmp_path)
    dossier = tmp_path / "runtime" / "codex_research" / "copy_vault_continuous_lab" / DIGEST
    dossier.mkdir(parents=True)
    with open(dossier / "TRIALS.jsonl", "w", encoding="utf-8", newline="") as flux:
        ligne = _essai(DIGEST, numero=1, parametres={"stop_loss_bps": 10})
        ligne["parameter_signature"] = "0" * 64        # ne correspond plus aux paramètres
        flux.write(json.dumps(ligne) + "\n")
    with pytest.raises(ValueError, match="identity mismatch"):
        LL._prior_copy_vault_trial_count(tmp_path, exclude_campaign_name="aucune")


def test_sans_aucune_campagne_le_compte_est_zero_pas_None(tmp_path):
    """`None` veut dire « registre absent » ; zéro veut dire « rien cherché ailleurs »."""
    (tmp_path / "runtime" / "codex_research").mkdir(parents=True)
    (tmp_path / "runtime" / "codex_research" / "HYPOTHESIS_LEDGER.jsonl").write_text(
        "", encoding="utf-8")
    assert LL._prior_copy_vault_trial_count(tmp_path, exclude_campaign_name="aucune") == 0


def test_un_registre_ABSENT_rend_None_et_non_zero(tmp_path):
    """Un zéro ferait croire qu'aucun essai n'a eu lieu ; None dit qu'on ne sait pas."""
    assert LL._prior_copy_vault_trial_count(tmp_path, exclude_campaign_name="aucune") is None
