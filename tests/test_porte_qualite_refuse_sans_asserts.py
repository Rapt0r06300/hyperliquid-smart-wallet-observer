"""Une porte batie sur `assert` devient VERTE sous `python -O`.

`tools/check_dataset_quality.py` verifie toute la politique de donnees avec 36
`assert` et est appelee par 19 sites de .github/workflows. `python -O` supprime
ces instructions a la compilation mais garde le print(... OK) final : la porte
afficherait un succes affirmatif et sortirait 0 sur des donnees contradictoires.
Ces tests prouvent le refus, et prouvent que le controle attraperait le defaut.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Scripts appeles par les workflows qui portent des `assert` SANS garde, avec la
# raison. tools/restore_alina.py:3561 est `assert catalog_path is not None` : un
# INVARIANT de type, pas une verification de donnees. Sans -O il leve
# AssertionError ; avec -O, build_certified_working_set recoit None et echoue
# quand meme. Il ne peut donc pas produire de faux vert. Tout NOUVEAU script de
# ce genre doit etre examine, pas ajoute ici par reflexe.
EXEMPTIONS = {"tools/restore_alina.py"}


def _scripts_appeles_par_les_workflows() -> dict[str, int]:
    appeles: dict[str, int] = {}
    for y in sorted((RACINE / ".github/workflows").glob("*.y*ml")):
        texte = y.read_text(encoding="utf-8", errors="replace")
        motif = r"python3?\s+(?:-[A-Za-z0-9]+\s+)*(tools/[A-Za-z0-9_./-]+\.py)"
        for m in re.finditer(motif, texte):
            appeles[m.group(1)] = appeles.get(m.group(1), 0) + 1
    return appeles


def _compte_les_asserts(chemin: Path) -> int:
    arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    return sum(1 for n in ast.walk(arbre) if isinstance(n, ast.Assert))


def _porte_la_garde(chemin: Path) -> bool:
    return "__debug__" in chemin.read_text(encoding="utf-8", errors="replace")


def test_la_porte_refuse_sous_O_sur_le_vrai_fichier() -> None:
    """La garde tombe AVANT toute lecture de catalogue, donc le test est instantane."""
    r = subprocess.run(
        [sys.executable, "-O", "tools/check_dataset_quality.py", "--catalog-only"],
        cwd=RACINE, capture_output=True, text=True, timeout=120,
    )
    sortie = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0, f"la porte a repondu 0 sous -O : {sortie[:400]}"
    assert "REFUS" in sortie, sortie[:400]
    assert "OK" not in r.stdout, f"succes affirmatif sous -O : {r.stdout[:200]}"


def test_la_porte_ne_refuse_pas_sans_O() -> None:
    """Le refus doit viser -O SEUL : sans -O, la garde ne doit jamais se declencher."""
    code = (
        "import pathlib,sys;"
        "src=pathlib.Path('tools/check_dataset_quality.py').read_text(encoding='utf-8');"
        "bloc=src.split('parser = argparse')[0];"
        "ns={};exec(compile(bloc,'porte','exec'),ns);"
        "print('GARDE_INACTIVE')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=RACINE,
        capture_output=True, text=True, timeout=120,
    )
    assert "GARDE_INACTIVE" in r.stdout, (r.stdout + r.stderr)[:400]


def test_tout_script_de_workflow_a_asserts_porte_la_garde() -> None:
    nus = []
    for script, _sites in sorted(_scripts_appeles_par_les_workflows().items()):
        chemin = RACINE / script
        if not chemin.is_file() or script in EXEMPTIONS:
            continue
        if _compte_les_asserts(chemin) > 0 and not _porte_la_garde(chemin):
            nus.append(script)
    assert not nus, f"porte(s) de workflow verifiant par assert sans garde -O : {nus}"


def test_le_controle_attraperait_le_defaut(tmp_path: Path) -> None:
    """Discrimination : sans la garde, -O rend 0 sur des donnees contradictoires."""
    sans = tmp_path / "sans_garde.py"
    sans.write_text(
        "donnees = {'self_hosted_forbidden': False}\n"
        "assert donnees['self_hosted_forbidden'] is True, 'self-hosted interdit'\n"
        "print('OK')\n",
        encoding="utf-8",
    )
    avec = tmp_path / "avec_garde.py"
    avec.write_text(
        "if not __debug__:\n"
        "    raise SystemExit('REFUS: asserts desactives')\n"
        "donnees = {'self_hosted_forbidden': False}\n"
        "assert donnees['self_hosted_forbidden'] is True, 'self-hosted interdit'\n"
        "print('OK')\n",
        encoding="utf-8",
    )

    def lance(f: Path, *drapeaux: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *drapeaux, str(f)],
            capture_output=True, text=True, timeout=120,
        )

    # Sans garde : le defaut EXISTE bien (sinon ce test ne prouverait rien).
    assert lance(sans).returncode != 0
    sous_O = lance(sans, "-O")
    assert sous_O.returncode == 0 and "OK" in sous_O.stdout, sous_O.stdout

    # Avec garde : refus sous -O, et comportement inchange sans -O.
    assert lance(avec).returncode != 0
    refus = lance(avec, "-O")
    assert refus.returncode != 0 and "REFUS" in (refus.stdout + refus.stderr)
