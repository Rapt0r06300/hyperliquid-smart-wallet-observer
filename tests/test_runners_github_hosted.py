"""Aucun workflow ne doit tourner ailleurs que sur un runner GitHub-hosted.

MESURE DU 21/11/2026 — pourquoi ce fichier existe. Un workflow injecté avec
`runs-on: self-hosted` a traversé **75 tests locaux verts** répartis sur les 8 fichiers
qui parlent déjà de workflows (`test_validate_github_hosted_workflows`,
`test_platform_responsibility_check`, `test_workflow_bounds`,
`test_alina_self_hosted_assets`, `test_alina_self_hosted_final_v1`,
`test_local_readonly_observer`, `test_portable_release_ci`,
`test_ci_long_run_wait_budgets`). La propriété n'était tenue que par
`.github/workflows/github-hosted-runner-firewall.yml` : un garde qui s'exécute APRÈS le
push, dans le cloud, et qui peut lui-même être désactivé ou supprimé.

Or le contrat du dépôt est explicite : GitHub-hosted uniquement pour le cloud, jamais
de dépendance cloud au PC. Un runner auto-hébergé ferait tourner du code du dépôt sur
une machine privée — exactement ce que ce contrat interdit.

Choix de méthode : **liste blanche**, pas liste noire. Interdire « self-hosted » ne
suffirait pas, car un runner privé s'étiquette comme on veut (`runs-on: ma-grosse-tour`
est auto-hébergé sans contenir le mot). Et toute valeur que ce test ne sait pas résoudre
(`${{ … }}` hors matrice lisible) est un ÉCHEC : ne pas savoir n'est pas une preuve
d'hébergement.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[1]
WORKFLOWS = RACINE / ".github" / "workflows"

# Préfixes des images fournies par GitHub (ubuntu-latest, windows-2022, macos-14…).
PREFIXES_HEBERGES = ("ubuntu-", "windows-", "macos-")


def _fichiers_workflow() -> list[Path]:
    return sorted(
        chemin
        for motif in ("*.yml", "*.yaml")
        for chemin in WORKFLOWS.glob(motif)
    )


def _valeurs_matrice(job: dict) -> dict[str, list[str]]:
    """Valeurs littérales déclarées par `strategy.matrix`, y compris `include`."""
    matrice = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrice, dict):
        return {}
    resolues: dict[str, list[str]] = {}
    for cle, valeur in matrice.items():
        if cle in ("include", "exclude"):
            continue
        if isinstance(valeur, list):
            resolues[str(cle)] = [str(v) for v in valeur]
    inclusions = matrice.get("include")
    if isinstance(inclusions, list):
        for entree in inclusions:
            if not isinstance(entree, dict):
                continue
            for cle, valeur in entree.items():
                if not isinstance(valeur, (list, dict)):
                    resolues.setdefault(str(cle), []).append(str(valeur))
    return resolues


def _etiquettes_brutes(runs_on) -> list[str]:
    """`runs-on` accepte une chaîne, une liste d'étiquettes, ou {group, labels}."""
    if isinstance(runs_on, str):
        return [runs_on]
    if isinstance(runs_on, list):
        return [str(v) for v in runs_on]
    if isinstance(runs_on, dict):
        etiquettes = []
        groupe = runs_on.get("group")
        if groupe is not None:
            # Un *runner group* est par construction un parc prive : jamais hebergé.
            etiquettes.append("group:" + str(groupe))
        labels = runs_on.get("labels")
        if isinstance(labels, str):
            etiquettes.append(labels)
        elif isinstance(labels, list):
            etiquettes.extend(str(v) for v in labels)
        return etiquettes or [repr(runs_on)]
    return [repr(runs_on)]


def _resoudre(etiquette: str, matrice: dict[str, list[str]]) -> list[str]:
    """Rend les valeurs possibles d'une étiquette, ou [] si elle reste inconnue."""
    nu = etiquette.strip()
    if "${{" not in nu:
        return [nu]
    interieur = nu[nu.index("${{") + 3:]
    interieur = interieur.split("}}")[0].strip()
    if interieur.startswith("matrix."):
        cle = interieur[len("matrix."):].strip()
        return matrice.get(cle, [])
    return []


def _violations() -> list[str]:
    trouvees: list[str] = []
    for chemin in _fichiers_workflow():
        try:
            charge = yaml.safe_load(chemin.read_text(encoding="utf-8", errors="replace"))
        except yaml.YAMLError as erreur:  # illisible => on ne peut rien prouver
            trouvees.append(f"{chemin.name}: YAML illisible ({type(erreur).__name__})")
            continue
        if not isinstance(charge, dict):
            trouvees.append(f"{chemin.name}: contenu inattendu (pas un mapping)")
            continue
        jobs = charge.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for nom, job in jobs.items():
            if not isinstance(job, dict) or "runs-on" not in job:
                continue  # un job `uses:` delegue a un workflow lui aussi scanne
            matrice = _valeurs_matrice(job)
            for etiquette in _etiquettes_brutes(job["runs-on"]):
                valeurs = _resoudre(etiquette, matrice)
                if not valeurs:
                    trouvees.append(
                        f"{chemin.name}:{nom}: runner non resolvable '{etiquette}' "
                        "-- impossible de prouver qu'il est GitHub-hosted")
                    continue
                for valeur in valeurs:
                    if not valeur.lower().startswith(PREFIXES_HEBERGES):
                        trouvees.append(f"{chemin.name}:{nom}: runner '{valeur}'")
    return trouvees


def test_il_y_a_bien_des_workflows_a_verifier():
    """Un test qui ne mesure rien serait vert pour la pire des raisons."""
    fichiers = _fichiers_workflow()
    assert len(fichiers) >= 50, f"seulement {len(fichiers)} workflow(s) trouve(s)"


def test_tous_les_runners_sont_github_hosted():
    violations = _violations()
    assert not violations, (
        "runner(s) non GitHub-hosted — le code du depot tournerait hors du cloud :\n- "
        + "\n- ".join(violations[:10])
    )


@pytest.mark.parametrize(
    ("runs_on", "doit_passer"),
    [
        ("ubuntu-latest", True),
        ("windows-latest", True),
        ("macos-14", True),
        ("self-hosted", False),
        ("ma-grosse-tour", False),          # auto-heberge SANS le mot interdit
        ("[self-hosted, windows]", False),
        ("${{ env.RUNNER }}", False),       # non resolvable => refus
    ],
)
def test_le_controle_attraperait_chaque_forme(tmp_path, monkeypatch, runs_on, doit_passer):
    """Le discriminant est verifie forme par forme, liste blanche comprise."""
    dossier = tmp_path / "workflows"
    dossier.mkdir()
    (dossier / "essai.yml").write_text(
        "name: essai\non:\n  workflow_dispatch:\njobs:\n"
        f"  job:\n    runs-on: {runs_on}\n    steps:\n      - run: echo ok\n",
        encoding="utf-8", newline="\n")
    monkeypatch.setitem(globals(), "WORKFLOWS", dossier)
    assert (_violations() == []) is doit_passer, _violations()


def test_une_matrice_dos_runners_prives_est_refusee(tmp_path, monkeypatch):
    """`runs-on: ${{ matrix.os }}` ne protege rien si la matrice porte un runner prive."""
    dossier = tmp_path / "workflows"
    dossier.mkdir()
    (dossier / "essai.yml").write_text(
        "name: essai\non:\n  workflow_dispatch:\njobs:\n"
        "  job:\n    strategy:\n      matrix:\n        os: [ubuntu-latest, self-hosted]\n"
        "    runs-on: ${{ matrix.os }}\n    steps:\n      - run: echo ok\n",
        encoding="utf-8", newline="\n")
    monkeypatch.setitem(globals(), "WORKFLOWS", dossier)
    violations = _violations()
    assert violations and "self-hosted" in violations[0], violations
