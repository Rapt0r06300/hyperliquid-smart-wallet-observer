"""`with sqlite3.connect(...)` NE FERME PAS la connexion. Mesure, pas croyance.

LE FAIT, VERIFIE LE 20/11/2026 (Python 3.14.2, sqlite 3.50.4) : apres le bloc `with`, la
connexion repond encore a `execute()`. Le gestionnaire de contexte de `sqlite3.Connection`
fait un COMMIT (ou un ROLLBACK), **jamais** un `close()`. C'est contre-intuitif, et c'est
exactement ce que trois appels du projet supposaient.

POURQUOI CA COMPTE ICI. Sous Windows, un handle ouvert maintient un VERROU sur le `.db` et ses
`-wal`/`-shm`, et le contrat exige de gerer << fichiers verrouilles, SQLite actif >>. Les trois
sites etaient en lecture seule dans des fonctions courtes -- donc le compteur de references
fermait a la sortie, gravite faible -- mais le piege se declenche des qu'une ligne est ajoutee
apres le bloc, ou des que l'appel passe dans une boucle.

⚠ LE PIEGE SYMETRIQUE, documente sur les trois sites : `closing()` ne COMMIT pas. Sans effet
sur une connexion `mode=ro` ; sur une connexion en ECRITURE il faut les DEUX
(`with closing(sqlite3.connect(p)) as c, c:`), sinon on perd les ecritures EN SILENCE.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

#: Les trois appels corriges. Ils doivent rester en `closing(...)`.
SITES = (
    "tools/alina_quant_lab_console.py",
    "tools/copy_vault_safe_bridge.py",
    "tools/sync_complete_clone.py",
)


def test_le_with_de_sqlite_ne_ferme_pas(tmp_path) -> None:
    """La mesure qui fonde tout le reste : si ce comportement changeait, on le saurait ici."""
    chemin = tmp_path / "x.db"
    with sqlite3.connect(chemin) as connexion:
        connexion.execute("CREATE TABLE t(a)")
    connexion.execute("SELECT 1")          # ne leve PAS : la connexion est encore ouverte
    connexion.close()
    with pytest.raises(sqlite3.ProgrammingError):
        connexion.execute("SELECT 1")      # apres close(), elle leve


def test_closing_ferme_vraiment(tmp_path) -> None:
    """La moitie qui compte : le remede doit, lui, fermer pour de vrai."""
    chemin = tmp_path / "y.db"
    with closing(sqlite3.connect(chemin)) as connexion:
        connexion.execute("CREATE TABLE t(a)")
    with pytest.raises(sqlite3.ProgrammingError):
        connexion.execute("SELECT 1")


def test_les_trois_sites_restent_fermes_explicitement() -> None:
    """Verrouille le correctif : plus aucun `with sqlite3.connect(` nu dans ces fichiers."""
    fautifs: list[str] = []
    for relatif in SITES:
        chemin = RACINE / relatif
        assert chemin.is_file(), f"{relatif} a disparu : le test ne verrouille plus rien"
        for numero, ligne in enumerate(
                chemin.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            nu = ligne.strip()
            if nu.startswith("#"):
                continue
            if "with sqlite3.connect(" in nu:
                fautifs.append(f"{relatif}:{numero} -> {nu[:88]}")
    assert not fautifs, (
        "connexion(s) SQLite dont le `with` ne ferme PAS (utiliser closing(...)) :\n  "
        + "\n  ".join(fautifs))


def test_les_trois_sites_utilisent_bien_closing() -> None:
    """Sans ceci, supprimer purement et simplement les lignes passerait le test ci-dessus."""
    for relatif in SITES:
        texte = (RACINE / relatif).read_text(encoding="utf-8", errors="replace")
        assert "with closing(sqlite3.connect(" in texte, (
            f"{relatif} : l'appel SQLite ferme explicitement a disparu")
        assert "from contextlib import closing" in texte, (
            f"{relatif} : `closing` n'est plus importe")
