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


# ============================================================================
# EXTENSION DU 21/11/2026 — LES FABRIQUES DE CONNEXION
# ============================================================================
# Les trois sites ci-dessus etaient des appels isoles. Le balayage du 21/11 a
# trouve la MEME faute sous une autre forme, plus grave : une fabrique
# (`_connect()` / `_conn()` / `connect()`) appelee a CHAQUE operation, dont le
# resultat etait consomme par `with ...` au site d appel. Donc une connexion
# fuyait PAR OPERATION, pas une fois. 21 sites d appel sur 4 modules, dont
# `durable_dedup` qui est dans le chemin temps reel et tourne en WAL.
#
# Le correctif transforme la fabrique en gestionnaire de contexte qui garde
# `with connection:` AUTOUR du yield (donc le commit/rollback d avant) et ajoute
# `close()` en `finally`. Chaque test ci-dessous verifie LES DEUX :
#   1. la connexion est bien FERMEE apres le bloc ;
#   2. l ecriture faite dans le bloc a bien ete CONSERVEE.
# Le point 2 est le garde-fou : un `closing()` seul fermerait proprement tout en
# perdant les ecritures EN SILENCE, et le point 1 ne le verrait pas.

#: Les 4 sites inline de whale_watchlist doivent rester en closing(...) ET `, conn`.
FICHIER_WATCHLIST = "hyper_smart_observer/dydx_v4/whale_watchlist.py"


def _prouver_fermee_et_ecriture_conservee(fabrique) -> None:
    """Contrat commun aux trois fabriques, pour ne pas le reecrire trois fois."""
    with fabrique() as connexion:
        connexion.execute("CREATE TABLE IF NOT EXISTS t_preuve(a INTEGER)")
        connexion.execute("INSERT INTO t_preuve(a) VALUES (7)")

    # 1. fermee pour de vrai
    with pytest.raises(sqlite3.ProgrammingError):
        connexion.execute("SELECT 1")

    # 2. l ecriture a survecu a la fermeture
    with fabrique() as relecture:
        assert relecture.execute("SELECT a FROM t_preuve").fetchone()[0] == 7


def test_dedup_durable_ferme_et_conserve(tmp_path) -> None:
    from hl_observer.realtime.durable_dedup import DurableEventDedup

    store = DurableEventDedup(tmp_path / "dedup")
    _prouver_fermee_et_ecriture_conservee(store._connect)


def test_memoire_ia_ferme_et_conserve(tmp_path) -> None:
    from hl_observer.ml.memory_store import IAMemory

    store = IAMemory(str(tmp_path / "ia.sqlite3"))
    _prouver_fermee_et_ecriture_conservee(store._conn)


def test_store_v12_ferme_et_conserve(tmp_path) -> None:
    from hl_observer.storage.v12_sqlite_store import V12SQLiteStore

    store = V12SQLiteStore(tmp_path / "v12.sqlite3")
    _prouver_fermee_et_ecriture_conservee(store.connect)


def test_watchlist_ne_laisse_aucune_connexion_ouverte(tmp_path, monkeypatch) -> None:
    """Capture TOUTES les connexions ouvertes, puis exige qu aucune ne reponde."""
    from unittest.mock import MagicMock

    from hyper_smart_observer.dydx_v4.whale_watchlist import WhaleWatchlist

    ouvertes: list[sqlite3.Connection] = []
    vrai_connect = sqlite3.connect

    def connect_espionne(*args, **kwargs):
        connexion = vrai_connect(*args, **kwargs)
        ouvertes.append(connexion)
        return connexion

    monkeypatch.setattr(sqlite3, "connect", connect_espionne)

    liste = WhaleWatchlist(
        rest_client=MagicMock(), db_path=str(tmp_path / "whale.db"),
    )
    liste._save_candidates(["0xabc", "0xdef"], source="test")

    assert ouvertes, "aucune connexion observee : le test ne prouverait rien"
    encore_vivantes = []
    for i, connexion in enumerate(ouvertes):
        try:
            connexion.execute("SELECT 1")
            encore_vivantes.append(i)
        except sqlite3.ProgrammingError:
            pass
    assert not encore_vivantes, (
        f"{len(encore_vivantes)}/{len(ouvertes)} connexions encore ouvertes : {encore_vivantes}"
    )

    # Et l ecriture a bien ete conservee malgre la fermeture.
    with closing(vrai_connect(str(tmp_path / "whale.db"))) as verif:
        n = verif.execute("SELECT COUNT(*) FROM whale_candidates").fetchone()[0]
    assert n == 2, n


def test_les_quatre_sites_de_la_watchlist_ont_closing_et_le_commit() -> None:
    texte = (RACINE / FICHIER_WATCHLIST).read_text(encoding="utf-8")
    attendu = "with closing(sqlite3.connect(str(self._db_path))) as conn, conn:"
    assert texte.count(attendu) == 4, texte.count(attendu)
    # Aucun site ne doit revenir a la forme nue.
    assert "with sqlite3.connect(str(self._db_path)) as conn:" not in texte
