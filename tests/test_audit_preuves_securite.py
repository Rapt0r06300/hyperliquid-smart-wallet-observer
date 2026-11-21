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


# ------------------------------- l'interpreteur qui MESURE doit etre le bon
def _requirements_bidon(monkeypatch, tmp_path, contenu):
    """Fait lire a la regle un requirements.txt fabrique, sans toucher au vrai."""
    m = _audit()
    (tmp_path / "requirements.txt").write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    return m


def test_la_regle_est_verte_quand_l_interpreteur_satisfait_les_bornes(
        monkeypatch, tmp_path):
    m = _requirements_bidon(
        monkeypatch, tmp_path, "pytest>=0" + chr(10) + "packaging>=0" + chr(10))
    verdict = m.c_interpreteur_conforme_aux_requirements()
    assert verdict.ok, verdict.errors
    assert "2/2" in verdict.summary


def test_la_regle_ROUGIT_sur_une_version_interdite(monkeypatch, tmp_path):
    """LE CAS REEL DU 21/11/2026.

    La passe complete (19 860 tests verts) avait tourne sous un interpreteur
    portant pytest 8.4.2 et websockets 10.4, alors que requirements.txt exige
    pytest>=9.0.3,<10 et websockets>=17,<18. Deux echecs n'avaient pas
    d'autre cause. Un vert obtenu sur une bibliotheque interdite n'est pas
    un verdict : la regle doit le dire, et le dire en BLOQUANT.
    """
    m = _requirements_bidon(
        monkeypatch, tmp_path, "pytest>=99,<100" + chr(10))
    verdict = m.c_interpreteur_conforme_aux_requirements()
    assert not verdict.ok, (
        'une version hors bornes n a pas fait rougir la regle'
    )
    assert verdict.blocking is True, (
        'la regle doit rester BLOQUANTE : un faux vert se presenterait'
        ' comme un verdict'
    )
    joint = chr(10).join(verdict.errors)
    assert "pytest" in joint and ">=99" in joint
    assert "interpreteur courant" in joint, (
        'le refus doit nommer l interpreteur fautif, sinon il est inactionnable'
    )
    assert "tools/python/python.exe" in joint, (
        'le refus doit donner le remede : l interpreteur epingle du depot'
    )


def test_la_regle_ROUGIT_sur_un_paquet_absent(monkeypatch, tmp_path):
    m = _requirements_bidon(
        monkeypatch, tmp_path,
        "paquet-qui-n-existe-pas-du-tout>=1" + chr(10))
    verdict = m.c_interpreteur_conforme_aux_requirements()
    assert not verdict.ok
    assert any("ABSENT" in e for e in verdict.errors)


def test_la_regle_ROUGIT_plutot_que_de_ne_rien_mesurer(monkeypatch, tmp_path):
    """Un fichier vide, ou absent, ne doit pas donner un vert favorable."""
    m = _requirements_bidon(
        monkeypatch, tmp_path, "# que des commentaires" + chr(10))
    verdict = m.c_interpreteur_conforme_aux_requirements()
    assert not verdict.ok, 'aucune borne lue = regle AVEUGLE, donc refus'
    assert any("AVEUGLE" in e for e in verdict.errors)

    (tmp_path / "requirements.txt").unlink()
    verdict = m.c_interpreteur_conforme_aux_requirements()
    assert not verdict.ok, 'fichier absent = refus, jamais un vert'
    assert verdict.blocking is True


def test_la_regle_est_bien_branchee_dans_le_plan_bloquant():
    """Une regle non enregistree ne protege personne."""
    source = (RACINE / "tools" / "audit_report.py").read_text(encoding="utf-8")
    assert "c_interpreteur_conforme_aux_requirements," in source, (
        'la regle n est pas listee dans `plan` : elle ne tournera jamais'
    )


# ------------------------------------------------- le GARDE n'est plus accuse (discriminant AST)
def test_un_litteral_exchange_examine_n_est_pas_un_chemin_d_execution():
    """Mesure du 21/11/2026 : la regle 13 rougissait sur le seul garde du depot.

    `if "/exchange" in url` EXAMINE la chaine ; une chaine assignee, concatenee ou
    passee a une requete l'EMPLOIE. Seul le second cas est une porte.
    """
    m = _audit()
    assert m._lignes_exchange_utilisees(
        'if "/exchange" in url.casefold():\n    raise ValueError("refuse")\n') == set()
    assert m._lignes_exchange_utilisees('if "/exchange" not in url:\n    pass\n') == set()
    assert m._lignes_exchange_utilisees('URL = "/exchange"\n') == {1}
    assert m._lignes_exchange_utilisees(
        'import urllib.request\nurllib.request.urlopen(BASE + "/exchange")\n') == {2}
    # Un tuple d'URL n'est pas un garde : il reste signale (conservateur).
    assert m._lignes_exchange_utilisees('AUTORISEES = ("/exchange",)\n') == {1}


def test_un_fichier_inanalysable_compte_toutes_les_occurrences():
    """Fail-closed : ne pas savoir lire n'est pas une raison de declarer propre."""
    m = _audit()
    assert m._lignes_exchange_utilisees('def f(:\n    "/exchange"\n') is None


def test_la_regle_13_rougit_toujours_sur_un_vrai_emploi(tmp_path, monkeypatch):
    """Sans ce test, le discriminant pourrait rendre la regle aveugle."""
    m = _audit()
    piege = tmp_path / "faux_module.py"
    piege.write_text('URL = "/exchange"\n', encoding="utf-8")
    monkeypatch.setattr(m, "_py_files", lambda *dirs: [piege])
    monkeypatch.setattr(m, "_rel", lambda p: p.name)
    verdict = m.c_no_real_exec()
    assert not verdict.ok, "un vrai emploi de /exchange n a pas fait rougir la regle"
    assert any("faux_module.py:1" in e for e in verdict.errors), verdict.errors

    garde = tmp_path / "faux_garde.py"
    garde.write_text('if "/exchange" in url:\n    raise ValueError("refuse")\n', encoding="utf-8")
    monkeypatch.setattr(m, "_py_files", lambda *dirs: [garde])
    verdict = m.c_no_real_exec()
    assert verdict.ok, verdict.errors


# ------------------------------------- la suppression bornee et archivee n'est plus accusee
_COMPACTAGE = '''
def compacter(self):
    lignes = self.lire()
    chemin = self._write_archive(lignes)
    self.cx.execute("DELETE FROM seen_events WHERE row_sequence <= ?", (1,))
    return chemin
'''


def _ligne_du_delete(source: str) -> int:
    for numero, ligne in enumerate(source.split("\n"), start=1):
        if "DELETE FROM" in ligne:
            return numero
    raise AssertionError("aucun DELETE dans la source de test")


@pytest.mark.parametrize(
    ("transformation", "attendu", "nom"),
    [
        (lambda s: s, True, "archive AVANT + WHERE"),
        (lambda s: s.replace(" WHERE row_sequence <= ?", ""), False, "sans WHERE"),
        (lambda s: s.replace("    chemin = self._write_archive(lignes)\n", ""),
         False, "sans archivage"),
    ],
)
def test_le_discriminant_de_suppression_verifie_les_deux_conditions(transformation, attendu, nom):
    """Archiver AVANT et borner : les deux, sinon la ligne reste signalee."""
    m = _audit()
    source = transformation(_COMPACTAGE)
    assert m._suppression_archivee_et_bornee(source, _ligne_du_delete(source)) is attendu, nom


def test_une_archive_posterieure_ne_protege_rien():
    """Archiver APRES avoir supprime ne sauve rien : l'ordre est la propriete."""
    m = _audit()
    source = ('def compacter(self):\n'
              '    self.cx.execute("DELETE FROM seen_events WHERE row_sequence <= ?", (1,))\n'
              '    return self._write_archive([])\n')
    assert m._suppression_archivee_et_bornee(source, 2) is False


def test_une_source_inanalysable_reste_signalee():
    """Fail-closed : ne pas savoir lire ne vaut pas un laissez-passer."""
    m = _audit()
    assert m._suppression_archivee_et_bornee("def f(:\n  'DELETE FROM seen_events WHERE x'\n", 2) is False


def test_la_regle_du_ledger_rougit_toujours_sur_une_table_videe(tmp_path, monkeypatch):
    """Le discriminant ne doit pas rendre la regle aveugle a une vraie perte seche."""
    m = _audit()
    piege = tmp_path / "faux_ledger.py"
    piege.write_text('def purge(cx):\n    cx.execute("DELETE FROM event_ledger")\n', encoding="utf-8")
    monkeypatch.setattr(m, "_py_files", lambda *dirs: [piege])
    monkeypatch.setattr(m, "_rel", lambda p: p.name)
    verdict = m.c_ledger_append_only()
    assert not verdict.ok, "une table videe sans archivage n a pas fait rougir la regle"

    piege.write_text(_COMPACTAGE, encoding="utf-8")
    verdict = m.c_ledger_append_only()
    assert verdict.ok, verdict.errors
