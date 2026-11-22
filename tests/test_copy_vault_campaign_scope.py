"""Le périmètre canonique est copy_vault, et cela doit être LISIBLE sans l'inférer.

POURQUOI CE FICHIER REVIENT (22/11/2026). Un `tests/__pycache__/test_copy_vault_campaign_scope
.cpython-314-pytest-8.4.2.pyc` de 14,8 ko traînait, daté du 18/11 à 20:27, **sans source ni dans
l'arbre de travail ni dans HEAD**. Démarshalé, il nomme les trois gardes qu'il portait :

    test_campagne_canonique_nexecute_que_copy_vault
    test_runner_refuse_un_scope_elargi_avant_de_charger_un_moteur
    test_cli_aide_est_disponible_sans_importer_une_famille_desactivee

La deuxième a survécu, renommée, dans `test_economic_runner_copy_vault_scope.py`
(`test_runner_fails_closed_before_any_io_if_scope_is_widened`). **Les deux autres ont été
perdues au renommage** — et l'absence de la première s'est payée le 22/11 : faute de garde
lisible, j'ai lu `all_software_pipelines_ready: True` comme « une famille sur trois », puis
annoncé une réserve qui n'existait pas. `CANONICAL_FAMILIES` ne contient qu'`copy_vault`, donc
ce `True` couvre le périmètre ENTIER.

Ce fichier ne reconstitue pas les assertions d'origine, qu'un bytecode ne rend pas : il réécrit
les deux intentions perdues, en le disant.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hl_observer.simulation.economic_collection_plan import (  # noqa: E402
    CANONICAL_FAMILIES,
    build_collection_plan,
)


def test_campagne_canonique_nexecute_que_copy_vault() -> None:
    """Le périmètre déclaré est UNE famille, conformément à « CopyVault uniquement »."""
    assert CANONICAL_FAMILIES == ("copy_vault",)


def test_all_software_pipelines_ready_couvre_le_perimetre_ENTIER() -> None:
    """Le piège qui m'a eu : ce booléen est un ET sur les familles du plan, pas sur trois.

    Sans cette garde, un lecteur (moi le 22/11) croit qu'il manque deux familles et annonce une
    réserve fausse. On épingle donc l'invariant : autant de familles dans le plan que dans le
    périmètre canonique, ni plus ni moins.
    """
    plan = build_collection_plan(
        [{"family": "copy_vault", "objective_status": "NON_ATTEINT"}],
        {"copy_vault": {}},
    )
    familles = plan["families"]
    assert len(familles) == len(CANONICAL_FAMILIES)
    assert [row["family"] for row in familles] == list(CANONICAL_FAMILIES)


def test_les_familles_parquees_sont_CONSERVEES_mais_jamais_selectionnees() -> None:
    """« NE SUPPRIME RIEN » : le code des familles inactives reste, et reste inatteignable.

    Le module garde `_lead_state` et `_cross_state` pour l'audit et l'historique. Ils ne doivent
    jamais être choisis tant qu'ils ne sont pas canoniques — mais les effacer serait une perte.
    """
    from hl_observer.simulation import economic_collection_plan as plan_mod

    assert callable(plan_mod._lead_state)
    assert callable(plan_mod._cross_state)
    for nom in ("lead_lag", "cross_venue_dislocation_v2"):
        assert nom not in CANONICAL_FAMILIES


def test_cli_aide_est_disponible_sans_executer_la_moindre_campagne(tmp_path: Path) -> None:
    """`--help` doit rester utilisable, et ne rien calculer ni écrire.

    ⚠️ Limite assumée : l'intention d'origine parlait de « sans importer une famille
    désactivée ». Le runner importe `lead_lag_shadow` au niveau module (ligne 19), donc cette
    formulation serait fausse aujourd'hui et je ne l'invente pas. Ce qui est vérifiable et
    utile : l'aide répond, et aucune campagne n'est produite au passage.
    """
    avant = set((ROOT / "runtime" / "reports" / "economic_campaigns").glob("*.json"))
    issue = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tools" / "run_economic_objective_campaigns.py"), "--help"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert issue.returncode == 0, issue.stderr[-400:]
    assert "usage:" in issue.stdout
    assert "--no-start-collection" in issue.stdout
    apres = set((ROOT / "runtime" / "reports" / "economic_campaigns").glob("*.json"))
    assert apres == avant, "l'aide a produit un artefact de campagne"


def test_les_DEUX_homonymes_CANONICAL_FAMILIES_restent_distincts() -> None:
    """Deux constantes du même nom, deux valeurs, et les deux ont raison.

    `simulation.economic_objective.CANONICAL_FAMILIES` = ("copy_vault",) est le PÉRIMÈTRE
    ÉVALUÉ aujourd'hui. `datasets.economic_memory.CANONICAL_FAMILIES` = les trois noms admis
    dans la mémoire des preuves, parce que l'historique en contient trois : c'est une liste
    blanche de NOMS, pas un périmètre d'exécution.

    Aucun appelant n'importe aujourd'hui la seconde en croyant lire la première — vérifié le
    22/11. Mais le nom partagé est un piège : importer la mauvaise élargirait le périmètre
    évalué EN SILENCE, et un `all(...)` sur trois familles absentes changerait de sens. Cette
    garde interdit donc de les « unifier » sans y penser.
    """
    from hl_observer.datasets.economic_memory import CANONICAL_FAMILIES as NOMS_ADMIS
    from hl_observer.simulation.economic_objective import CANONICAL_FAMILIES as PERIMETRE

    assert PERIMETRE == ("copy_vault",)
    assert {"copy_vault", "lead_lag", "cross_venue_dislocation_v2"} == NOMS_ADMIS
    assert set(PERIMETRE) < NOMS_ADMIS, "le périmètre évalué doit rester un sous-ensemble strict"
