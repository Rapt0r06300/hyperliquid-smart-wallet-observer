"""Le préflight dit « 8/8 démarreraient » — encore faut-il qu'il sache dire non.

POURQUOI CES TESTS. `tools/preflight_collecteurs.py` a rendu `TOUS_PRETS` du premier coup. Un
vert immédiat sur huit collecteurs est exactement le genre de résultat qu'il faut soupçonner :
un préflight qui ne détecte rien rend toujours vert, et une telle garde est pire qu'absente —
elle rassure avant le feu vert de l'opérateur, au moment où une panne coûte le plus.

On construit donc des collecteurs FACTICES dans un dossier temporaire, chacun cassé d'une façon
différente, et on exige le motif juste pour chacun. Le dépôt réel n'est jamais modifié.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import preflight_collecteurs as P  # noqa: E402


def _atelier(tmp_path: Path, nom_fichier: str, contenu: str) -> Path:
    (tmp_path / "tools").mkdir(exist_ok=True)
    cible = tmp_path / "tools" / nom_fichier
    cible.write_text(contenu, encoding="utf-8")
    return cible


def test_un_collecteur_sain_demarrerait(tmp_path: Path) -> None:
    _atelier(tmp_path, "sain.py",
             "import json" + chr(10) + "def main():" + chr(10) + "    return 0" + chr(10)
             + "if __name__ == '__main__':" + chr(10) + "    raise SystemExit(main())" + chr(10))
    bilan = P.verifier_un("sain", {"nom": "sain", "script": "tools/sain.py"}, tmp_path)
    assert bilan["verdict"] == "DEMARRERAIT", bilan


def test_un_script_ABSENT_est_vu(tmp_path: Path) -> None:
    bilan = P.verifier_un("fantome", {"nom": "fantome", "script": "tools/jamais_ecrit.py"}, tmp_path)
    assert bilan["verdict"] == "SCRIPT_ABSENT"
    assert any("jamais_ecrit" in m for m in bilan["motifs"])


def test_une_erreur_de_SYNTAXE_est_vue(tmp_path: Path) -> None:
    _atelier(tmp_path, "casse.py", "def main(:" + chr(10))
    bilan = P.verifier_un("casse", {"nom": "casse", "script": "tools/casse.py"}, tmp_path)
    assert bilan["verdict"] == "NE_COMPILE_PAS", bilan


def test_un_IMPORT_casse_est_vu(tmp_path: Path) -> None:
    """Le cas d'école : une dépendance absente ou une API retirée tue le collecteur."""
    _atelier(tmp_path, "import_casse.py",
             "import un_module_qui_nexiste_absolument_pas" + chr(10))
    bilan = P.verifier_un("import_casse",
                          {"nom": "import_casse", "script": "tools/import_casse.py"}, tmp_path)
    assert bilan["verdict"] == "IMPORTS_CASSES", bilan
    assert any("un_module_qui_nexiste" in m for m in bilan["motifs"]), bilan["motifs"]


def test_une_CONFIG_absente_est_vue(tmp_path: Path, monkeypatch) -> None:
    _atelier(tmp_path, "avec_config.py", "x = 1" + chr(10))
    monkeypatch.setitem(P.CONFIGS_REQUISES, "avec_config", ("config/manquante.json",))
    bilan = P.verifier_un("avec_config",
                          {"nom": "avec_config", "script": "tools/avec_config.py"}, tmp_path)
    assert bilan["verdict"] == "CONFIG_ABSENTE", bilan
    assert any("manquante.json" in m for m in bilan["motifs"])


def test_un_nom_INCONNU_du_registre_nest_pas_un_OK(tmp_path: Path) -> None:
    """Le plan exige un nom que personne ne déclare : ce doit être un refus, pas un silence."""
    bilan = P.verifier_un("inexistant", None, tmp_path)
    assert bilan["verdict"] == "INCONNU_DU_REGISTRE"
    assert bilan["motifs"], "le refus doit dire pourquoi"


def test_un_module_qui_AGIT_des_l_import_est_vu(tmp_path: Path, monkeypatch) -> None:
    """Un collecteur doit garder son point d'entrée : sinon l'import lance la collecte."""
    _atelier(tmp_path, "agit.py", "import time" + chr(10) + "time.sleep(30)" + chr(10))
    monkeypatch.setattr(P, "DELAI_IMPORT_S", 3)
    bilan = P.verifier_un("agit", {"nom": "agit", "script": "tools/agit.py"}, tmp_path)
    assert bilan["verdict"] == "AGIT_DES_L_IMPORT", bilan


def test_le_preflight_lit_le_CONTRAT_et_non_une_liste_recopiee() -> None:
    """Les 8 noms doivent venir du contrat : une liste recopiée se périme en silence."""
    from hl_observer.simulation.copy_vault_collection_contract import (
        COPY_VAULT_REQUIRED_COLLECTORS,
    )
    assert P.collecteurs_requis() == tuple(COPY_VAULT_REQUIRED_COLLECTORS)
    assert "userfills-poll" in P.collecteurs_requis()


def test_le_verdict_global_dit_ce_quil_ne_prouve_PAS() -> None:
    """Un préflight qui laisse croire qu'il prouve la collecte serait un faux succès."""
    bilan = P.preflight()
    limite = str(bilan.get("ce_que_ca_ne_prouve_pas") or "")
    assert "COLLECTERA" in limite.upper(), limite
    assert "reseau" in limite.casefold(), "dire qu'aucune requete n'a ete faite"
    # Et le verdict global doit rester lisible dans le JSON rendu par --json.
    rendu = json.loads(json.dumps(bilan, ensure_ascii=False))
    assert rendu["verdict"] in {"TOUS_PRETS", "AU_MOINS_UN_BLOQUE"}
