"""[LANCEUR items 10 & 11] Porte d'entree ANALYSER : selectionne la DERNIERE session COMPLETE, RECALCULE
les checksums, refuse ACTIVE/QUARANTINED, refuse une session alteree ; + le budget lab n'a plus de
plafond arbitraire (budget<=0 = grille entiere). Prouve aussi que le .cmd restaure portable_env, pose la
porte AVANT le lab, et passe un budget maximal. 0 reseau.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import analyser_session as AS
from hl_observer.ops import session_catalog as SC
from hl_observer.ops import lab_alpha as LA
from hl_observer.ops import lab_recherche as R
from hl_observer.ops.session_catalog import CatalogueSession, EntreeSource

RACINE = Path(__file__).resolve().parents[1]
CMD = RACINE / "ANALYSER_BACKTESTS_REPLAYS.cmd"


def _session_complete(root, run_id, *, rel="hl/a.jsonl", contenu=b"a\nb\n"):
    p = SC.chemin_session(root, run_id) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    c = CatalogueSession(root, run_id)
    c.demarrer(horloge=lambda: 1000.0)
    c.enregistrer_source(EntreeSource("allmids-collector", chemin=rel))
    c.cloturer(writers_arretes=True, horloge=lambda: 1001.0)
    return c


def test_no_go_si_aucune_session(tmp_path):
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and res["run_id"] is None
    assert "aucune session" in res["raison"].lower()


def test_no_go_si_seulement_active(tmp_path):
    CatalogueSession(tmp_path, "run-active").demarrer()      # ACTIVE, jamais analysee
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and "COMPLETE" in res["raison"]


def test_go_sur_session_complete_verifiee(tmp_path):
    _session_complete(tmp_path, "run-ok")
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.GO and res["run_id"] == "run-ok"
    assert res["verification"]["ok"] is True
    # rapport consolide ecrit sur disque
    assert (tmp_path / "runtime" / "reports" / "backtest_replay" / "ANALYSE_SESSION.md").is_file()


def test_item12_provenance_deny_by_default_et_real_execution_toujours_false(tmp_path):
    # AUD-001/073 : une session SANS attestation positive vaut UNKNOWN, jamais REEL par defaut
    # (une absence d'attestation n'est pas une preuve de donnee reelle). real_execution reste False.
    _session_complete(tmp_path, "run-inconnu")               # demarrer() sans data_origin -> UNKNOWN
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.GO
    assert res["data_origin"] == SC.ORIGINE_INCONNUE
    assert res["real_execution"] is False                    # invariant securite, INDEPENDANT de data_origin


def test_item12_attestation_reelle_positive_est_REEL(tmp_path):
    # seule une attestation POSITIVE (le vrai collecteur de production) rend la session REELLE.
    p = SC.chemin_session(tmp_path, "run-reel") / "hl/a.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a\nb\n")
    c = CatalogueSession(tmp_path, "run-reel")
    c.demarrer(data_origin=SC.ORIGINE_REEL, horloge=lambda: 1000.0)
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    c.cloturer(writers_arretes=True, horloge=lambda: 1001.0)
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.GO and res["data_origin"] == SC.ORIGINE_REEL


def test_item12_fixture_synthetique_etiquetee_synthetique(tmp_path):
    # une FIXTURE de test doit s'ETIQUETER SYNTHETIQUE -> jamais confondue avec du reel (faux vert).
    c = CatalogueSession(tmp_path, "run-synth")
    c.demarrer(data_origin=SC.ORIGINE_SYNTHETIQUE, horloge=lambda: 1000.0)
    (SC.chemin_session(tmp_path, "run-synth") / "hl").mkdir(parents=True, exist_ok=True)
    (SC.chemin_session(tmp_path, "run-synth") / "hl" / "a.jsonl").write_bytes(b"a\nb\n")
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    c.cloturer(writers_arretes=True, horloge=lambda: 1001.0)
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.GO and res["data_origin"] == SC.ORIGINE_SYNTHETIQUE
    assert res["real_execution"] is False                    # toujours False, meme sur du synthetique
    # la provenance est aussi persistee dans le catalogue de la session.
    assert SC.CatalogueSession(tmp_path, "run-synth").lire()["data_origin"] == SC.ORIGINE_SYNTHETIQUE


def test_no_go_si_session_alteree_apres_cloture(tmp_path):
    _session_complete(tmp_path, "run-corrompu")
    # altere le fichier APRES la cloture -> le checksum recalcule par ANALYSER doit diverger.
    (SC.chemin_session(tmp_path, "run-corrompu") / "hl" / "a.jsonl").write_bytes(b"ALTERE\n")
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and "VERIFICATION ECHOUEE" in res["raison"]


def test_prend_la_complete_la_plus_recente(tmp_path):
    _session_complete(tmp_path, "run-vieux")
    # une seconde COMPLETE plus recente (debut_ms plus grand)
    p = SC.chemin_session(tmp_path, "run-recent") / "hl/a.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"z\n")
    c = CatalogueSession(tmp_path, "run-recent")
    c.demarrer(horloge=lambda: 5000.0)
    c.enregistrer_source(EntreeSource("allmids-collector", chemin="hl/a.jsonl"))
    c.cloturer(writers_arretes=True, horloge=lambda: 5001.0)
    res = AS.analyser(tmp_path)
    assert res["run_id"] == "run-recent"


def test_cli_exit_codes(tmp_path, capsys):
    assert AS.main(["--root", str(tmp_path)]) == 2         # NO_GO
    _session_complete(tmp_path, "run-cli")
    assert AS.main(["--root", str(tmp_path)]) == 0         # GO
    assert "verdict=GO" in capsys.readouterr().out


def test_budget_maximal_couvre_toute_la_grille(monkeypatch):
    # item 11 : budget<=0 => grille entiere (plus de plafond 48/32 code en dur).
    n_grille = 1
    for v in R.ESPACE_DEFAUT.values():
        n_grille *= len(v)
    vus = {}

    def faux_rechercher(events, *, espace, leader_equity_defaut, budget, **kw):
        vus["budget"] = budget
        return {"candidats": [], "evalues": 0, "caches": 0, "verdict_global": "MORE_DATA"}

    monkeypatch.setattr(LA.R, "rechercher", faux_rechercher)
    LA.lancer_lab(racine=".", sortie_dir="/tmp/_lab_maximal_test", budget=0, source="SYNTHETIQUE")
    assert vus["budget"] == n_grille                        # maximal = toute la grille


def test_le_cmd_restaure_portable_env_et_pose_la_porte_avant_le_lab():
    txt = CMD.read_text(encoding="utf-8", errors="ignore")
    assert "portable_env.cmd" in txt                        # item 10 : meme Python que le runtime
    i_porte = txt.index("analyser_session")
    i_lab = txt.index("lab_alpha", i_porte)
    assert i_porte < i_lab                                  # la porte AVANT le lab
    assert "exit /b 5" in txt                               # NO_GO bloque l'analyse
    assert "--budget %HYPERSMART_LAB_BUDGET%" in txt        # budget maximal surchargeable


def test_item14_refuse_vieille_complete_si_plus_recente_active(tmp_path):
    # une COMPLETE ancienne + une ACTIVE plus recente -> on NE selectionne PAS la vieille en silence.
    a = CatalogueSession(tmp_path, "run-vieille-complete")
    a.demarrer(horloge=lambda: 1000.0)
    p = SC.chemin_session(tmp_path, "run-vieille-complete") / "x.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"a\n")
    a.enregistrer_source(EntreeSource("s", chemin="x.jsonl"))
    a.cloturer(writers_arretes=True, horloge=lambda: 1001.0)
    CatalogueSession(tmp_path, "run-active-recente").demarrer(horloge=lambda: 9000.0)  # plus recente, ACTIVE
    res = AS.analyser(tmp_path)
    assert res["verdict"] == AS.NO_GO and "pas COMPLETE" in res["raison"]
    # override explicite : autoriser la vieille COMPLETE.
    res2 = AS.analyser(tmp_path, autoriser_complete_ancienne=True)
    assert res2["verdict"] == AS.GO and res2["run_id"] == "run-vieille-complete"


def test_item14_seuil_de_fraicheur(tmp_path):
    c = CatalogueSession(tmp_path, "run-fraiche")
    c.demarrer(horloge=lambda: 1_000_000.0)
    p = SC.chemin_session(tmp_path, "run-fraiche") / "x.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"a\n")
    c.enregistrer_source(EntreeSource("s", chemin="x.jsonl"))
    c.cloturer(writers_arretes=True, horloge=lambda: 1_000_001.0)
    # "maintenant" = 1_000_050 s -> age ~49 s. seuil 10 s -> trop vieille ; seuil 100 s -> ok.
    res_vieux = AS.analyser(tmp_path, age_max_s=10.0, horloge=lambda: 1_000_050.0)
    assert res_vieux["verdict"] == AS.NO_GO and "trop vieille" in res_vieux["raison"]
    res_ok = AS.analyser(tmp_path, age_max_s=100.0, horloge=lambda: 1_000_050.0)
    assert res_ok["verdict"] == AS.GO and res_ok["age_s"] is not None
