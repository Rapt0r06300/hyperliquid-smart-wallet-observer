"""IMPROVE-14 (#121) — le CLIQUET de couverture.

LE PROBLÈME
-----------
« Étendre la couverture de tests » est un vœu. Un vœu ne garde rien.
Des dizaines de modules **joignables depuis un point d'entrée** — donc susceptibles de
s'exécuter en production — ne sont **couverts par aucun test**. Et rien n'empêche ce nombre
d'augmenter demain.

CE QU'ON FAIT À LA PLACE
-----------------------
Un **cliquet** : on mesure le nombre de modules joignables-mais-non-testés, on le fige dans
`tools/couverture_baseline.json`, et un test **échoue si ce nombre AUGMENTE**.

    On ne promet pas d'atteindre 100 %. On interdit de RECULER.

C'est la même logique que le cliquet de sécurité (#131) : la garantie ne vient pas d'un chiffre
flatteur, elle vient du fait que **le chiffre ne peut plus empirer sans que la CI crie**.

DÉFINITIONS (et leurs limites, dites franchement)
-------------------------------------------------
* **joignable** : atteignable depuis un point d'entrée réel (même graphe d'imports que T3b).
* **couvert** : atteignable depuis un fichier `tests/test_*.py`.

⚠️ « Couvert » ici signifie **« un test l'importe, directement ou transitivement »** — PAS
« ses lignes sont exécutées ». C'est une borne **optimiste** : un module importé par un test
qui ne l'appelle jamais compte comme couvert. On le dit, parce qu'un indicateur dont on cache
la faiblesse est un indicateur qui finira par mentir. Le cliquet reste utile : il empêche
d'ajouter du code **entièrement** invisible aux tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.audit.cablage import (
    _importes_par,
    _points_d_entree,
    modules_atteignables,
)

RACINE = "hl_observer"
FICHIER_BASELINE = Path("tools") / "couverture_baseline.json"


@dataclass(frozen=True, slots=True)
class VerdictCouverture:
    n_joignables: int
    n_couverts: int
    non_testes: tuple[str, ...]

    @property
    def n_non_testes(self) -> int:
        return len(self.non_testes)

    @property
    def taux(self) -> float:
        return (self.n_couverts / self.n_joignables) if self.n_joignables else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_joignables": self.n_joignables,
            "n_couverts": self.n_couverts,
            "n_non_testes": self.n_non_testes,
            "taux_couverture": round(self.taux, 4),
            "non_testes": list(self.non_testes),
        }


def _importes_directement_par_les_tests(fichiers: dict[str, str]) -> list[str]:
    """Les modules `hl_observer.*` que les fichiers de test importent DIRECTEMENT.

    🚩 MA PREMIERE VERSION ETAIT FAUSSE, ET MON PROPRE TEST L'A ATTRAPEE.
    Je passais `tests.test_xxx` comme points de depart a `modules_atteignables` — qui ne parcourt
    que le graphe des modules `hl_observer.*`. Resultat : **0 module couvert sur 484**, un chiffre
    absurde que j'aurais pu inscrire tel quel dans la baseline.

    Un outil de mesure qui se trompe est PIRE qu'une absence de mesure : on lui fait confiance.
    C'est exactement pour ca que cet audit doit rester PUR et etre eprouve sur un arbre fabrique
    dont on connait la reponse (cf. `test_l_audit_de_couverture_se_teste_sur_un_arbre_FABRIQUE`).
    """
    graines: set[str] = set()
    for chemin, source in fichiers.items():
        if not (chemin.startswith("tests/") and Path(chemin).name.startswith("test_")):
            continue
        graines |= {m for m in _importes_par(source, chemin) if m.startswith(RACINE)}
    return sorted(graines)


def auditer(fichiers: dict[str, str], lanceurs: dict[str, str]) -> VerdictCouverture:
    """PUR : on lui donne les fichiers, il rend le verdict. Aucun disque, aucun reseau.

    C'est ce qui permet de l'eprouver sur des arbres FABRIQUES — un outil qu'on ne peut pas
    tester sur des cas connus finit par se tromper sans qu'on le sache (cf. l'audit qui
    contaminait ses propres tests, le 12/07... et cet audit-ci, qui annoncait 0 % de couverture).
    """
    joignables = modules_atteignables(fichiers, _points_d_entree(fichiers, RACINE, lanceurs))
    # Un module est COUVERT s'il est importe par un test, ou importe par un module lui-meme
    # couvert : on prend la fermeture transitive a partir des imports directs des tests.
    couverts = modules_atteignables(fichiers, _importes_directement_par_les_tests(fichiers))

    # On ne compte QUE le code de production : un test non teste n'a aucun sens.
    prod = {m for m in joignables if m.startswith(RACINE + ".")}
    vus_par_les_tests = {m for m in couverts if m.startswith(RACINE + ".")}

    non_testes = tuple(sorted(prod - vus_par_les_tests))
    return VerdictCouverture(
        n_joignables=len(prod),
        n_couverts=len(prod & vus_par_les_tests),
        non_testes=non_testes,
    )


def lire_baseline(racine: Path) -> int | None:
    chemin = Path(racine) / FICHIER_BASELINE
    if not chemin.exists():
        return None
    try:
        return int(json.loads(chemin.read_text(encoding="utf-8"))["max_non_testes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ecrire_baseline(racine: Path, n: int, note: str = "") -> None:
    """N'ECRIT QUE SI ON DESCEND. Le cliquet ne doit pouvoir tourner que dans un sens.

    Si on laissait ce script remonter la baseline, il suffirait de le relancer apres avoir
    ajoute du code non teste pour faire taire l'alarme. Un cliquet qui se relache tout seul
    n'est pas un cliquet : c'est une decoration.
    """
    chemin = Path(racine) / FICHIER_BASELINE
    actuel = lire_baseline(racine)
    if actuel is not None and n > actuel:
        raise ValueError(
            "REFUS d'augmenter la baseline (%d -> %d). Le cliquet ne tourne que vers le BAS. "
            "Si du code non teste vient d'etre ajoute, il faut le TESTER, pas relever la barre."
            % (actuel, n)
        )
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps({"max_non_testes": int(n), "note": note}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "FICHIER_BASELINE",
    "VerdictCouverture",
    "auditer",
    "lire_baseline",
    "ecrire_baseline",
]
