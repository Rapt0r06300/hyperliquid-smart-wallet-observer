"""[LANCEUR items 7-câblage & 9] Orchestration de session : la COLLECTE alimente réellement le catalogue
canonique, et le lanceur intègre le moniteur. Prouve : ouverture -> session ACTIVE + pointeur + TOUTES les
sources déclarées (vivantes avec compteurs réels / absentes avec raison) ; métriques réelles (gaps/
reconnects) reportées ; clôture propre -> COMPLETE ; le .cmd ouvre la session, auto-démarre le moniteur,
et clôt à l'arrêt. 0 réseau.
"""
from __future__ import annotations

import time
from pathlib import Path

from hl_observer.ops import session_catalog as SC
from hl_observer.ops import session_harvest as SH
from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST
from tools import heartbeat_collecteur as HB

RACINE = Path(__file__).resolve().parents[1]
CMD = RACINE / "LANCER_HYPERSMART.cmd"
CORE = tuple(s for s in SOURCES_HARVEST if s.obligatoire)


def _battre_core(root, *, metriques_par_nom=None):
    metriques_par_nom = metriques_par_nom or {}
    for s in CORE:
        HB.battre(root, s.nom, n_ecrites=5, dernier_exchange_ts=int(time.time() * 1000) - 50,
                  metriques=metriques_par_nom.get(s.nom))


def test_ouvrir_cree_session_active_et_declare_toutes_les_sources(tmp_path):
    _battre_core(tmp_path)
    rid, cat = SH.ouvrir_session_harvest(tmp_path, run_id="harvest-fixe-1",
                                         now_ms=time.time() * 1000 + 100)
    assert cat["statut"] == SC.STATUT_ACTIVE
    assert SH.run_id_courant(tmp_path) == "harvest-fixe-1"       # pointeur COURANTE écrit
    # item 3 : TOUTES les sources attendues sont déclarées dans le catalogue.
    declarees = {v["source"] for v in cat["sources"].values()}
    for attendu in ("allmids-collector", "bbo-collector", "userfills-live",
                    "node-fills-global", "twap-slices", "bybit", "dydx-live"):
        assert attendu in declarees, attendu
    # une non-implémentée est DÉCLARÉE absente (raison), jamais inventée vivante.
    bybit = next(v for v in cat["sources"].values() if v["source"] == "bybit")
    assert bybit["raison_absence"] and bybit["sante"] == "GRISE"
    # une CORE fraîche est vivante avec compteurs réels.
    allmids = next(v for v in cat["sources"].values() if v["source"] == "allmids-collector")
    assert allmids["sante"] == "VERTE" and allmids["evenements_recus"] == 5


def test_metriques_reelles_remontent_dans_le_catalogue(tmp_path):
    _battre_core(tmp_path, metriques_par_nom={"bbo-collector": {"gaps_critiques": 4, "reconnects": 9}})
    rid, cat = SH.ouvrir_session_harvest(tmp_path, run_id="harvest-fixe-2",
                                         now_ms=time.time() * 1000 + 100)
    bbo = next(v for v in cat["sources"].values() if v["source"] == "bbo-collector")
    assert bbo["gaps"] == 4 and bbo["reconnects"] == 9
    # un gap critique rend la source NON saine -> déclarée avec une raison, pas verte en trompe-l'œil.
    assert bbo["sante"] == "ROUGE" and "gap" in bbo["raison_absence"]


def test_source_core_sans_heartbeat_est_declaree_absente(tmp_path):
    # seul allmids bat ; bbo/userfills manquent -> déclarés absents (aucun heartbeat), jamais omis.
    HB.battre(tmp_path, "allmids-collector", n_ecrites=3, dernier_exchange_ts=int(time.time() * 1000))
    rid, cat = SH.ouvrir_session_harvest(tmp_path, run_id="harvest-fixe-3",
                                         now_ms=time.time() * 1000 + 100)
    bbo = next(v for v in cat["sources"].values() if v["source"] == "bbo-collector")
    assert bbo["raison_absence"].startswith("aucun heartbeat") and bbo["sante"] == "ROUGE"


def _artefact_reel(root, run_id, rel="hl/allmids.jsonl", contenu=b"a\nb\n"):
    """item 3 : un vrai artefact catalogue (fichier present + non vide) — requis pour COMPLETE."""
    p = SC.chemin_session(root, run_id) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    SC.CatalogueSession(root, run_id).enregistrer_source(
        SC.EntreeSource("allmids-collector", "HYPERLIQUID", "allMids", chemin=rel))


def _artefacts_core(root, run_id):
    """item 5 : chaque source CORE declaree VIVANTE doit avoir son artefact reel pour devenir COMPLETE."""
    c = SC.CatalogueSession(root, run_id)
    for s in CORE:
        rel = "hl/%s.jsonl" % s.nom
        p = SC.chemin_session(root, run_id) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("evenements %s\n" % s.nom).encode())
        c.enregistrer_source(SC.EntreeSource(s.nom, s.venue, s.canal, chemin=rel))


def test_cloture_propre_donne_complete(tmp_path):
    _battre_core(tmp_path)
    SH.ouvrir_session_harvest(tmp_path, run_id="harvest-fixe-4", now_ms=time.time() * 1000 + 100)
    _artefacts_core(tmp_path, "harvest-fixe-4")              # item 5 : artefact pour CHAQUE source vivante
    _ecrire_registre(tmp_path, {})                          # item 8 : registre present, 0 collecteur vivant
    v = SH.cloturer_session_courante(tmp_path, writers_arretes=True)
    assert v["statut"] == SC.STATUT_COMPLETE and v["run_id"] == "harvest-fixe-4"
    # la dernière session COMPLETE est retrouvable par ANALYSER.
    derniere = SC.derniere_session_complete(tmp_path)
    assert derniere["run_id"] == "harvest-fixe-4"


def test_cloture_quarantaine_si_source_vivante_sans_artefact(tmp_path):
    # item 5 : 3 CORE declarees VIVANTES mais UN SEUL artefact -> QUARANTINED (un fichier ne couvre pas tout).
    _battre_core(tmp_path)
    SH.ouvrir_session_harvest(tmp_path, run_id="harvest-partiel", now_ms=time.time() * 1000 + 100)
    _artefact_reel(tmp_path, "harvest-partiel")             # seulement allmids
    v = SH.cloturer_session_courante(tmp_path, writers_arretes=True)
    assert v["statut"] == SC.STATUT_QUARANTINED and "SOURCE_VIVANTE_SANS_ARTEFACT" in v["motifs"]


def test_cloture_sans_writers_arretes_quarantaine(tmp_path):
    _battre_core(tmp_path)
    SH.ouvrir_session_harvest(tmp_path, run_id="harvest-fixe-5", now_ms=time.time() * 1000 + 100)
    v = SH.cloturer_session_courante(tmp_path, writers_arretes=False)
    assert v["statut"] == SC.STATUT_QUARANTINED and "WRITERS_ENCORE_ACTIFS" in v["motifs"]


def test_cli_ouvrir_status_cloturer(tmp_path, capsys):
    _battre_core(tmp_path)
    assert SH.main(["ouvrir", str(tmp_path)]) == 0
    assert "SESSION_OUVERTE" in capsys.readouterr().out
    assert SH.main(["status", str(tmp_path)]) == 0
    assert "statut=ACTIVE" in capsys.readouterr().out
    rid = SH.run_id_courant(tmp_path)
    _artefacts_core(tmp_path, rid)                           # item 5 : artefact pour CHAQUE source vivante
    _ecrire_registre(tmp_path, {})                          # item 8 : registre present, 0 collecteur vivant
    assert SH.main(["cloturer", str(tmp_path), "--writers-arretes"]) == 0
    assert "statut=COMPLETE" in capsys.readouterr().out


def test_le_cmd_ouvre_session_auto_moniteur_et_cloture():
    txt = CMD.read_text(encoding="utf-8", errors="ignore")
    # item 7 câblage : ouverture de session après READY_CORE, AVANT le moteur.
    i_ouvrir = txt.index("session_harvest ouvrir")
    i_moteur = txt.index("start_hypersmart_simulation.ps1", i_ouvrir)
    assert i_ouvrir < i_moteur
    # item 9 : moniteur auto-démarré (start /b, Python portable), plus besoin de "sante" manuelle.
    assert 'start "" /b "%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante' in txt
    i_moniteur = txt.index('start "" /b "%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante')
    assert i_ouvrir < i_moniteur < i_moteur
    # items 4 & 8 : clôture dans le chemin d'arrêt, SANS --writers-arretes aveugle (preuve calculee).
    assert '-m hl_observer.ops.session_harvest cloturer "%~dp0."' in txt
    assert 'cloturer "%~dp0." --writers-arretes' not in txt


def _ecrire_registre(root, collecteurs):
    from hl_observer.ops.registre_pids import REGISTRE_RELPATH
    import json as _j
    p = Path(root) / REGISTRE_RELPATH                                # <root>/runtime/data/lanceur_pids.json
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_j.dumps({"collecteurs": collecteurs}), encoding="utf-8")


def test_preuve_writers_arretes_independante_du_registre(tmp_path):
    _ecrire_registre(tmp_path, {"bbo-collector": 4242})
    arretes, vivants = SH.preuve_writers_arretes(tmp_path, pid_vivant=lambda pid: pid == 4242)
    assert arretes is False and "bbo-collector" in vivants           # un collecteur encore vivant
    arretes2, vivants2 = SH.preuve_writers_arretes(tmp_path, pid_vivant=lambda pid: False)
    assert arretes2 is True and vivants2 == []                       # tous morts -> preuve d'arret


def test_cloture_quarantaine_si_un_writer_vit_encore(tmp_path):
    # item 4 : meme si l'appelant atteste l'arret, un writer vivant -> QUARANTINED (la preuve prime).
    _battre_core(tmp_path)
    rid, _ = SH.ouvrir_session_harvest(tmp_path, run_id="harvest-vivant", now_ms=time.time() * 1000 + 100)
    _artefact_reel(tmp_path, rid)
    _ecrire_registre(tmp_path, {"bbo-collector": 4242})
    v = SH.cloturer_session_courante(tmp_path, writers_arretes=True, pid_vivant=lambda pid: pid == 4242)
    assert v["statut"] == SC.STATUT_QUARANTINED and "WRITERS_ENCORE_ACTIFS" in v["motifs"]
    assert v["preuve_writers_arretes"] is False and "bbo-collector" in v["writers_vivants"]


def test_preuve_writers_arretes_fail_closed_sans_registre(tmp_path):
    # item 8 : registre ABSENT -> arret NON prouve (fail-closed), jamais suppose arrete.
    arretes, motifs = SH.preuve_writers_arretes(tmp_path)
    assert arretes is False and "REGISTRE_ABSENT" in motifs
    # cloture sans registre -> QUARANTINED (writers non prouves arretes).
    _battre_core(tmp_path)
    SH.ouvrir_session_harvest(tmp_path, run_id="harvest-noreg", now_ms=time.time() * 1000 + 100)
    _artefacts_core(tmp_path, "harvest-noreg")
    v = SH.cloturer_session_courante(tmp_path)               # aucune attestation, aucun registre
    assert v["statut"] == SC.STATUT_QUARANTINED


def test_preuve_writers_arretes_fail_closed_registre_incomplet(tmp_path):
    import json as _j
    from hl_observer.ops.registre_pids import REGISTRE_RELPATH
    p = Path(tmp_path) / REGISTRE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_j.dumps({"role": "launcher"}), encoding="utf-8")   # pas de cle 'collecteurs' = corrompu
    arretes, motifs = SH.preuve_writers_arretes(tmp_path)
    assert arretes is False and "REGISTRE_INCOMPLET" in motifs
