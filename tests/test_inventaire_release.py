"""[RELEASE] Moteur de completude : inventaire + cloture d'imports + references .cmd + controle qui
BLOQUE si un requis manque/vide/exclu ou un import casse. Plus un verrou PERMANENT : le vrai depot est
complet, donc tout nouveau module/test/config non inclus fera echouer ce test. 0 reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import inventaire_release as IR       # noqa: E402


def _mini_projet(root: Path):
    """Petit projet valide : 2 modules (dont __init__), 1 test, 1 config, 1 .cmd qui reference tout."""
    pkg = root / "src" / "hl_observer"
    (pkg / "ops").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "ops" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "ops" / "moteur.py").write_text("from hl_observer.ops.util import X\n", encoding="utf-8")
    (pkg / "ops" / "util.py").write_text("X = 1\n", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "outil.py").write_text("print(1)\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "reglages.yaml").write_text("a: 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "requirements-portable.txt").write_text("numpy>=1\n", encoding="utf-8")
    (root / "LANCER_HYPERSMART.cmd").write_text(
        'cd /d "%~dp0"\n"%HYPERSMART_PYTHON%" -m hl_observer.ops.moteur\n'
        '"%HYPERSMART_PYTHON%" tools\\outil.py\n', encoding="utf-8")
    (root / "ANALYSER_BACKTESTS_REPLAYS.cmd").write_text('cd /d "%~dp0"\n', encoding="utf-8")
    (root / "CREER_ARCHIVE_PORTABLE.cmd").write_text('cd /d "%~dp0"\n', encoding="utf-8")


def _tous_les_fichiers(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_inventaire_categorise(tmp_path):
    _mini_projet(tmp_path)
    archive_machine = tmp_path / "archive" / "ancienne-machine"
    archive_machine.mkdir(parents=True)
    (archive_machine / "trace.txt").write_text(r"C:\\Users\\machine\\runtime.db", encoding="utf-8")
    inv = IR.inventaire(tmp_path)
    assert "src/hl_observer/ops/moteur.py" in inv["modules"]
    assert "tools/outil.py" in inv["tools_py"]
    assert "tests/test_x.py" in inv["tests"]
    assert "config/reglages.yaml" in inv["configs"]
    assert "LANCER_HYPERSMART.cmd" in inv["cmd"]
    assert all(not path.startswith("archive/") for paths in inv.values() for path in paths)


def test_cloture_imports_resout_et_detecte_casse(tmp_path):
    _mini_projet(tmp_path)
    clo = IR.cloture_imports(tmp_path)
    assert "src/hl_observer/ops/util.py" in clo["requis"] and clo["casses"] == []
    # casse un import DIRECT : moteur importe un sous-module inexistant (doit etre un module present).
    (tmp_path / "src" / "hl_observer" / "ops" / "moteur.py").write_text(
        "import hl_observer.ops.fantome\n", encoding="utf-8")
    clo2 = IR.cloture_imports(tmp_path)
    assert any(c["module"] == "hl_observer.ops.fantome" for c in clo2["casses"])


def test_cloture_imports_resout_import_relatif(tmp_path):
    _mini_projet(tmp_path)
    (tmp_path / "src" / "hl_observer" / "ops" / "moteur.py").write_text(
        "from .util import X\n", encoding="utf-8")
    clo = IR.cloture_imports(tmp_path)
    assert clo["casses"] == []
    assert "src/hl_observer/ops/util.py" in clo["requis"]


def test_import_garde_par_try_except_est_optionnel(tmp_path):
    _mini_projet(tmp_path)
    # import best-effort d'un module absent, sous try/except : NE casse PAS la release.
    (tmp_path / "src" / "hl_observer" / "ops" / "moteur.py").write_text(
        "try:\n    from hl_observer.ops.optionnel import f\nexcept Exception:\n    f = None\n",
        encoding="utf-8")
    clo = IR.cloture_imports(tmp_path)
    assert clo["casses"] == []                              # garde -> tolere


def test_references_cmd(tmp_path):
    _mini_projet(tmp_path)
    refs = IR.references_cmd(tmp_path)
    assert "src/hl_observer/ops/moteur.py" in refs["requis"]
    assert "tools/outil.py" in refs["requis"] and refs["manquants"] == []
    # supprime l'outil reference -> manquant detecte.
    (tmp_path / "tools" / "outil.py").unlink()
    assert "tools/outil.py" in IR.references_cmd(tmp_path)["manquants"]


def test_references_dynamiques_et_ressources(tmp_path):
    _mini_projet(tmp_path)
    (tmp_path / "config" / "modele.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "src" / "hl_observer" / "ops" / "moteur.py").write_text(
        "import importlib\n"
        "from pathlib import Path\n"
        "M = importlib.import_module('hl_observer.ops.util')\n"
        "CFG = Path('config/modele.json').read_text()\n",
        encoding="utf-8",
    )
    refs = IR.references_dynamiques(tmp_path)
    assert refs["manquants"] == []
    assert "src/hl_observer/ops/util.py" in refs["requis"]
    assert "config/modele.json" in refs["requis"]


def test_reference_dynamique_absente_bloque_completude(tmp_path):
    _mini_projet(tmp_path)
    (tmp_path / "src" / "hl_observer" / "ops" / "moteur.py").write_text(
        "open('config/obligatoire.json', 'r', encoding='utf-8')\n", encoding="utf-8")
    v = IR.controle_completude(tmp_path, _tous_les_fichiers(tmp_path))
    assert v["complet"] is False
    assert any(x["reference"] == "config/obligatoire.json"
               for x in v["references_dynamiques_manquantes"])


def test_outils_scripts_certificats_et_fixtures_sont_requis(tmp_path):
    _mini_projet(tmp_path)
    (tmp_path / "tools" / "helper.ps1").write_text("Write-Output ok\n", encoding="utf-8")
    (tmp_path / "tests" / "fixtures").mkdir()
    (tmp_path / "tests" / "fixtures" / "sample.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "ca.pem").write_text("PUBLIC CA\n", encoding="utf-8")
    requis = IR.fichiers_requis(tmp_path)
    assert "tools/helper.ps1" in requis
    assert "tests/fixtures/sample.jsonl" in requis
    assert "ca.pem" in requis


def test_completude_ok_sur_projet_complet(tmp_path):
    _mini_projet(tmp_path)
    v = IR.controle_completude(tmp_path, _tous_les_fichiers(tmp_path))
    assert v["complet"] is True


def test_completude_bloque_si_module_exclu(tmp_path):
    _mini_projet(tmp_path)
    inclus = _tous_les_fichiers(tmp_path) - {"src/hl_observer/ops/util.py"}   # exclu par erreur
    v = IR.controle_completude(tmp_path, inclus)
    assert v["complet"] is False and "src/hl_observer/ops/util.py" in v["exclus_par_erreur"]


def test_completude_bloque_si_requis_vide_mais_init_vide_ok(tmp_path):
    _mini_projet(tmp_path)
    (tmp_path / "src" / "hl_observer" / "ops" / "util.py").write_text("", encoding="utf-8")  # requis VIDE
    v = IR.controle_completude(tmp_path, _tous_les_fichiers(tmp_path))
    assert v["complet"] is False and "src/hl_observer/ops/util.py" in v["vides"]
    # mais un __init__.py vide reste OK (marqueur de paquet).
    (tmp_path / "src" / "hl_observer" / "ops" / "util.py").write_text("X=1\n", encoding="utf-8")
    assert IR.controle_completude(tmp_path, _tous_les_fichiers(tmp_path))["complet"] is True


def test_completude_signale_non_suivis_requis(tmp_path):
    _mini_projet(tmp_path)
    v = IR.controle_completude(tmp_path, _tous_les_fichiers(tmp_path),
                               non_suivis=["src/hl_observer/ops/util.py"])
    assert "src/hl_observer/ops/util.py" in v["non_suivis_requis"]


# ── VERROU PERMANENT : le vrai depot est complet (auto-inclusion garantie) ────────────────────
def test_le_vrai_depot_est_complet_et_ferme():
    # tout module/test/config du depot doit resoudre : imports fermes, references .cmd presentes.
    clo = IR.cloture_imports(RACINE)
    assert clo["casses"] == [], "imports intra-projet casses : %s" % clo["casses"][:10]
    refs = IR.references_cmd(RACINE)
    assert refs["manquants"] == [], "references .cmd manquantes : %s" % refs["manquants"]


def test_le_vrai_depot_est_inclus_par_l_archive():
    # LE verrou anti-oubli : tout fichier REQUIS est bien dans la selection de l'archive. Un nouveau
    # module/collecteur/test/config ajoute plus tard sans etre inclus fera ECHOUER ce test.
    from hl_observer.ops import archive_portable as AP
    inclus, _ = AP.lister_pour_archive(RACINE)
    v = IR.controle_completude(RACINE, inclus)
    assert v["complet"] is True, IR.formater(v)
