"""Les deux PREUVES qui remplacent deux faux positifs de l'audit.

CONTEXTE (2026-11-21). Deux regles bloquantes de l'audit rougissaient sur des HOMONYMES :

  * « Aucune URL d'execution (endpoint /exchange) » accusait `ops/validation_portable.py:311`,
    qui est le GARDE qui refuse cet endpoint ;
  * « Le LEDGER D'EVENEMENTS ne doit jamais etre supprime » accusait
    `realtime/durable_dedup.py`, dont la table `seen_events` est une FENETRE de dedup bornee
    (le mot « event » y est une coincidence de nom), et dont le compactage ARCHIVE avant de
    supprimer.

Le garde etait accuse a la place du voleur. Mais retirer ces lignes du compte textuel sans
rien mettre a la place echangerait un faux positif contre un angle mort. Deux regles
BLOQUANTES ont donc ete ajoutees, qui PROUVENT la propriete au lieu de la supposer.

Ce fichier verifie les deux regles -- et surtout qu'elles ROUGISSENT si la propriete tombe.
Une regle verte qui ne peut pas rougir ne verifie rien.
"""
from __future__ import annotations

import importlib.util
import sys
from contextlib import suppress
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_report_preuves", RACINE / "tools" / "audit_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_report_preuves"] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------- l'URL d'execution est REFUSEE
def test_la_regle_prouve_que_l_endpoint_d_ordre_est_refuse():
    verdict = _audit().c_exchange_url_refusee()
    assert verdict.ok, verdict.errors
    assert "sans aucun appel reseau" in verdict.summary


def test_la_regle_ROUGIT_si_une_url_interdite_etait_acceptee(monkeypatch):
    """DISCRIMINANT : sans cela, la regle pourrait etre verte par construction."""
    m = _audit()
    from hl_observer.ops import validation_portable as vp

    monkeypatch.setattr(vp, "smoke_reseau_readonly", lambda **kw: {
        "ok": True, "read_only": True, "credentials_sent": False,
        "exchange_endpoint_used": False,
        "results": [{"venue": "x", "ok": True, "detail": "accepte"},
                    {"venue": "y", "ok": True, "detail": "accepte"}],
    })
    verdict = m.c_exchange_url_refusee()
    assert not verdict.ok, "une URL interdite ACCEPTEE n'a pas fait rougir la regle"


def test_la_regle_ROUGIT_si_l_ouvreur_reseau_est_appele(monkeypatch):
    """Refuser APRES avoir ouvert la connexion n'est pas refuser."""
    m = _audit()
    from hl_observer.ops import validation_portable as vp

    def _appelle_quand_meme(*, opener, timeout):
        with suppress(Exception):
            opener(object(), timeout=timeout)
        return {"ok": False, "read_only": True, "credentials_sent": False,
                "exchange_endpoint_used": False,
                "results": [{"ok": False, "detail": "unsafe URL refused"},
                            {"ok": False, "detail": "unsafe URL refused"}]}

    monkeypatch.setattr(vp, "smoke_reseau_readonly", _appelle_quand_meme)
    assert not m.c_exchange_url_refusee().ok


# ------------------------------------------------------- la dedup archive AVANT de supprimer
def test_la_regle_prouve_que_la_dedup_archive_avant_de_supprimer():
    verdict = _audit().c_dedup_archive_avant_suppression()
    assert verdict.ok, verdict.errors
    assert "AVANT suppression" in verdict.summary


def _poser_module(m, tmp_path: Path, corps: str) -> None:
    chemin = tmp_path / "hl_observer" / "realtime" / "durable_dedup.py"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(corps, encoding="utf-8")
    m.SRC = tmp_path


SAIN = '''
class S:
    def compact(self):
        rows = self.lire()
        chemin = self._write_archive(rows)
        self.cx.execute("DELETE FROM seen_events WHERE row_sequence <= ?", (1,))
        return chemin
'''

INVERSE = '''
class S:
    def compact(self):
        rows = self.lire()
        self.cx.execute("DELETE FROM seen_events WHERE row_sequence <= ?", (1,))
        chemin = self._write_archive(rows)
        return chemin
'''

SANS_ARCHIVE = '''
class S:
    def compact(self):
        self.cx.execute("DELETE FROM seen_events WHERE row_sequence <= ?", (1,))
'''

SANS_WHERE = '''
class S:
    def compact(self):
        chemin = self._write_archive([])
        self.cx.execute("DELETE FROM seen_events")
        return chemin
'''


def test_un_module_sain_de_fixture_passe(tmp_path):
    m = _audit()
    _poser_module(m, tmp_path, SAIN)
    assert m.c_dedup_archive_avant_suppression().ok


@pytest.mark.parametrize("corps,attendu", [
    (INVERSE, "precede l'ARCHIVAGE"),
    (SANS_ARCHIVE, "_write_archive"),
    (SANS_WHERE, "SANS WHERE"),
])
def test_chaque_rupture_du_contrat_fait_rougir_la_regle(tmp_path, corps, attendu):
    """DISCRIMINANT, les trois ruptures qui comptent : inversion, perte seche, purge totale."""
    m = _audit()
    _poser_module(m, tmp_path, corps)
    verdict = m.c_dedup_archive_avant_suppression()
    assert not verdict.ok
    assert any(attendu in e for e in verdict.errors), verdict.errors


def test_un_module_absent_fait_rougir_au_lieu_de_passer(tmp_path):
    """Donnee absente -> refus sur. Jamais un vert parce qu'il n'y avait rien a lire."""
    m = _audit()
    m.SRC = tmp_path
    verdict = m.c_dedup_archive_avant_suppression()
    assert not verdict.ok


def test_les_deux_regles_sont_BLOQUANTES():
    """Une preuve de securite non bloquante est un avertissement qu'on apprend a ignorer."""
    m = _audit()
    assert m.c_exchange_url_refusee().blocking is True
    assert m.c_dedup_archive_avant_suppression().blocking is True
