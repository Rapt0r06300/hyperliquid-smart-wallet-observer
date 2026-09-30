"""[LANCEUR items 7,8,9,10,17] Recette E2E DETERMINISTE de la chaine complete, sans reseau ni Windows :

  heartbeats reels des collecteurs  ->  ouverture de SESSION (catalogue ACTIVE + sources declarees)
  ->  arret des writers  ->  CLOTURE (checksums recalcules + zero orphelin => COMPLETE)
  ->  ANALYSER : selectionne CETTE session COMPLETE, RE-verifie les checksums => GO.

C'est la preuve, cote code, des points que Flo verifiera aussi par les deux double-clics sous Windows
(item 17). Une session laissee ACTIVE, ou alteree apres cloture, DOIT donner NO_GO. 0 ordre, 0 reseau.
"""
from __future__ import annotations

import time
from pathlib import Path

from hl_observer.ops import analyser_session as AS
from hl_observer.ops import session_catalog as SC
from hl_observer.ops import session_harvest as SH
from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST
from tools import heartbeat_collecteur as HB

CORE = tuple(s for s in SOURCES_HARVEST if s.obligatoire)


def _registre_arrete(root):
    """item 8 : registre PID PRESENT avec 0 collecteur vivant -> preuve d'arret (fail-closed sinon)."""
    import json
    from hl_observer.ops.registre_pids import REGISTRE_RELPATH
    p = Path(root) / REGISTRE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"collecteurs": {}}), encoding="utf-8")


def test_chaine_complete_collecte_session_cloture_analyser(tmp_path):
    # 1) COLLECTE : heartbeats CORE frais.
    for s in CORE:
        HB.battre(tmp_path, s.nom, n_ecrites=10, dernier_exchange_ts=int(time.time() * 1000) - 20)

    # 2) OUVERTURE de session : catalogue ACTIVE + toutes les sources declarees.
    rid, cat = SH.ouvrir_session_harvest(tmp_path, run_id="e2e-run-1", now_ms=time.time() * 1000 + 50)
    assert cat["statut"] == SC.STATUT_ACTIVE

    # 2bis) des artefacts de donnees reels apparaissent dans la session ; on les catalogue avec checksum.
    dossier = SC.chemin_session(tmp_path, rid)
    c = SC.CatalogueSession(tmp_path, rid)
    for s in CORE:
        rel = "hl/%s.jsonl" % s.nom
        p = dossier / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("evenements %s\n" % s.nom).encode() * 50)
        c.enregistrer_source(SC.EntreeSource(s.nom, s.venue, s.canal, chemin=rel,
                                             evenements_recus=10, evenements_valides=10))

    # 3) ARRET des writers puis CLOTURE : COMPLETE seulement si tout verifie.
    _registre_arrete(tmp_path)
    verdict = SH.cloturer_session_courante(tmp_path, writers_arretes=True)
    assert verdict["statut"] == SC.STATUT_COMPLETE, verdict
    assert verdict["verifications"]["zero_orphelin"] is True
    assert verdict["verifications"]["checksums_ok"] is True

    # 4) ANALYSER : selectionne CETTE session COMPLETE et RE-verifie -> GO.
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.GO and res["run_id"] == "e2e-run-1"
    assert res["verification"]["ok"] is True
    assert res["verification"]["n_artefacts_verifies"] == len(CORE)


def test_chaine_refuse_session_active(tmp_path):
    # collecte + ouverture, mais PAS de cloture -> la session reste ACTIVE -> ANALYSER NO_GO.
    for s in CORE:
        HB.battre(tmp_path, s.nom, n_ecrites=5, dernier_exchange_ts=int(time.time() * 1000) - 20)
    SH.ouvrir_session_harvest(tmp_path, run_id="e2e-active", now_ms=time.time() * 1000 + 50)
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and "COMPLETE" in res["raison"]


def test_chaine_refuse_session_alteree_apres_cloture(tmp_path):
    for s in CORE:
        HB.battre(tmp_path, s.nom, n_ecrites=5, dernier_exchange_ts=int(time.time() * 1000) - 20)
    rid, _ = SH.ouvrir_session_harvest(tmp_path, run_id="e2e-altere", now_ms=time.time() * 1000 + 50)
    dossier = SC.chemin_session(tmp_path, rid)
    c = SC.CatalogueSession(tmp_path, rid)
    # item 5 : chaque source CORE vivante a son artefact ; on garde une reference sur bbo pour l'alterer.
    p_bbo = None
    for s in CORE:
        rel = "hl/%s.jsonl" % s.nom
        p = dossier / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("origine %s\n" % s.nom).encode())
        c.enregistrer_source(SC.EntreeSource(s.nom, s.venue, s.canal, chemin=rel))
        if s.nom == "bbo-collector":
            p_bbo = p
    _registre_arrete(tmp_path)
    assert SH.cloturer_session_courante(tmp_path, writers_arretes=True)["statut"] == SC.STATUT_COMPLETE
    # altération APRES cloture -> ANALYSER recalcule et refuse.
    p_bbo.write_bytes(b"DONNEES FALSIFIEES APRES CLOTURE\n")
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and "VERIFICATION ECHOUEE" in res["raison"]
