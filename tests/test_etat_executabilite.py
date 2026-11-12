"""La jauge d'exécutabilité lit le dernier rapport du labo et dit, en clair, quoi collecter."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))


def _mod():
    spec = importlib.util.spec_from_file_location("etat_executabilite", RACINE / "tools" / "etat_executabilite.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


E = _mod()


def _ecrire_run(root: Path, nom: str, economic: dict) -> None:
    run = root / "runtime" / "reports" / "copy_vault_quant_lab" / nom
    run.mkdir(parents=True, exist_ok=True)
    (run / "resultat.json").write_text(json.dumps({"economic_result": economic}), encoding="utf-8")


def test_prend_le_run_le_plus_recent_et_nomme_les_coins_a_collecter(tmp_path):
    _ecrire_run(tmp_path, "20261111T000000000000Z", {"train_executability": {"executable": False, "signaux_train": 1}})
    _ecrire_run(tmp_path, "20261112T120000000000Z", {"train_executability": {
        "executable": False, "signaux_train": 98138, "signaux_executables": 0,
        "refus_par_motif": {"STALE_OR_MISSING_REFERENCE_BOOK": 77008, "L2_CONNECTION_IDENTITY_INCOMPLETE": 14878},
        "explications": {"STALE_OR_MISSING_REFERENCE_BOOK": "aucun carnet dans les 30 secondes avant le signal",
                         "L2_CONNECTION_IDENTITY_INCOMPLETE": "carnets sans identité de connexion"},
        "coins_a_collecter": [{"coin": "xyz:SP500", "non_executables": 812,
                               "motif_principal": "STALE_OR_MISSING_REFERENCE_BOOK"}],
    }})
    rapport = E.dernier_rapport(tmp_path)
    assert rapport.parent.name == "20261112T120000000000Z"                   # le plus récent
    texte = "\n".join(E.rendre(E.lire_sonde(rapport), run_nom=rapport.parent.name))
    assert "PAS ENCORE MESURABLE" in texte and "98 138" in texte
    assert "aucun carnet dans les 30 secondes avant le signal" in texte
    assert "xyz:SP500" in texte and "812 bloqués" in texte
    assert "generer_coins_lanes.py cible déjà ces coins" in texte


def test_dit_quand_c_est_mesurable(tmp_path):
    _ecrire_run(tmp_path, "20261113T000000000000Z", {"train_executability": {
        "executable": True, "signaux_train": 5000, "signaux_executables": 1200}})
    texte = "\n".join(E.rendre(E.lire_sonde(E.dernier_rapport(tmp_path))))
    assert "✅ MESURABLE" in texte and "1 200 signaux" in texte


def test_sans_blocage_enregistre_ne_panique_pas(tmp_path):
    _ecrire_run(tmp_path, "20261113T000000000000Z", {"status": "SEARCH_RUNNING"})   # pas de train_executability
    assert E.lire_sonde(E.dernier_rapport(tmp_path)) == {}
    texte = "\n".join(E.rendre({}))
    assert "aucun blocage" in texte or "aucun rapport" in texte


def test_main_sans_rapport(tmp_path, capsys):
    assert E.main(["--root", str(tmp_path)]) == 2
    assert "aucun rapport" in capsys.readouterr().out


def test_main_json(tmp_path, capsys):
    _ecrire_run(tmp_path, "20261113T000000000000Z", {"train_executability": {"executable": True, "signaux_train": 3}})
    assert E.main(["--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["executable"] is True
