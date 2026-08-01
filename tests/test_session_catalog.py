"""[LANCEUR items 7 & 8] Session canonique + DATA_CATALOG.json + clôture/quarantaine sûres.

Prouve : catalogue ACTIVE créé avec run_id/SHA/schéma ; enregistrement d'une source avec checksum+taille
calculés DEPUIS LE DISQUE ; clôture COMPLETE seulement si writers arrêtés + fichiers présents + checksums
recalculés OK + ZÉRO orphelin ; sinon QUARANTINED (writers actifs / checksum divergent / fichier manquant
/ orphelin) — jamais COMPLETE à tort, jamais de suppression. 0 réseau.
"""
from __future__ import annotations

import hashlib
import json

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.session_catalog import CatalogueSession, EntreeSource


def _run(root):
    return "run-fixe-000001"


def _ecrire(root, run_id, rel, contenu=b"abc\n"):
    p = SC.chemin_session(root, run_id) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    return p


def test_demarrer_cree_catalogue_actif(tmp_path):
    rid = _run(tmp_path)
    cat = CatalogueSession(tmp_path, rid).demarrer(git_head="deadbeef", contexte={"profil": "HARVEST"})
    assert cat["statut"] == SC.STATUT_ACTIVE
    assert cat["run_id"] == rid and cat["git_head"] == "deadbeef"
    assert cat["schema_catalogue"] == SC.SCHEMA_CATALOGUE
    assert cat["real_execution"] is False and cat["sources"] == {}
    # écrit sur disque, JSON valide, empreinte présente (item 7 : atomique)
    relu = json.loads(SC.chemin_catalogue(tmp_path, rid).read_text(encoding="utf-8"))
    assert relu["statut"] == SC.STATUT_ACTIVE and "empreinte" in relu


def test_demarrer_idempotent(tmp_path):
    rid = _run(tmp_path)
    c = CatalogueSession(tmp_path, rid)
    a = c.demarrer(git_head="a")
    b = c.demarrer(git_head="b")           # ne réécrase pas
    assert a["debut_ms"] == b["debut_ms"] and b["git_head"] == "a"


def test_sha256_fichier_streaming_egal_hashlib(tmp_path):
    rid = _run(tmp_path)
    p = _ecrire(tmp_path, rid, "d/x.jsonl", b"x" * 3_000_000)   # > 1 chunk
    h, taille = SC.sha256_fichier(p)
    assert taille == 3_000_000
    assert h == hashlib.sha256(b"x" * 3_000_000).hexdigest()
    assert SC.sha256_fichier(p.with_name("absent.jsonl")) == ("", -1)   # jamais un faux hash


def test_enregistrer_source_calcule_checksum_depuis_disque(tmp_path):
    rid = _run(tmp_path)
    _ecrire(tmp_path, rid, "hl/allmids.jsonl", b"line1\nline2\n")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    d = c.enregistrer_source(EntreeSource("allmids-collector", "HYPERLIQUID", "allMids",
                                          chemin="hl/allmids.jsonl", schema_version="v1",
                                          evenements_recus=2, evenements_valides=2))
    assert d["checksum_sha256"] == hashlib.sha256(b"line1\nline2\n").hexdigest()
    assert d["taille_octets"] == 12
    cat = c.lire()
    assert len(cat["sources"]) == 1


def test_source_absente_est_cataloguee_sans_artefact(tmp_path):
    # item 3/7 : une source absente/non-implémentée est DÉCLARÉE (raison) sans fichier — pas d'orphelin.
    rid = _run(tmp_path)
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    d = c.enregistrer_source(EntreeSource("bybit", "BYBIT", "trades", raison_absence="non implementee",
                                          sante="GRISE"))
    assert d["chemin"] == "" and d["raison_absence"] == "non implementee"


def test_cloture_complete_quand_tout_est_verifie(tmp_path):
    rid = _run(tmp_path)
    _ecrire(tmp_path, rid, "hl/allmids.jsonl", b"a\nb\n")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", "HYPERLIQUID", "allMids",
                                      chemin="hl/allmids.jsonl"))
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_COMPLETE
    assert v["verifications"]["zero_orphelin"] is True and v["verifications"]["checksums_ok"] is True
    cat = c.lire()
    assert cat["statut"] == SC.STATUT_COMPLETE and cat["fin_ms"] is not None


def test_cloture_refuse_si_writers_actifs(tmp_path):
    rid = _run(tmp_path)
    _ecrire(tmp_path, rid, "hl/a.jsonl")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    v = c.cloturer(writers_arretes=False)
    assert v["statut"] == SC.STATUT_QUARANTINED and "WRITERS_ENCORE_ACTIFS" in v["motifs"]
    assert c.lire()["statut"] == SC.STATUT_QUARANTINED       # jamais COMPLETE à tort


def test_cloture_quarantaine_si_checksum_divergent(tmp_path):
    rid = _run(tmp_path)
    p = _ecrire(tmp_path, rid, "hl/a.jsonl", b"origine\n")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    p.write_bytes(b"MODIFIE APRES CATALOGAGE\n")             # corruption/altération post-catalogue
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "CHECKSUM_DIVERGENT" in v["motifs"]
    assert v["divergences"][0]["probleme"] == "CHECKSUM"


def test_cloture_quarantaine_si_fichier_manquant(tmp_path):
    rid = _run(tmp_path)
    p = _ecrire(tmp_path, rid, "hl/a.jsonl")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    p.unlink()                                                # writer a disparu / fichier perdu
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "FICHIER_MANQUANT" in v["motifs"]


def test_cloture_quarantaine_si_orphelin(tmp_path):
    rid = _run(tmp_path)
    _ecrire(tmp_path, rid, "hl/a.jsonl")
    _ecrire(tmp_path, rid, "hl/ORPHELIN.jsonl")               # donnée non cataloguée
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "ORPHELINS" in v["motifs"]
    assert "hl/ORPHELIN.jsonl" in [o.replace("\\", "/") for o in v["orphelins"]]


def test_enregistrer_refuse_apres_cloture(tmp_path):
    rid = _run(tmp_path)
    _ecrire(tmp_path, rid, "hl/a.jsonl")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    c.cloturer(writers_arretes=True)
    try:
        c.enregistrer_source(EntreeSource("tardif", chemin="hl/a.jsonl"))
        assert False, "aurait dû lever : session figée"
    except SC.SessionFigeeError:
        pass


def test_quarantiner_ne_supprime_rien(tmp_path):
    rid = _run(tmp_path)
    p = _ecrire(tmp_path, rid, "hl/a.jsonl", b"data\n")
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    v = c.quarantiner("erreur archive/rotation")
    assert v["statut"] == SC.STATUT_QUARANTINED
    assert p.is_file() and p.read_bytes() == b"data\n"        # données intactes
    assert c.lire()["statut"] == SC.STATUT_QUARANTINED


def test_derniere_session_complete_ignore_active_et_quarantaine(tmp_path):
    # une COMPLETE ancienne, une ACTIVE récente, une QUARANTINED récente -> ANALYSER prend la COMPLETE.
    a = CatalogueSession(tmp_path, "run-1000-aaaa")
    a.demarrer(horloge=lambda: 1000.0)
    _ecrire(tmp_path, "run-1000-aaaa", "x.jsonl")
    a.enregistrer_source(EntreeSource("s", chemin="x.jsonl"))
    a.cloturer(writers_arretes=True, horloge=lambda: 1001.0)

    CatalogueSession(tmp_path, "run-3000-bbbb").demarrer(horloge=lambda: 3000.0)   # ACTIVE récente
    CatalogueSession(tmp_path, "run-4000-cccc").demarrer(horloge=lambda: 4000.0)
    CatalogueSession(tmp_path, "run-4000-cccc").quarantiner("x", horloge=lambda: 4001.0)  # QUARANTINED

    derniere = SC.derniere_session_complete(tmp_path)
    assert derniere is not None and derniere["run_id"] == "run-1000-aaaa"
    statuts = {s["run_id"]: s["statut"] for s in SC.scanner_sessions(tmp_path)}
    assert statuts["run-3000-bbbb"] == SC.STATUT_ACTIVE and statuts["run-4000-cccc"] == SC.STATUT_QUARANTINED


def test_nouveau_run_id_trie_et_unique():
    a = SC.nouveau_run_id("run", horloge=lambda: 1000.0)
    b = SC.nouveau_run_id("run", horloge=lambda: 2000.0)
    assert a != b and a.startswith("run-1000000-") and b.startswith("run-2000000-")


def test_cloture_refuse_complete_sans_artefact_reel(tmp_path):
    # item 3 : une session avec des sources DECLAREES mais AUCUN artefact reel ne devient jamais COMPLETE.
    rid = "run-sans-artefact"
    c = CatalogueSession(tmp_path, rid)
    c.demarrer()
    c.enregistrer_source(EntreeSource("bybit", "BYBIT", "trades", raison_absence="non implementee"))
    v = c.cloturer(writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "AUCUN_ARTEFACT_REEL" in v["motifs"]
    # backward-compat explicite : exiger_artefacts=False autorise une cloture technique sans artefact.
    c2 = CatalogueSession(tmp_path, "run-tech")
    c2.demarrer()
    assert c2.cloturer(writers_arretes=True, exiger_artefacts=False)["statut"] == SC.STATUT_COMPLETE
