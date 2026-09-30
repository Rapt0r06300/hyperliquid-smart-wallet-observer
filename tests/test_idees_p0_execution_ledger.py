"""IDEA-11 → IDEA-35 — exécution, microstructure, forward causal, ledger/PnL (P0). Paper-only, 0 réseau.

Une idée n'est traitée que si un test la PROUVE. Chaque test porte le numéro de l'idée qu'il défend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import execution_realiste as EX        # noqa: E402
import couts_verite as CV              # noqa: E402
import forward_causal as FC            # noqa: E402
import ledger_verite as LV             # noqa: E402
import moteur_execution_prod as MEP    # noqa: E402


# ═══════════════ IDEA-11 — TruthReconciler ═══════════════
def _maillons(**kw):
    base = {"CANONICAL_EVENT": 100, "SIGNAL": 10, "PAPER_FILL": 8, "OPEN": 8, "REDUCE": 0, "CLOSE": 8,
            "COSTS": 4.0, "CANDIDATE_PNL": 12.0, "PORTFOLIO_PNL": 12.0, "DASHBOARD": 12.0}
    base.update(kw)
    return base


def test_idea11_chaine_coherente_est_fiable():
    r = LV.TruthReconciler().verifier_candidat("c1", _maillons())
    assert r["statut"] == LV.OK and r["promotion_autorisee"] is True and r["quarantaine"] is False


def test_idea11_divergence_pnl_donne_pnl_untrusted_et_quarantaine():
    r = LV.TruthReconciler().verifier_candidat("c1", _maillons(DASHBOARD=99.0))
    assert r["statut"] == LV.PNL_UNTRUSTED and r["quarantaine"] is True
    assert r["promotion_autorisee"] is False and r["ecarts"]


def test_idea11_plus_de_fills_que_de_signaux_est_impossible():
    r = LV.TruthReconciler().verifier_candidat("c1", _maillons(PAPER_FILL=50))
    assert r["statut"] == LV.PNL_UNTRUSTED and any("PAPER_FILL" in e["maillon"] for e in r["ecarts"])


def test_idea11_maillon_manquant_bloque_la_promotion():
    m = _maillons(); m.pop("COSTS")
    r = LV.TruthReconciler().verifier_candidat("c1", m)
    assert "COSTS" in r["maillons_manquants"] and r["promotion_autorisee"] is False


def test_idea11_un_seul_candidat_en_quarantaine_bloque_le_global():
    t = LV.TruthReconciler()
    g = t.verifier_tous({"bon": _maillons(), "mauvais": _maillons(PORTFOLIO_PNL=1.0)})
    assert g["n_quarantaine"] == 1 and g["promotion_globale_autorisee"] is False


# ═══════════════ IDEA-12/13 — prix exécutable + VWAP profondeur (audit de l'existant) ═══════════════
def test_idea12_prix_exit_executable_utilise_le_carnet_futur():
    ep = {"bid": 100.0, "ask": 100.2, "fwd_bid": {1000: 101.0}, "fwd_ask": {1000: 101.2}}
    px, src = MEP.prix_exit_executable(ep, sens=1, horizon_ms=1000)
    assert px == 101.0 and src == "FWD_BOOK"                          # long sort au BID futur
    px_s, _ = MEP.prix_exit_executable(ep, sens=-1, horizon_ms=1000)
    assert px_s == 101.2                                              # short sort à l'ASK futur


def test_idea12_sans_carnet_futur_le_prix_est_approximatif_non_promouvable():
    ep = {"bid": 100.0, "ask": 100.2, "fwd_mid": {1000: 101.0}}
    px, src = MEP.prix_exit_executable(ep, sens=1, horizon_ms=1000)
    assert src != "FWD_BOOK" and src == "FWD_MID_MOINS_DEMISPREAD"    # approximation documentée
    px2, src2 = MEP.prix_exit_executable({"bid": 1.0, "ask": 2.0}, sens=1, horizon_ms=1000)
    assert px2 is None and src2 == "UNMEASURABLE"                     # sans futur : jamais un prix inventé


def test_idea13_vwap_marche_le_carnet_et_signale_la_profondeur_insuffisante():
    niveaux = [[100.0, 1.0], [100.5, 1.0]]                            # 100 USD + ~100.5 USD de profondeur
    r = MEP.vwap_profondeur(niveaux, 150.0)
    assert r["vwap"] > 100.0 and r["rempli_frac"] > 0                 # on a marché le 2e niveau
    manque = MEP.vwap_profondeur(niveaux, 10_000.0)
    assert manque["rempli_frac"] < 1.0                                # profondeur insuffisante = honnête


# ═══════════════ IDEA-14 — propagation des fills partiels ═══════════════
def test_idea14_fill_20pct_propage_partout():
    r = EX.propager_fill_partiel(requested_notional=1000.0, filled_notional=200.0, levier=2.0,
                                 couts_bps={"fees": 5.0}, gross_bps=100.0)
    assert r["statut"] == "PARTIAL_FILL" and r["fill_fraction"] == 0.2
    assert r["position_notional"] == 200.0 and r["turnover_usd"] == 200.0
    assert r["marge_usd"] == 100.0                                     # 200 / levier 2
    assert r["couts_usd"] == 0.1 and r["pnl_brut_usd"] == 2.0          # coûts et PnL sur 200, jamais 1000
    assert r["pnl_net_usd"] == 1.9


def test_idea14_aucun_fill_est_no_fill_honnete():
    r = EX.propager_fill_partiel(requested_notional=500.0, filled_notional=0.0)
    assert r["statut"] == "NO_FILL" and r["position_notional"] == 0.0 and r["turnover_usd"] == 0.0


# ═══════════════ IDEA-15/16 — fill maker et file d'attente ═══════════════
def test_idea15_no_fill_si_le_volume_ne_depasse_pas_la_file():
    r = EX.probabilite_fill_maker(taille_devant=100.0, notre_taille=10.0, volume_traversant=50.0)
    assert r["statut"] == "NO_FILL" and r["fill_probability"] == 0.0   # on n'offre jamais un fill


def test_idea15_fill_partiel_quand_le_reliquat_nous_atteint():
    r = EX.probabilite_fill_maker(taille_devant=100.0, notre_taille=10.0, volume_traversant=104.0)
    assert r["statut"] == "PARTIAL_FILL" and r["filled_size"] == 4.0 and r["filled_fraction"] == 0.4


def test_idea16_queue_depletion_rate_mesure():
    q = EX.position_file(taille_devant=100.0, annulations_devant=20.0, volume_traversant=30.0)
    assert q["queue_ahead"] == 50.0 and q["queue_depletion_rate"] == 0.5


def test_idea16_file_vide_donne_taux_inconnu():
    assert EX.position_file(taille_devant=0.0)["queue_depletion_rate"] is None


# ═══════════════ IDEA-17/18 — adverse selection et qualité du fill ═══════════════
def test_idea17_markouts_causaux_et_adverse_selection():
    r = EX.markouts_apres_fill(100.0, sens=1, mids_futurs={100: 99.9, 1000: 100.5})
    assert r["markout_100ms_bps"] == -10.0                             # le marché part contre nous
    assert r["adverse_selection_bps"] == 10.0
    assert r["markout_250ms_bps"] is None                              # horizon sans donnée = None, jamais 0


def test_idea18_fill_rate_eleve_mais_toxique_est_refuse():
    v = EX.qualite_fill(fill_rate=0.95, markout_bps=-8.0, net_bps=2.0)
    assert v["verdict"] == "FILL_TOXIQUE"
    assert EX.qualite_fill(fill_rate=0.95, markout_bps=3.0, net_bps=-1.0)["verdict"] == "MAUVAIS_NET"
    assert EX.qualite_fill(fill_rate=0.2, markout_bps=3.0, net_bps=2.0)["verdict"] == "OK"


# ═══════════════ IDEA-19/20 — coûts complets, anti-double-comptage ═══════════════
def test_idea19_composante_inconnue_bloque_la_promotion():
    couts = {"fees": CV.composante(4.5, statut=CV.KNOWN, source="profil", methode="taker")}
    agg = CV.additionner_couts(couts)
    assert agg["complet"] is False and agg["promotion_autorisee"] is False
    assert "funding" in agg["composantes_inconnues"]                   # absente = inconnue, jamais gratuite


def test_idea19_composante_known_exige_une_valeur():
    with pytest.raises(ValueError):
        CV.composante(None, statut=CV.KNOWN)


def test_idea19_net_marque_unmeasurable_si_incomplet():
    r = CV.net_apres_couts(20.0, {"fees": CV.composante(5.0, statut=CV.KNOWN)})
    assert r["net_bps"] == 15.0 and r["statut"] == CV.UNMEASURABLE and r["promotion_autorisee"] is False


def test_idea20_cout_deja_dans_le_prix_nest_pas_soustrait_deux_fois():
    couts = {c: CV.composante(0.0, statut=CV.NOT_APPLICABLE) for c in CV.COMPOSANTES}
    couts["fees"] = CV.composante(4.5, statut=CV.KNOWN, source="profil", methode="taker")
    couts["spread"] = CV.composante(6.0, statut=CV.KNOWN, source="vwap", methode="marche_carnet",
                                    included_in_price=True)
    r = CV.net_apres_couts(20.0, couts)
    assert r["cout_a_soustraire_bps"] == 4.5                           # le spread n'est PAS re-soustrait
    assert r["deja_inclus_dans_le_prix_bps"] == 6.0
    assert r["net_bps"] == 15.5 and r["promotion_autorisee"] is True


def test_idea20_composante_mal_declaree_est_refusee():
    with pytest.raises(ValueError):
        CV.additionner_couts({"fees": 4.5})                            # un float nu n'est pas une déclaration


# ═══════════════ IDEA-21 — capacité ═══════════════
def test_idea21_capacite_limitee_par_la_jambe_la_plus_restrictive():
    r = CV.capacite_round_trip(1000.0, 250.0)
    assert r["capacite_usd"] == 250.0 and r["jambe_limitante"] == "sortie"


def test_idea21_jambe_inconnue_rend_capacite_inconnue():
    assert CV.capacite_round_trip(1000.0, None)["statut"] == CV.UNMEASURABLE


def test_idea21_courbe_capacite_donne_le_notionnel_max_rentable():
    r = CV.courbe_capacite_nette([{"notional_usd": 10, "net_bps": 5.0},
                                  {"notional_usd": 100, "net_bps": 1.0},
                                  {"notional_usd": 500, "net_bps": -3.0}])
    assert r["notional_max_rentable_usd"] == 100 and r["capacite_non_nulle"] is True


def test_idea21_courbe_toute_negative_est_capacite_nulle():
    r = CV.courbe_capacite_nette([{"notional_usd": 10, "net_bps": -1.0}])
    assert r["capacite_non_nulle"] is False and r["notional_max_rentable_usd"] is None


# ═══════════════ IDEA-22/23/24 — latence, decay, timings ═══════════════
def test_idea22_budget_latence_complet_et_segments():
    ts = {"exchange_ts": 0, "recv_ts": 30, "feature_ready_ts": 35, "signal_ts": 40,
          "decision_ts": 45, "paper_intent_ts": 50, "modeled_fill_ts": 80}
    b = EX.budget_latence(ts)
    assert b["complet"] is True and b["total_ms"] == 80
    assert b["segments_ms"]["exchange_ts->recv_ts"] == 30 and not b["violations_causalite"]


def test_idea22_violation_de_causalite_detectee():
    b = EX.budget_latence({"exchange_ts": 100, "recv_ts": 50})
    assert b["violations_causalite"] and b["complet"] is False


def test_idea22_percentiles_latence():
    p = EX.percentiles_latence([10, 20, 30, 40, 100])
    assert p["n"] == 5 and p["p50"] == 30 and p["p95"] >= p["p50"] and p["p99"] >= p["p95"]
    assert EX.percentiles_latence([])["p50"] is None                   # échantillon vide = inconnu


def test_idea23_edge_decay_demi_vie():
    d = EX.edge_decay({50: 10.0, 100: 8.0, 250: 4.0, 500: 1.0})
    assert d["mesurable"] is True and d["edge_immediat_bps"] == 10.0
    assert d["demi_vie_ms"] == 250                                     # premier retard sous la moitié


def test_idea24_timing_avec_trop_peu_d_observations_non_concluant():
    r = EX.comparer_timings({"immediat": {"nets_bps": [5.0] * 40},
                             "plus_1s": {"nets_bps": [50.0] * 3}}, min_n=30)
    assert r["meilleur"]["timing"] == "immediat"                       # 50 bps sur 3 essais ne gagne pas
    assert r["n_non_concluants"] == 1


# ═══════════════ IDEA-25/26 — qualité d'entrée, break-even ═══════════════
def test_idea25_qualite_entree_mesure_spread_et_distance_mid():
    q = EX.qualite_entree(prix_entree=100.2, mid=100.1, bid=100.0, ask=100.2,
                          couts_bps={"fees": 4.5})
    assert q["mesurable"] is True and round(q["spread_bps"], 1) == 20.0
    assert q["distance_mid_bps"] > 0 and q["part_du_spread_payee"] == 1.0   # on paie tout le demi-spread
    assert q["edge_minimal_requis_bps"] == 4.5


def test_idea26_break_even_win_rate_minimal():
    r = EX.seuil_break_even({"fees": 9.0}, gain_moyen_bps=20.0, perte_moyenne_bps=20.0)
    assert r["cout_total_bps"] == 9.0 and r["win_rate_minimal"] == 0.725 and r["atteignable"] is True


def test_idea26_sans_gain_perte_le_win_rate_reste_inconnu():
    r = EX.seuil_break_even({"fees": 9.0})
    assert r["edge_minimal_bps"] == 9.0 and r["win_rate_minimal"] is None


# ═══════════════ IDEA-27/28 — SIGNAL_READY vs EPISODE_MATURED ═══════════════
def test_idea27_open_ne_connait_jamais_la_sortie():
    import inspect
    params = inspect.signature(FC.ouvrir_signal).parameters
    assert not any("exit" in p or "sortie" in p for p in params if p != "exit_rule")
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=1000.0,
                         horizon_ms=500.0, entry_px=100.0, notional=100.0)
    assert p["etat"] == FC.SIGNAL_READY and p["exit_px"] is None and p["net_bps"] is None
    assert p["exit_due_ts"] == 1500.0


def test_idea27_pas_de_fermeture_avant_echeance():
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=1000.0,
                         horizon_ms=500.0, entry_px=100.0, notional=100.0)
    r = FC.maturer(p, maintenant_ms=1200.0, prix_sortie=101.0)
    assert r["etat"] == FC.SIGNAL_READY and r["motif"] == "ECHEANCE_NON_ATTEINTE"


def test_idea28_maturation_a_l_echeance_produit_le_net():
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=0.0,
                         horizon_ms=100.0, entry_px=100.0, notional=100.0)
    r = FC.maturer(p, maintenant_ms=100.0, prix_sortie=101.0)
    assert r["etat"] == FC.EPISODE_MATURED and r["net_bps"] == 100.0 and r["promotable"] is True
    assert p["mode"] == FC.STATEFUL_FORWARD_PAPER and FC.PROSPECTIVE_MATURED_REPLAY != p["mode"]


def test_idea28_open_refuse_sans_prix_executable():
    with pytest.raises(ValueError):
        FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=0.0,
                         horizon_ms=10.0, entry_px=0.0, notional=100.0)


# ═══════════════ IDEA-29/30 — file chronologique et capital partagé ═══════════════
def test_idea29_ordre_chronologique_independant_de_l_ordre_python():
    a = [{"candidate_id": "z", "ts_signal_ms": 200.0}, {"candidate_id": "a", "ts_signal_ms": 100.0}]
    b = list(reversed(a))
    assert FC.file_chronologique(a) == FC.file_chronologique(b)
    assert FC.file_chronologique(a)[0]["candidate_id"] == "a"


def test_idea30_le_premier_signal_chronologique_obtient_le_capital():
    sig = [{"candidate_id": "tardif", "ts_signal_ms": 500.0},
           {"candidate_id": "premier", "ts_signal_ms": 100.0}]
    r = FC.allouer_capital(sig, capital=100.0, marge_par_trade=100.0)
    assert r["n_acceptes"] == 1 and r["acceptes"][0]["candidate_id"] == "premier"
    assert r["refuses"][0]["motif"] == "CAPITAL_INSUFFISANT"


def test_idea30_resultat_identique_quelle_que_soit_la_permutation():
    sig = [{"candidate_id": "c%d" % i, "ts_signal_ms": float(i)} for i in range(5)]
    r1 = FC.allouer_capital(sig, capital=200.0, marge_par_trade=100.0)
    r2 = FC.allouer_capital(list(reversed(sig)), capital=200.0, marge_par_trade=100.0)
    assert [s["candidate_id"] for s in r1["acceptes"]] == [s["candidate_id"] for s in r2["acceptes"]]


# ═══════════════ IDEA-31/32 — sorties reconstructibles, sortie non mesurable ═══════════════
def test_idea31_position_porte_tout_pour_etre_reconstruite():
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=-1, ts_signal_ms=10.0,
                         horizon_ms=90.0, entry_px=100.0, notional=50.0, exit_rule="TIME_STOP")
    for cle in ("horizon_ms", "exit_due_ts", "candidate_id", "exit_rule", "position_id"):
        assert p.get(cle) is not None


def test_idea31_fichier_corrompu_ne_fait_pas_disparaitre_une_sortie(tmp_path):
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=0.0,
                         horizon_ms=100.0, entry_px=100.0, notional=100.0)
    s = FC.SortiesReconstructibles(tmp_path / "pending.json")
    s.ecrire([p])
    (tmp_path / "pending.json").write_text("{{{ corrompu", encoding="utf-8")
    assert s.lire() == []                                              # illisible
    r = s.reconstruire([p])
    assert r["corrige"] is True and r["n_reconstruites"] == 1
    assert s.lire()[0]["position_id"] == p["position_id"]              # la sortie est retrouvée


def test_idea32_sortie_non_mesurable_conserve_la_position():
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=0.0,
                         horizon_ms=100.0, entry_px=100.0, notional=100.0)
    r = FC.maturer(p, maintenant_ms=100.0, prix_sortie=None)
    assert r["etat"] == FC.EXIT_UNMEASURABLE and r["sous_etat"] == FC.DATA_GAP
    assert r["promotable"] is False and r["position_id"] == p["position_id"]   # jamais supprimée
    assert r["net_bps"] == -50.0                                       # politique conservatrice, pas 0


def test_idea32_politique_inconnue_refusee():
    p = FC.ouvrir_signal(candidate_id="c1", coin="BTC", sens=1, ts_signal_ms=0.0,
                         horizon_ms=1.0, entry_px=100.0, notional=100.0)
    with pytest.raises(ValueError):
        FC.maturer(p, maintenant_ms=10.0, prix_sortie=None, politique="INVENTEE")


# ═══════════════ IDEA-33/34/35 — ledger, crash recovery, snapshot corrompu ═══════════════
def _ledger(tmp_path, n=3):
    p = tmp_path / "ledger.jsonl"
    evts = [LV.evenement_ledger(event_seq=1, event_id="e1", candidate_id="c1", type_="OPEN", ts_ms=1.0,
                                requested_notional=300.0, filled_notional=300.0, price_source="FWD_BOOK",
                                cout_usd=1.0),
            LV.evenement_ledger(event_seq=2, event_id="e2", candidate_id="c1", type_="CLOSE", ts_ms=2.0,
                                requested_notional=300.0, filled_notional=300.0, price_source="FWD_BOOK",
                                pnl_usd=5.0, cout_usd=1.0)][:n]
    p.write_text("\n".join(json.dumps(e) for e in evts) + "\n", encoding="utf-8")
    return p, evts


def test_idea33_evenement_ledger_complet_et_fill_fraction_derivee():
    e = LV.evenement_ledger(event_seq=7, event_id="x", candidate_id="c1", type_="OPEN", ts_ms=1.0,
                            requested_notional=1000.0, filled_notional=250.0, price_source="VWAP_L2")
    for cle in ("event_seq", "event_id", "candidate_id", "ts_ms", "requested_notional",
                "filled_notional", "fill_fraction", "price_source", "couts_bps", "state_version"):
        assert cle in e
    assert e["fill_fraction"] == 0.25


def test_idea33_sans_requested_la_fraction_reste_inconnue():
    e = LV.evenement_ledger(event_seq=1, event_id="x", candidate_id="c", type_="OPEN", ts_ms=0.0,
                            filled_notional=100.0)
    assert e["fill_fraction"] is None                                   # jamais 1.0 supposé


def test_idea34_rejeu_idempotent_ne_double_jamais_le_pnl(tmp_path):
    _, evts = _ledger(tmp_path)
    a = LV.rejouer(evts, capital_initial=1000.0, levier=3.0)
    b = LV.rejouer(evts + evts, capital_initial=1000.0, levier=3.0)     # le MÊME ledger rejoué deux fois
    assert a["realized"] == b["realized"] and a["cash"] == b["cash"]
    assert a["last_applied_event_seq"] == 2


def test_idea34_reprise_applique_seulement_la_queue(tmp_path):
    p, evts = _ledger(tmp_path)
    snap = {"cash": 900.0, "realized": -1.0, "last_applied_event_seq": 1}
    r = LV.reprise_apres_crash(p, snap, capital_initial=1000.0, levier=3.0)
    assert r["statut"] == LV.OK and r["reconstruit_depuis_ledger"] is False
    assert r["etat"]["n_appliques"] == 1                                # seul l'event_seq 2 est appliqué


def test_idea35_snapshot_corrompu_declenche_recovery_et_ne_remet_pas_le_cash_a_neuf(tmp_path):
    p, _ = _ledger(tmp_path)
    r = LV.reprise_apres_crash(p, {"cash": "casse"}, capital_initial=1000.0, levier=3.0)
    assert r["statut"] == LV.RECOVERY_REQUIRED and r["reconstruit_depuis_ledger"] is True
    assert r["etat"]["realized"] != 0.0                                 # le PnL du ledger est retrouvé
    assert r["etat"]["last_applied_event_seq"] == 2


def test_idea35_ledger_corrompu_refuse_toute_reconstruction(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"event_seq": 1}\nPAS DU JSON\n', encoding="utf-8")
    r = LV.reprise_apres_crash(p, None)
    assert r["statut"] == LV.LEDGER_CORRUPTED and r["promotion_autorisee"] is False
    assert r["erreurs"][0]["ligne"] == 2 and "offset" in r["erreurs"][0]


def test_idea35_ledger_absent_est_ok_et_vide(tmp_path):
    r = LV.lire_ledger(tmp_path / "rien.jsonl")
    assert r["statut"] == LV.OK and r["n"] == 0


# ═══════════════ sécurité transversale ═══════════════
def test_aucun_module_ne_touche_au_reseau_ni_a_l_exchange():
    for mod in ("execution_realiste", "couts_verite", "forward_causal", "ledger_verite"):
        src = (RACINE / "tools" / ("%s.py" % mod)).read_text(encoding="utf-8")
        for interdit in ("/exchange", "requests.", "urllib.request", "websocket", "private_key",
                         "mnemonic", "eth_account"):
            assert interdit not in src, "%s contient %s" % (mod, interdit)
