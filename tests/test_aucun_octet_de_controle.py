"""Aucun octet de controle ne doit survivre dans le code source Python.

LE FAIT (20/11/2026). J'ecris mes correctifs avec des scripts qui reecrivent le fichier cible.
Un motif place dans une chaine **non brute** -- ``'(?=.*\bexit_code)'`` -- a vu son ``\b``
interprete **a l'ecriture** : c'est l'octet 0x08 (retour arriere) qui s'est retrouve DANS le
source. Le motif compile lisait alors << retour arriere suivi de exit_code >>, qui n'arrive
jamais : la regle ne se declenchait plus du tout.

POURQUOI RIEN NE LE VOYAIT. ``grep`` affichait la ligne comme si de rien n'etait (0x08 ne
s'imprime pas), ``ast.parse`` passait (c'est du code valide), et **sept tests passaient pour la
mauvaise raison** -- ils reussissaient parce que le motif ne matchait PLUS RIEN. Seul ``repr()``
l'a montre. Le meme piege avait deja frappe avec ``\t`` dans ``tools/tee_console.py`` : c'est une
FAMILLE, pas un accident, et une famille se garde par un test, pas par de l'attention.

CE QUE CE TEST TIENT. Il lit les OCTETS de chaque source Python du projet et refuse tout
caractere de controle autre que tabulation, LF et CR -- les seuls legitimes dans du texte. Le
controle est exact : il ne peut produire aucun faux positif, contrairement a une recherche par
mot-clef. Les motifs d'expression reguliere restent verifies un par un dans
``tests/test_tester_cmds_motifs.py`` ; ici c'est le source entier qui est couvert.

PORTEE. Seuls les ``.py`` : un ``.cmd`` peut legitimement porter un 0x1A (marqueur de fin de
fichier DOS), et un controle qui crie au loup apprend a l'operateur a l'ignorer.
"""
from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: Les seuls octets de controle admis dans du texte : tabulation, LF, CR.
CONTROLES_LEGITIMES = frozenset({9, 10, 13})

#: Repertoires de code du projet (hors dependances et hors arborescences de donnees).
DOSSIERS = ("src", "tools", "tests")


def _controles(octets: bytes) -> list[str]:
    """Les octets de controle interdits presents, en hexadecimal, tries et uniques."""
    return [hex(x) for x in sorted({o for o in octets
                                    if o < 32 and o not in CONTROLES_LEGITIMES})]


def _sources() -> list[Path]:
    fichiers: list[Path] = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if base.is_dir():
            fichiers.extend(p for p in base.rglob("*.py") if p.is_file())
    return fichiers


def test_aucun_octet_de_controle_dans_le_source_python() -> None:
    fichiers = _sources()
    assert len(fichiers) > 1000, (
        f"seulement {len(fichiers)} sources trouvees : le balayage ne couvre plus le projet, "
        "donc il ne protege plus rien")
    fautifs: list[str] = []
    for chemin in fichiers:
        trouves = _controles(chemin.read_bytes())
        if trouves:
            fautifs.append(f"{chemin.relative_to(RACINE)} -> {', '.join(trouves)}")
    assert not fautifs, (
        "octet(s) de controle dans du code source -- presque surement un echappement "
        "interprete a l'ecriture (ecrire r'...' et verifier par repr()) :\n  "
        + "\n  ".join(fautifs))


def test_la_regle_attrape_un_echappement_interprete() -> None:
    """Sans ceci, le test ci-dessus passerait avec une regle qui ne detecte rien.

    On construit l'octet par ``chr(8)`` et jamais par un echappement litteral : ecrire le piege
    dans ce fichier le ferait echouer lui-meme, et un fichier de test qui s'attrape est inutile.
    """
    piege = ('_MOTIF = re.compile("(?=.*' + chr(8) + 'exit_code)")').encode("utf-8")
    assert _controles(piege) == ["0x8"]
    assert _controles(b"x = 1\x0cy = 2") == ["0xc"]


def test_la_regle_accepte_tabulation_et_fins_de_ligne() -> None:
    """La moitie qui compte : du code normal ne doit JAMAIS etre signale."""
    assert _controles(b"def f():\n\treturn 1\r\n") == []
    assert _controles(('MOTIF = r"' + chr(92) + 'bexit_code"').encode()) == []
