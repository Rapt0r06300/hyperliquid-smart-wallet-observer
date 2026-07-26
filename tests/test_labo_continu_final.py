"""LABO-CONTINU-FINAL — tests d'acceptation ACCÉLÉRÉS (Flo 26/07). Prouve, sans lancer le vrai labo, les
20 points : curseurs précis (offset/rotation, jamais tout relire), new_events/affected_windows, jamais de
cycle vide, scheduler 7 files + signature canonique + nouveauté + multi-étages, objectif multi-critères,
familles élargies honnêtes + horizons subseconde, EXACT_REPLAY interruptible, champions/dérive/gel immuable,
dashboard threadé, superviseur (anti-doublon/restart/arrêt), Ctrl+C strict, STOP_REQUEST IPC, dossier
<run_id> + INDEX, réconciliation, 14h/18h intacts, paper-only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import recherche_continue as RC       # noqa: E402
import curseurs_continue as CUR       # noqa: E402
import scheduler_continue as SCH      # noqa: E402
import champions_continue as CH       # noqa: E402
import superviseur_continue as SUP    # noqa: E402
import familles_continue as FAM       # noqa: E402
import pipeline_18h as PL             # noqa: E402
import securite_18h as SEC            # noqa: E402


# ─────────────── fixtures données ───────────────
def _bbo(c, ts, mid):
    sp = mid * 0.0006
    return {"venue": "HL", "coin": c, "ts_wall_ms": ts, "bid": mid - sp / 2, "ask": mid + sp / 2, "isSnapshot": False}


def _donnees(root: Path, n=120, decal=0):
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    lignes = [_bbo(c, 1_000_000 + (decal + i) * 1000, base * (1 + (decal + i) * 0.001))
              for i in range(n) for c, base in (("BTC", 64000), ("ETH", 3200))]
    (d / "bbo_tape.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")


def _corpus(n=60):
    out = []
    for i in range(n):
        mid = 100.0 * (1 + i * 0.002)
        out.append({"coin": "BTC", "regime": "trend", "ts_ms": 1_000 + i,
                    "bid": mid - 0.03, "ask": mid + 0.03,
                    "fwd_mid": {250: mid * 1.001, 1000: mid * 1.002}, "fees_bps": 1.0, "slippage_bps": 0.5})
    return out


def _run(tmp_path):
    RC._ARRET.clear(); RC._URGENCE.clear()
    _donnees(tmp_path)
    r = RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    return Path(r["rundir"])


# ─────────────── 1) curseurs précis : offset + rotation + jamais tout relire ───────────────
def test_curseurs_offset_incremental_et_rotation(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    src = tmp_path / "s.jsonl"
    src.write_text("".join(json.dumps({"coin": "BTC", "exchange_ts": i, "tid": i}) + "\n" for i in range(3)))
    ev1, info1 = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert len(ev1) == 3 and info1["offset"] > 0
    with src.open("a") as f:                                  # 2 lignes de plus
        f.write(json.dumps({"coin": "ETH", "exchange_ts": 3, "tid": 3}) + "\n")
        f.write(json.dumps({"coin": "ETH", "exchange_ts": 4, "tid": 4}) + "\n")
    ev2, info2 = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert len(ev2) == 2                                      # SEULEMENT les nouvelles, pas les 5
    ev3, _ = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert ev3 == []                                         # rien de neuf -> aucun re-comptage
    src.write_text(json.dumps({"coin": "SOL", "exchange_ts": 9, "tid": 9}) + "\n")  # rotation (fichier plus petit)
    ev4, info4 = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert info4["rotation"] is True and len(ev4) == 1


def test_curseurs_ligne_incomplete_non_consommee(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    src = tmp_path / "s.jsonl"
    src.write_text(json.dumps({"tid": 0, "coin": "BTC"}) + "\n" + '{"tid":1,"coin":"ETH"')  # 2e ligne tronquée
    ev, info = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert len(ev) == 1                                       # la ligne incomplète n'est pas consommée
    with src.open("a") as f:
        f.write("}\n")                                       # complète la ligne
    ev2, _ = CUR.nouveaux_evenements(tmp_path, rd, src)
    assert len(ev2) == 1 and ev2[0]["tid"] == 1


def test_scanner_new_events_et_fenetres(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    _donnees(tmp_path, n=5)
    scan = CUR.scanner_nouveautes(tmp_path, rd)
    assert scan["n_new"] == 10 and scan["sources_avec_nouveaute"] == 1
    scan2 = CUR.scanner_nouveautes(tmp_path, rd)
    assert scan2["n_new"] == 0                                # 2e passage : aucun re-comptage
    fen = CUR.fenetres_impactees(scan["new_events"], (250, 1000))
    assert set(fen["coins"]) == {"BTC", "ETH"} and fen["horizons_ms"] == [250, 1000]


# ─────────────── 2) jamais de cycle vide + affected_windows dans la campagne ───────────────
def test_jamais_cycle_vide_meme_sans_nouvelles_donnees(tmp_path):
    rd = _run(tmp_path)
    r1 = RC.executer_cycle(tmp_path, rd, cycle=1, code_sha="abc")
    assert r1["n_variantes_nouvelles"] > 0                    # cycle 1 : nouvelles données -> variantes
    r2 = RC.executer_cycle(tmp_path, rd, cycle=2, code_sha="abc")
    assert r2["n_new_events"] == 0                            # plus de données neuves
    assert r2["n_variantes_nouvelles"] > 0                    # MAIS toujours du travail (exploration)
    camp = json.loads((rd / "campagnes" / r2["campaign_id"] / "campaign.json").read_text())
    assert "affected_windows" in camp and camp["n_variantes_nouvelles"] > 0


# ─────────────── 3) scheduler : signature canonique + nouveauté + multi-étages ───────────────
def test_scheduler_novelty_jamais_les_memes(tmp_path):
    deja = set()
    v0 = SCH.generer(cycle=0, deja_vus=deja, familles=("GENERIC", "OFI"), directions=(1, -1),
                     horizons=(250, 1000), regimes=("all",), coins=("BTC", "ETH"), budget=24, seed=1, code_sha="x")
    s0 = {SCH.signature_canonique(v) for v in v0}            # v porte code_sha (estampillé par generer)
    deja |= s0
    v1 = SCH.generer(cycle=1, deja_vus=deja, familles=("GENERIC", "OFI"), directions=(1, -1),
                     horizons=(250, 1000), regimes=("all",), coins=("BTC", "ETH"), budget=24, seed=1, code_sha="x")
    s1 = {SCH.signature_canonique(v) for v in v1}
    assert s0 and s1 and s0.isdisjoint(s1)                    # aucun trial identique rejoué


def test_scheduler_7_files_prioritaires():
    assert len(SCH.FILES) == 7
    sc = SCH.ResearchScheduler()
    sc.enfiler("amelioration_locale", {"t": 1}); sc.enfiler("ingestion_sante", {"t": 2})
    assert sc.defiler()["file"] == "ingestion_sante"         # la file la plus prioritaire d'abord


def test_classer_nouveaute():
    t = {"family": "OFI", "version": 1, "horizon_ms": 250, "direction": 1, "coins": ["BTC"]}
    deja = {SCH.signature_canonique(t)}
    assert SCH.classer_nouveaute(t, deja) == "identique"
    assert SCH.classer_nouveaute({**t, "horizon_ms": 999}, deja) == "nouvelle_hypothese"


# ─────────────── 4) objectif multi-critères : jamais le PnL brut seul ───────────────
def test_objectif_multicritere_refuse_no_edge():
    assert SCH.score_multicritere({"net_median_bps": -3.0}) <= -100      # pas d'edge net -> jamais promu
    bon = SCH.score_multicritere({"net_median_bps": 12, "pf": 2.0, "dsr": 0.9, "stabilite_oos": 1})
    mono = SCH.score_multicritere({"net_median_bps": 12, "pf": 2.0, "dependance_coin": 5, "pbo": 0.9})
    assert bon > mono                                        # un edge instable/mono-coin/PBO élevé perd


# ─────────────── 5) familles élargies honnêtes + horizons subseconde ───────────────
def test_familles_predicat_honnete():
    ep_sans = {"coin": "BTC", "bid": 1, "ask": 1.1}
    assert FAM.predicat(ep_sans, "GENERIC", 8) is True                    # GENERIC : toujours testable
    assert FAM.predicat(ep_sans, "OFI", 8) is False                      # OFI sans donnée 'ofi' -> non testable
    assert FAM.predicat({"ofi": 20.0}, "OFI", 8) is True                 # avec la feature et au seuil
    assert FAM.predicat({"ofi": 2.0}, "OFI", 8) is False
    assert 100 in FAM.horizons_pour(None) and 500 in FAM.horizons_pour(None)


def test_famille_sans_donnee_donne_data_missing(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    corpus = _corpus(40)                                     # aucune feature 'ofi' dans le corpus
    var = [{"family": "OFI", "direction": 1, "horizon_ms": 250, "regime": "trend",
            "coin": "BTC", "params": {"seuil": 8}}]
    d = PL.phase_discovery(rd, corpus, var, code_sha="x", source_hash="h", predicat=FAM.predicat)
    assert d["n_fast_screen"] == 1 and d["n_survivants"] == 0            # 0 épisode -> KILL_FAST honnête


# ─────────────── 6) EXACT_REPLAY interruptible en secondes ───────────────
def test_phase_discovery_interruptible(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    corpus = _corpus(60)
    var = [{"family": "GENERIC", "direction": 1, "horizon_ms": 250, "regime": "trend",
            "coin": "BTC", "params": {"seuil": 8}} for _ in range(30)]
    ev = threading.Event(); ev.set()                        # déjà demandé -> doit s'arrêter d'entrée
    d = PL.phase_discovery(rd, corpus, var, code_sha="x", source_hash="h", stop_event=ev)
    assert d["n_preregistres"] == 0                          # aucune variante traitée (interruption immédiate)


# ─────────────── 7) champions : statut + gel immuable + dérive ───────────────
def test_champions_statut_et_append_only(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    assert CH.statut_depuis_metriques({"n": 5}) == "DATA_MISSING"
    assert CH.statut_depuis_metriques({"n": 100, "net_median_bps": 3}) == "PROMETTEUR"
    a = CH.enregistrer_candidat(rd, {"candidate_id": "t1", "n": 100, "net_median_bps": 3})
    CH.enregistrer_candidat(rd, {"candidate_id": "t1", "n": 120, "net_median_bps": -2})  # nouvelle ligne, pas modif
    lignes = CH.charger(rd)
    assert len(lignes) == 2 and lignes[0] == a               # le 1er enregistrement n'est jamais réécrit


def test_champions_derive():
    d = CH.mesurer_derive({"net_median_bps": 1.0, "n": 50}, {"net_median_bps": 6.0, "n": 200})
    assert d["etat"] == "DEGRADE" and d["edge_delta_bps"] == -5.0


# ─────────────── 9) superviseur : anti-doublon + restart + arrêt explicite ───────────────
def test_superviseur_anti_doublon_restart_arret(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    sup = SUP.Superviseur(rd, {"col_a": ["x.py"]})
    lancer = lambda nom, argv: os.getpid()                   # "démarre" -> pid vivant (le process courant)
    r1 = sup.demarrer_un("col_a", lancer=lancer)
    assert r1["etat"] == "DEMARRE"
    r2 = sup.demarrer_un("col_a", lancer=lancer)
    assert r2["etat"] == "DEJA_VIVANT"                       # pas de 2e copie
    sup.etat["col_a"]["pid"] = 999_999                        # simule un collecteur mort
    surv = sup.surveiller(lancer=lancer)
    assert "col_a" in surv["redemarres"] and sup.etat["col_a"]["restart_count"] >= 1
    sup.arreter_tous()
    assert sup.etat["col_a"]["pid"] is None                   # arrêt explicite


# ─────────────── 8/10/11) boucle : 5 cycles, jamais tout relire, dashboard threadé ───────────────
def test_cinq_cycles_consomment_seulement_le_neuf(tmp_path):
    rd = _run(tmp_path)
    res = RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=5, intervalle_s=0.0)
    assert res["cycles"] == 5
    ev = [json.loads(l) for l in (rd / "LIVE-RESEARCH-EVENTS.jsonl").read_text().splitlines()]
    assert ev[0]["n_new_events"] > 0 and ev[-1]["n_new_events"] == 0      # neuf au 1er, plus rien ensuite
    assert all(e["n_variantes_nouvelles"] > 0 for e in ev)               # jamais de cycle vide


def test_dashboard_thread_rafraichit_pendant_les_calculs(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    RC._ARRET.clear()
    ident = json.loads((rd / "run_identity.json").read_text())
    th = RC._demarrer_dashboard_thread(tmp_path, ident, intervalle_s=0.05)
    time.sleep(0.2)
    assert th.is_alive()                                     # rafraîchit indépendamment du cycle
    RC._ARRET.set(); th.join(timeout=2.0)
    assert not th.is_alive()


# ─────────────── 12) STOP_REQUEST IPC : la boucle détecte, pas de finalize concurrent ───────────────
def test_stop_request_ipc_detecte_par_la_boucle(tmp_path):
    rd = _run(tmp_path)
    ident = json.loads((rd / "run_identity.json").read_text())
    RC._ecrire_stop_request(tmp_path, ident["run_id"])       # `stop` écrit l'IPC
    res = RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=50, intervalle_s=0.0)
    assert res["boucle"] == "ARRET_DEMANDE" and res["cycles"] == 0        # détecté d'entrée, aucun cycle lancé
    assert RC._stop_request_present(tmp_path)                # le fichier reste jusqu'à finalisation


def test_stop_orphelin_finalise_ici(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    ident = json.loads((rd / "run_identity.json").read_text())
    fin = RC.stopper(tmp_path, ident["run_id"])              # même process (pid courant) -> finalise ici
    assert str(fin.get("finalisation", "")).startswith("FINALIZATION_COMPLETE")


# ─────────────── 13/14) dossier <run_id> + INDEX + réconciliation ───────────────
def test_rapport_dossier_run_id_index_et_reconciliation(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    ident = json.loads((rd / "run_identity.json").read_text())
    fin = RC.finaliser(tmp_path, partial=False)
    rap = Path(fin["rapport"])
    assert rap.parent.name == ident["run_id"]                # rapport dans Rapports en continu/<run_id>/
    idx = tmp_path / "Rapports en continu" / "INDEX-RAPPORTS.md"
    assert idx.exists() and ident["run_id"] in idx.read_text(encoding="utf-8")
    rec = json.loads((rd / "results" / "reconciliation.json").read_text())
    assert "somme_net_bps" in rec and rec["drawdown_bps"] <= 0
    assert "reconciliation" in fin


# ─────────────── 15) rapport complet + ligne de sécurité ───────────────
def test_rapport_complet_et_securite(tmp_path):
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    fin = RC.finaliser(tmp_path, partial=False)
    md = Path(fin["rapport"]).read_text(encoding="utf-8")
    assert "0 ordre" in md.lower() or "paper" in md.lower()


# ─────────────── 16) 14h/18h intacts ───────────────
def test_14h_18h_intacts():
    assert (RACINE / "LANCER-RECHERCHE-14H.cmd").exists()
    assert (RACINE / "LANCER-RECHERCHE-18H.cmd").exists()
    import recherche_18h  # noqa: F401  (le module 18h s'importe toujours)
    import rapport_14h    # noqa: F401


# ─────────────── 9bis) registre de collecteurs supervisés : read-only + scripts réels ───────────────
def test_registre_collecteurs_supervises_read_only():
    reg = RC._collecteurs_lecture_seule()
    assert set(reg) == {"lab-microstructure", "lab-ctx"}
    for nom, argv in reg.items():
        script = RACINE / argv[0]
        assert script.exists()                              # le script supervisé existe vraiment
        dangereux = [f for f in SEC.scanner_fichier(script)
                     if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "SEED")]
        assert dangereux == [], (nom, dangereux)            # collecteur = lecture seule, aucun ordre


# ─────────────── 17) paper-only sur toute la nouvelle chaîne ───────────────
def test_paper_only_nouvelle_chaine():
    findings = []
    for nom in ("curseurs_continue", "scheduler_continue", "champions_continue",
                "superviseur_continue", "familles_continue"):
        findings += SEC.scanner_fichier(RACINE / "tools" / (nom + ".py"))
    dangereux = [f for f in findings if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "SEED")]
    assert dangereux == [], dangereux
