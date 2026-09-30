"""POURQUOI CA CASSE -- regroupe les tests en echec par CAUSE RACINE (2026-07-12).

LE PROBLEME QU'IL RESOUT
-----------------------
L'audit dit "30 failed". Trente. Ca sonne comme une catastrophe.
Mais 21 de ces 30 sont dans UN SEUL fichier, et sentent la CASCADE : si l'entree est
refusee, alors la position n'existe pas, alors le PnL n'existe pas, alors l'equity
n'existe pas -- un seul verrou produit vingt symptomes.

Compter les symptomes, c'est se faire peur. Compter les CAUSES, c'est savoir quoi reparer.

CE QU'IL FAIT
-------------
Il lit la sortie de pytest, extrait la DERNIERE ligne `E   ...` de chaque echec
(l'exception reelle), la normalise (on retire les adresses memoire, les chemins, les
nombres) et regroupe. Le rapport dit :

    3 causes racines pour 30 echecs
      [21x] AssertionError: OBSERVING_NO_VIRTUAL_ENTRY != SIMULATION_ACTIVE
      [ 2x] TypeError: '>' not supported between 'str' and 'float'
      ...

100 % lecture seule. Aucun reseau, aucun ordre. Il ne fait que lire du texte.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict

# Un message d'erreur contient du bruit qui DIFFERE a chaque execution : adresses
# memoire, chemins temporaires, timestamps. Deux echecs identiques auraient l'air
# differents. On normalise avant de comparer -- sinon on compterait 30 causes pour 3.
_BRUIT = [
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"]+"), "<chemin>"),
    (re.compile(r"/[a-z0-9_./-]{8,}"), "<chemin>"),
    (re.compile(r"\b\d+\.\d+\b"), "<n>"),
    (re.compile(r"\b\d{4,}\b"), "<n>"),
]

# Le nom du test en echec, tel que pytest le liste en fin de run.
_LIGNE_TEST = re.compile(r"^(?:FAILED\s+)?(tests/[\w/]+\.py)::([\w\[\]-]+)")
# La ligne d'exception : pytest la prefixe de "E   ".
_LIGNE_E = re.compile(r"^E\s{3}(\w*(?:Error|Exception|Failed|Warning)\b.*|assert\b.*)")


def normaliser(msg: str) -> str:
    """Retire le bruit variable pour que deux echecs IDENTIQUES se ressemblent."""
    out = msg.strip()
    for motif, remplacement in _BRUIT:
        out = motif.sub(remplacement, out)
    return out[:110]


def grouper(sortie_pytest: str) -> dict[str, list[str]]:
    """{cause racine normalisee: [noms de tests]}.

    On lit le rapport de pytest de haut en bas. Chaque bloc `_____ test_x _____`
    ouvre un echec ; la DERNIERE ligne `E   ...` du bloc est l'exception qui a
    reellement tue le test (les precedentes sont du contexte).
    """
    causes: dict[str, list[str]] = defaultdict(list)
    test_courant = ""
    erreur_courante = ""

    def _fermer() -> None:
        if test_courant and erreur_courante:
            causes[normaliser(erreur_courante)].append(test_courant)

    for ligne in sortie_pytest.splitlines():
        entete = re.match(r"^_+\s+([\w\[\]-]+)\s+_+$", ligne.strip())
        if entete:
            _fermer()
            test_courant, erreur_courante = entete.group(1), ""
            continue
        m = _LIGNE_E.match(ligne)
        if m and test_courant:
            erreur_courante = m.group(1)
    _fermer()
    return dict(causes)


def rapport(causes: dict[str, list[str]]) -> str:
    """Le texte a lire. Trie par nombre de symptomes -- la plus grosse cause d'abord."""
    total = sum(len(v) for v in causes.values())
    if total == 0:
        return "  Aucun echec detecte dans cette sortie pytest. (Tout passe, ou rien n'a tourne.)\n"

    lignes = [
        "=" * 78,
        f"  {len(causes)} CAUSE(S) RACINE(S) pour {total} echec(s).",
        "",
        "  30 echecs ne sont pas 30 bugs. Un verrou qui refuse l'entree fait tomber",
        "  la position, puis le PnL, puis l'equity : un bug, vingt symptomes.",
        "  Reparer la cause du haut fait souvent tomber tout le bloc d'un coup.",
        "=" * 78,
        "",
    ]
    for cause, tests in sorted(causes.items(), key=lambda kv: -len(kv[1])):
        lignes.append(f"  [{len(tests):>2}x]  {cause}")
        for t in tests[:4]:
            lignes.append(f"          - {t}")
        if len(tests) > 4:
            lignes.append(f"          ... et {len(tests) - 4} autre(s), meme cause")
        lignes.append("")
    return "\n".join(lignes)


def main() -> int:  # pragma: no cover
    texte = sys.stdin.read()
    print(rapport(grouper(texte)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
