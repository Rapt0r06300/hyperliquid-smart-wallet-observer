"""[items 6,7,4] Intégrité du DATA_CATALOG : chemins refusés (absolu / .. / symlink sortant / hors
session / doublon / vide), clé stable source_id, pas de double entrée vide+chemin, artefact LIVE mutable
sans checksum final (un fichier actif qui grandit ne quarantaine pas). 0 réseau.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import session_catalog as SC          # noqa: E402
from hl_observer.ops.session_catalog import CatalogueSession, EntreeSource, CatalogueInvalideError  # noqa: E402


def _session(tmp_path, rid="run-integrite"):
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    return c


def test_refuse_chemin_absolu(tmp_path):
    c = _session(tmp_path)
    with pytest.raises(CatalogueInvalideError):
        c.enregistrer_source(EntreeSource("s", chemin="/etc/passwd"))


def test_refuse_remontee_point_point(tmp_path):
    c = _session(tmp_path)
    with pytest.raises(CatalogueInvalideError):
        c.enregistrer_source(EntreeSource("s", chemin="../../secret.jsonl"))


def test_refuse_symlink_sortant(tmp_path):
    c = _session(tmp_path)
    dossier = SC.chemin_session(tmp_path, "run-integrite")
    dossier.mkdir(parents=True, exist_ok=True)
    dehors = tmp_path / "dehors.jsonl"
    dehors.write_bytes(b"x\n")
    lien = dossier / "lien.jsonl"
    try:
        os.symlink(dehors, lien)
    except (OSError, NotImplementedError):
        pytest.skip("symlink non supporte ici")
    with pytest.raises(CatalogueInvalideError):
        c.enregistrer_source(EntreeSource("s", chemin="lien.jsonl"))


def test_refuse_doublon_de_chemin(tmp_path):
    c = _session(tmp_path)
    dossier = SC.chemin_session(tmp_path, "run-integrite")
    (dossier / "hl").mkdir(parents=True, exist_ok=True)
    (dossier / "hl" / "a.jsonl").write_bytes(b"a\n")
    c.enregistrer_source(EntreeSource("s1", "HL", "c1", chemin="hl/a.jsonl"))
    with pytest.raises(CatalogueInvalideError):
        c.enregistrer_source(EntreeSource("s2", "HL", "c2", chemin="hl/a.jsonl"))   # même fichier


def test_source_id_stable_et_pas_de_double_entree_vide_plus_chemin(tmp_path):
    c = _session(tmp_path)
    dossier = SC.chemin_session(tmp_path, "run-integrite")
    (dossier / "hl").mkdir(parents=True, exist_ok=True)
    (dossier / "hl" / "bbo.jsonl").write_bytes(b"b\n")
    # d'abord DÉCLARÉE vivante sans artefact (entrée vide), puis son artefact réel arrive.
    c.enregistrer_source(EntreeSource("bbo-collector", "HL", "bbo", sante="VERTE"))
    c.enregistrer_source(EntreeSource("bbo-collector", "HL", "bbo", chemin="hl/bbo.jsonl", sante="VERTE"))
    sources = c.lire()["sources"]
    entrees_bbo = [v for v in sources.values() if v["source"] == "bbo-collector"]
    assert len(entrees_bbo) == 1 and entrees_bbo[0]["chemin"] == "hl/bbo.jsonl"   # plus d'entrée vide
    assert entrees_bbo[0]["source_id"] == "bbo-collector"                         # clé stable


def test_artefact_live_qui_grandit_ne_quarantaine_pas(tmp_path):
    # item 4 : enregistrement LIVE (sans checksum) ; le fichier grandit ; a la cloture -> COMPLETE.
    c = _session(tmp_path, "run-live")
    dossier = SC.chemin_session(tmp_path, "run-live")
    (dossier / "hl").mkdir(parents=True, exist_ok=True)
    p = dossier / "hl" / "live.jsonl"
    p.write_bytes(b"ligne1\n")
    c.enregistrer_artefact_live(EntreeSource("allmids-collector", "HL", "allMids", chemin="hl/live.jsonl",
                                             sante="VERTE"))
    p.write_bytes(b"ligne1\nligne2\nligne3\n")               # le writer a continue d'ecrire (mutable)
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_COMPLETE                 # jamais quarantaine pour un fichier qui a grandi
    # le SHA-256 DEFINITIF est calcule a la cloture (etat final).
    import hashlib
    attendu = hashlib.sha256(b"ligne1\nligne2\nligne3\n").hexdigest()
    assert c.lire()["sources"][EntreeSource("allmids-collector", "HL", "allMids",
                                            chemin="hl/live.jsonl").cle()]["checksum_sha256"] == attendu


def test_fichier_vide_refuse_complete(tmp_path):
    c = _session(tmp_path, "run-vide")
    dossier = SC.chemin_session(tmp_path, "run-vide")
    (dossier / "hl").mkdir(parents=True, exist_ok=True)
    (dossier / "hl" / "vide.jsonl").write_bytes(b"")          # artefact VIDE
    c.enregistrer_artefact_live(EntreeSource("allmids-collector", "HL", "allMids", chemin="hl/vide.jsonl",
                                             sante="VERTE"))
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "FICHIER_VIDE" in v["motifs"]
