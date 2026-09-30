"""Shardage CI : une partition, pas un échantillon.

Découper la suite pour tenir dans le budget CI n'a de valeur que si **aucun test ne disparaît**. Un test qui
ne tourne plus est pire qu'un test lent : il donne une CI verte qui ne prouve rien. Ces tests verrouillent
la partition et le déterminisme.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import ci_shard as CS  # noqa: E402

from tests import coverage_contract_harness as coverage_harness  # noqa: E402


def test_la_partition_est_complete_et_sans_doublon():
    fichiers = CS.fichiers_de_test(RACINE)
    assert len(fichiers) > 100, "la suite reelle doit etre decouverte"
    for total in (1, 2, 3, 6, 8, 13):
        v = CS.verifier_partition(fichiers, total)
        assert v["partition_valide"] is True, total
        assert v["sans_doublon"] is True and v["complet"] is True


def test_les_shards_sont_equilibres():
    fichiers = CS.fichiers_de_test(RACINE)
    tailles = CS.verifier_partition(fichiers, 6)["tailles"]
    assert max(tailles) - min(tailles) <= 1        # round-robin : au plus un fichier d'ecart


def test_le_decoupage_est_deterministe():
    fichiers = CS.fichiers_de_test(RACINE)
    assert CS.shard(fichiers, 3, 6) == CS.shard(fichiers, 3, 6)
    assert CS.shard(list(reversed(fichiers)), 3, 6) != [] or not fichiers


def test_ce_fichier_appartient_a_exactement_un_shard():
    fichiers = CS.fichiers_de_test(RACINE)
    moi = "tests/test_ci_shard.py"
    assert moi in fichiers
    appartenances = [i for i in range(1, 7) if moi in CS.shard(fichiers, i, 6)]
    assert len(appartenances) == 1


def test_un_index_hors_bornes_est_refuse():
    for index, total in ((0, 6), (7, 6), (-1, 6)):
        with pytest.raises(ValueError):
            CS.shard(["a", "b"], index, total)
    with pytest.raises(ValueError):
        CS.shard(["a"], 1, 0)


def test_shard_unique_rend_tout():
    fichiers = CS.fichiers_de_test(RACINE)
    assert CS.shard(fichiers, 1, 1) == fichiers


def test_plus_de_shards_que_de_fichiers_ne_perd_rien():
    fichiers = ["tests/a.py", "tests/b.py"]
    v = CS.verifier_partition(fichiers, 5)
    assert v["partition_valide"] is True and sorted(v["tailles"]) == [0, 0, 0, 1, 1]


def test_dossier_absent_rend_une_liste_vide(tmp_path):
    assert CS.fichiers_de_test(tmp_path) == []


def test_le_cli_verifie_la_partition(capsys):
    assert CS.main(["1", "6", "--root", str(RACINE), "--verifier"]) == 0
    assert "partition_valide': True" in capsys.readouterr().out


def test_le_cli_rend_des_chemins_utilisables_par_pytest(capsys):
    assert CS.main(["2", "6", "--root", str(RACINE)]) == 0
    sortie = capsys.readouterr().out.strip()
    chemins = sortie.split(" ")
    assert chemins and all(c.startswith("tests/") and c.endswith(".py") for c in chemins)


def test_les_contrats_coverage_lourds_exigent_un_shard_explicite(monkeypatch):
    monkeypatch.delenv("HYPERSMART_COVERAGE_CONTRACT_SHARD", raising=False)
    with pytest.raises(pytest.skip.Exception):
        coverage_harness.require_explicit_coverage_shard()

    monkeypatch.setenv("HYPERSMART_COVERAGE_CONTRACT_SHARD", "7")
    monkeypatch.setenv("COVERAGE_SHARDS", "32")
    assert coverage_harness.require_explicit_coverage_shard() == (7, 32)

    monkeypatch.setenv("HYPERSMART_COVERAGE_CONTRACT_SHARD", "32")
    with pytest.raises(AssertionError, match="shard coverage invalide"):
        coverage_harness.require_explicit_coverage_shard()


# ═══════════════ le workflow lui-même ═══════════════
def _ci() -> str:
    return (RACINE / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _lignes_actives() -> list[str]:
    """Lignes YAML hors commentaires — une mention en commentaire n'est pas une configuration."""
    return [ligne for ligne in _ci().splitlines() if not ligne.strip().startswith("#")]


def test_le_workflow_declenche_bien_sur_main_et_a_la_demande():
    src = _ci()
    assert "workflow_dispatch" in src
    assert "branches: [main]" in src
    actives = _lignes_actives()
    assert not any("paths-ignore:" in ligne for ligne in actives), \
        "un paths-ignore empecherait un commit main de produire un statut"
    assert not any(ligne.strip().startswith("if:") and "github.ref" in ligne for ligne in actives), \
        "une condition sur la ref pourrait masquer les commits main"


def test_le_workflow_teste_le_runtime_reel_pas_le_legacy():
    src = _ci()
    assert "hl_observer.market_truth" in src and "hl_observer.ops.global_observer_pipeline" in src
    assert "compileall hyper_smart_observer" not in src, "l'ancien CI ne testait que le paquet legacy"


def test_le_workflow_ne_lance_jamais_la_suite_entiere_dun_bloc():
    """`pytest -q` nu sous un timeout court etait la cause racine de l'absence de statut."""
    src = _ci()
    for ligne in src.splitlines():
        nu = ligne.strip()
        assert nu not in {"run: pytest -q", "run: python -m pytest -q"}, nu
    assert "ci_shard.py" in src


def test_le_workflow_a_un_job_windows_et_publie_ses_artefacts():
    src = _ci()
    assert "windows-latest" in src
    assert "upload-artifact" in src and "if: always()" in src
    assert "junitxml" in src


def test_le_workflow_nexige_aucun_secret():
    src = _ci()
    assert "secrets." not in src, "les tests paper/read-only ne doivent exiger aucun secret"


def test_le_workflow_verrouille_lexecution():
    src = _ci()
    assert 'HL_ENABLE_MAINNET_EXECUTION: "0"' in src
    assert 'HL_ENABLE_TESTNET_EXECUTION: "0"' in src
    assert "python-version: '3.11'" in src


def test_le_workflow_a_concurrency_cache_et_timeouts():
    src = _ci()
    assert "concurrency:" in src and "cancel-in-progress" in src
    assert "cache: pip" in src and "timeout-minutes:" in src
