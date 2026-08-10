"""L'audit de portabilité détecte les dépendances machine, pas les diagnostics qui les décrivent."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import audit_portabilite as A  # noqa: E402


def _cats(violations):
    return {v["categorie"] for v in violations}


def test_detecte_chemin_absolu_disque(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.py").write_text('CHEMIN = "C:\\\\Users\\\\flo\\\\data"\n', encoding="utf-8")
    cats = _cats(A.auditer(tmp_path))
    assert "chemin_absolu_disque" in cats or "users_flo" in cats


def test_detecte_chemin_sandbox(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "y.py").write_text('OUT = "/home/claude/hypersmart/runtime"\n', encoding="utf-8")
    assert "chemin_sandbox_profil" in _cats(A.auditer(tmp_path))


def test_detecte_registre(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "z.py").write_text("import winreg\n", encoding="utf-8")
    assert "registre_windows" in _cats(A.auditer(tmp_path))


def test_machineguid_readonly_est_tolere_uniquement_dans_fonction_identite_connue(tmp_path):
    p = tmp_path / "src" / "hl_observer" / "ops"
    p.mkdir(parents=True)
    (p / "portable_clone.py").write_text(
        "def machine_fingerprint():\n"
        "    import winreg\n"
        "    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\\\\Microsoft\\\\Cryptography') as k:\n"
        "        return winreg.QueryValueEx(k, 'MachineGuid')[0]\n",
        encoding="utf-8",
    )
    assert A.auditer(tmp_path) == []


def test_machineguid_exception_ne_tolere_jamais_ecriture_registre(tmp_path):
    p = tmp_path / "src" / "hl_observer" / "ops"
    p.mkdir(parents=True)
    (p / "portable_clone.py").write_text(
        "def machine_fingerprint():\n"
        "    import winreg\n"
        "    winreg.SetValueEx(key, 'x', 0, 1, 'y')\n",
        encoding="utf-8",
    )
    assert "registre_windows" in _cats(A.auditer(tmp_path))


def test_recommandation_chemin_court_est_du_diagnostic_pas_une_dependance(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.py").write_text(
        'MESSAGE = "Extract to a short writable path such as C:\\\\HyperSmart or D:\\\\HyperSmart."\n',
        encoding="utf-8",
    )
    assert A.auditer(tmp_path) == []


def test_ignore_les_commentaires(tmp_path):
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text(
        "cd /d \"%~dp0\"\nREM 'C:\\Users\\flo\\Desktop\\Projet' n'est pas reconnu\n", encoding="utf-8"
    )
    assert A.auditer(tmp_path) == []


def test_tolere_dp0(tmp_path):
    (tmp_path / "LANCER_HYPERSMART.cmd").write_text(
        'call "%~dp0tools\\portable_env.cmd"\n', encoding="utf-8"
    )
    assert A.auditer(tmp_path) == []


def test_le_runtime_actif_du_depot_est_portable():
    violations = A.auditer(RACINE)
    assert violations == [], A.formater(violations)
