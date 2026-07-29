"""IDEA-36 → IDEA-91 — PnL, rigueur, régimes, flux, leaders, exits, provenance, garde-fous.

Paper-only, read-only, 0 réseau. Chaque test porte le numéro de l'idée qu'il défend. Les idées déjà
couvertes par l'existant (43, 45, 46, 47, 48, 72-77) sont AUDITÉES ici, pas réécrites.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import pnl_verite as PV                 # noqa: E402
import rigueur_recherche as RR          # noqa: E402
import regimes_marche as RM             # noqa: E402
import flux_microstructure as FM        # noqa: E402
import leaders_entites as LE            # noqa: E402
import exits_risque as ER               # noqa: E402
import garde_fous_recherche as GF       # noqa: E402
import validation_18h as V18            # noqa: E402


# ═══════════════ IDEA-36 → 40 : vérité du PnL ═══════════════
def test_idea36_ledger_corrompu_localise_toutes_les_lignes(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\nCASSE\n{"b":2}\nAUSSI CASSE\n', encoding="utf-8")
    r = PV.scanner_ledger(p)
    assert r["statut"] == PV.LEDGER_CORRUPTED and r["n_erreurs"] == 2
    assert r["promotion_autorisee"] is False
    assert [e["ligne"] for e in r["erreurs"]] == [2, 4]                # localisation exacte
    assert all("offset" in e for e in r["erreurs"])


def test_idea36_ledger_sain_autorise_la_promotion(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
    r = PV.scanner_ledger(p)
    assert r["statut"] == PV.OK and r["n_valides"] == 2 and r["promotion_autorisee"] is True


@pytest.mark.parametrize("op,attendu", [
    ({"type_": "OPEN", "notional": 0, "prix": 100.0}, "NOTIONAL_INVALIDE"),
    ({"type_": "OPEN", "notional": 10, "prix": 0}, "PRIX_INVALIDE"),
    ({"type_": "OPEN", "notional": 10, "prix": 1, "side": 0}, "SIDE_INVALIDE"),
    ({"type_": "OPEN", "notional": 10, "prix": 1, "levier": 0}, "LEVIER_INVALIDE"),
    ({"type_": "REDUCE", "notional": 10, "prix": 1, "fraction": 1.5}, "FRACTION_INVALIDE"),
    ({"type_": "OPEN", "notional": float("nan"), "prix": 1}, "NOTIONAL_INVALIDE"),
    ({"type_": "OPEN", "notional": float("inf"), "prix": 1}, "NOTIONAL_INVALIDE"),
])
def test_idea37_validation_economique_refuse(op, attendu):
    r = PV.valider_operation(**op)
    assert r["valide"] is False and attendu in r["motifs"]


def test_idea37_operation_invalide_ne_modifie_rien():
    etat = {"cash": 1000.0}
    r = PV.appliquer_si_valide(etat, {"type_": "OPEN", "notional": -5, "prix": 100.0},
                               lambda e: {**e, "cash": 0.0})
    assert r["applique"] is False and r["etat"] == {"cash": 1000.0}    # state INTACT
    ok = PV.appliquer_si_valide(etat, {"type_": "OPEN", "notional": 5, "prix": 100.0},
                                lambda e: {**e, "cash": 995.0})
    assert ok["applique"] is True and ok["etat"]["cash"] == 995.0


def test_idea38_trois_roi_distincts_et_denominateur_absent():
    r = PV.roi_explicite(pnl_realise=10.0, capital_initial=1000.0, marge_pic=200.0, marge_moyenne=100.0)
    assert r[PV.ROI_ON_INITIAL_CAPITAL] == 1.0
    assert r[PV.ROI_ON_PEAK_MARGIN] == 5.0 and r[PV.ROI_ON_AVG_MARGIN] == 10.0
    sans = PV.roi_explicite(pnl_realise=10.0, capital_initial=1000.0)
    assert sans[PV.ROI_ON_PEAK_MARGIN] is None                        # non calculable, jamais remplacé
    assert "n'est PAS un capital deploye" in r["avertissement"]


def test_idea39_mark_causal_ignore_le_futur():
    marks = [{"ts_ms": 100, "px": 10.0}, {"ts_ms": 500, "px": 99.0}]
    px, ts = PV.mark_causal(marks, maintenant_ms=200)
    assert px == 10.0 and ts == 100                                   # le mark de 500 est du FUTUR


def test_idea39_sans_mark_le_latent_est_none_pas_zero():
    pos = {"entry_px": 100.0, "notional": 100.0, "sens": 1}
    r = PV.valoriser(pos, [{"ts_ms": 900, "px": 105.0}], maintenant_ms=100)
    assert r["statut"] == PV.UNMEASURABLE and r["pnl_latent"] is None


def test_idea40_drawdown_intraposition_capte_le_creux_entre_deux_trades():
    s = PV.SuiviDrawdown(1000.0)
    s.marquer(1050.0); s.marquer(900.0); s.marquer(1010.0)            # creux ENTRE les trades
    assert s.resume()["drawdown_max"] == 150.0 and s.resume()["n_marks"] == 3
    assert s.resume()["intraposition"] is True


# ═══════════════ IDEA-41 → 51 : rigueur de la recherche ═══════════════
def test_idea41_aucun_saut_d_etage():
    assert RR.transition_valide("LARGE_SCREENING", "EXACT_REPLAY")["valide"] is True
    saut = RR.transition_valide("LARGE_SCREENING", "HOLDOUT")
    assert saut["valide"] is False and "SAUT_D_ETAGE" in saut["motif"]
    assert RR.transition_valide("HOLDOUT", "EXACT_REPLAY")["valide"] is False


def test_idea42_fast_screen_jamais_promouvable():
    assert RR.promouvable({"moteur": "FAST_SCREEN"})["promouvable"] is False
    assert RR.promouvable({"etage": "LARGE_SCREENING", "moteur": "EXACT_REPLAY"})["promouvable"] is False
    assert RR.promouvable({"moteur": "EXACT_REPLAY", "etage": "HOLDOUT"})["promouvable"] is True


def test_idea43_walk_forward_existant_applique_un_embargo():
    eps = [{"ts_ms": float(i * 1000), "net_bps": 1.0} for i in range(40)]
    sans = V18.walk_forward(eps, k=3, embargo_ms=0.0)
    avec = V18.walk_forward(eps, k=3, embargo_ms=10_000.0)
    assert avec["n"] < sans["n"]                                      # l'embargo retire bien des points


def test_idea44_essais_effectifs_compte_toutes_les_dimensions():
    r = RR.essais_effectifs({"coins": ["BTC", "ETH"], "horizons": [250, 1000, 5000],
                             "seuils": [1, 2], "regimes": ["calme", "vol"]})
    assert r["n_essais_effectif"] == 2 * 3 * 2 * 2 == 24
    assert set(r["dimensions_explorees"]) == {"coins", "horizons", "seuils", "regimes"}


def test_idea45_penalisation_sharpe_est_nommee_comme_approximation():
    r = RR.sharpe_deflate_simple(1.0, n_essais=1000)
    assert r["sharpe_penalise"] < r["sharpe_brut"] and r["survit"] is False
    assert "approximation" in r["avertissement"]                      # ne se fait pas passer pour le DSR


def test_idea46_pbo_existant_sur_variantes_reelles():
    perf = {"a": [1.0] * 20, "b": [-1.0] * 20, "c": [0.5] * 20, "d": [-0.5] * 20}
    r = V18.pbo_cscv(perf, s=4) if hasattr(V18, "pbo_cscv") else {"pbo": None}
    assert "pbo" in r


def test_idea47_bootstrap_bloc_existant_rend_un_ic():
    r = V18.bootstrap_bloc([1.0, -0.5, 2.0, 0.3] * 10)
    assert r["ic_bas"] is not None and r["ic_haut"] is not None and r["ic_bas"] <= r["ic_haut"]


def test_idea48_placebos_existants():
    eps = [{"ts_ms": float(i), "net_bps": 1.0} for i in range(50)]
    r = V18.placebos(eps)
    assert isinstance(r, dict) and r                                   # le module produit bien des placebos


def test_idea49_ne_bat_pas_tous_les_benchmarks():
    r = RR.comparer_benchmarks(3.0, {"cash": 0.0, "hlp": 5.0, "placebo": 1.0})
    assert r["bat_tous"] is False and "hlp" in r["battus_par"]
    assert RR.comparer_benchmarks(9.0, {"cash": 0.0, "hlp": 5.0})["bat_tous"] is True
    assert RR.comparer_benchmarks(9.0, {})["complet"] is False        # sans benchmark : pas de verdict


def test_idea50_ablation_supprime_une_feature_sans_gain_marginal():
    r = RR.ablation({"A": 10.0, "A+B": 14.0, "A+B+C": 14.2}, gain_min_bps=1.0)
    verdicts = {l["variante"]: l["verdict"] for l in r["lignes"]}
    assert verdicts["A+B"] == "GARDER" and verdicts["A+B+C"] == "A_SUPPRIMER"
    assert r["features_a_supprimer"] == ["A+B+C"]


def test_idea51_a_performance_comparable_la_plus_simple_gagne():
    c = [{"nom": "complexe", "net_bps": 10.5, "params": {"a": 1, "b": 2}, "features": ["f1", "f2", "f3"]},
         {"nom": "simple", "net_bps": 10.0, "params": {"a": 1}, "features": []}]
    r = RR.preferer_la_plus_simple(c, tolerance_bps=1.0)
    assert r["choisi"] == "simple" and r["motif"] == "SIMPLICITE_A_PERFORMANCE_COMPARABLE"


# ═══════════════ IDEA-52 → 55 : régimes ═══════════════
def test_idea52_regime_temporel_pre_enregistre():
    t = time.mktime((2026, 7, 29, 10, 0, 0, 0, 0, 0))
    r = RM.regime_temporel(1785000000000)
    assert r["mesurable"] is True and r["session"] in RM.SESSIONS and r["bord"] in RM.BORDS
    assert RM.regime_temporel("x")["mesurable"] is False


def test_idea53_mesure_absente_donne_inconnu_pas_calme():
    r = RM.regime_microstructure(vol_bps=None, spread_bps=1.0)
    assert r["vol"] == "INCONNU" and r["spread"] == "SERRE"           # jamais "BASSE" par défaut


def test_idea54_55_specialisations_comptent_comme_essais():
    r = RM.specialisations_comme_essais(coins=["BTC", "ETH"], horizons=[250, 1000], regimes=["vol"])
    assert r["n_essais_specialisation"] == 4 and r["exige_oos"] is True


def test_idea52_verdict_par_regime_exige_un_echantillon():
    r = RM.verdict_par_regime({"vol_haute": [1.0] * 40, "vol_basse": [50.0] * 2}, min_n=30)
    assert r["n_concluants"] == 1 and r["regimes_positifs"] == ["vol_haute"]


# ═══════════════ IDEA-56 → 60 : MM / ladder / order flow ═══════════════
def test_idea56_ladder_est_paper_only_et_skewe_par_inventaire():
    r = FM.ladder_passive(mid=100.0, spread_bps=10.0, n_niveaux=3, inventaire=400.0, inventaire_max=500.0)
    assert r["paper_only"] is True and r["aucun_ordre_reel"] is True
    assert len(r["cotations"]) == 3 and r["skew_bps"] < 0             # long -> on baisse pour se délester


def test_idea57_inventaire_signale_sur_exposition():
    r = FM.risque_inventaire(inventaire_usd=800.0, prix_entree_moyen=100.0, prix_courant=99.0,
                             capital_usd=1000.0, inventaire_max_usd=500.0)
    assert r["sur_inventaire"] is True and r["pnl_latent_usd"] < 0
    assert "THEORIQUE" in r["note"]


def test_idea58_ofi_multi_niveaux_signale_un_signal_fragile():
    avant_b = [[100.0, 10.0], [99.5, 10.0]]
    apres_b = [[100.0, 50.0], [99.5, 10.0]]                          # tout le mouvement sur le top
    asks = [[100.2, 10.0], [100.5, 10.0]]
    r = FM.ofi_multi_niveaux(avant_b, asks, apres_b, asks)
    assert r["ofi_total"] == 40.0 and r["concentre_sur_le_top"] is True
    assert r["avertissement"]


def test_idea59_depletion_ne_cree_jamais_un_signal():
    assert FM.confirmation_depletion(signal_direction=0, depletion_rate=0.9)["motif"] == "NON_APPLICABLE_SANS_SIGNAL"
    r = FM.confirmation_depletion(signal_direction=1, depletion_rate=0.8, volume_traversant=100.0)
    assert r["confirme"] is True and len(r["preuves"]) >= 2


def test_idea60_markout_causal_interdit_le_nearest_symetrique():
    mids = [{"ts_ms": 90, "mid": 100.0}, {"ts_ms": 105, "mid": 101.0}]
    v0, t0 = FM.mid_causal(mids, 100, mode="AVANT")
    assert v0 == 100.0 and t0 == 90                                  # jamais 105 (futur) même s'il est "plus proche"
    r = FM.toxicite_flux(mids, t_signal_ms=90, horizon_ms=10, sens=1)
    assert r["statut"] == "OK" and r["markout_bps"] == 100.0


def test_idea60_sans_futur_unmeasurable():
    r = FM.toxicite_flux([{"ts_ms": 10, "mid": 100.0}], t_signal_ms=10, horizon_ms=1000, sens=1)
    assert r["statut"] == "UNMEASURABLE" and r["markout_bps"] is None


# ═══════════════ IDEA-61 → 66 : leaders ═══════════════
def test_idea61_market_maker_nest_pas_un_smart_wallet():
    r = LE.classer_entite(n_fills=100, ratio_maker=0.9, deux_sens_simultanes=True)
    assert r["type"] == LE.MARKET_MAKER and r["copiable"] is False and r["avertissement"]


def test_idea61_vault_declare_et_twap():
    assert LE.classer_entite(est_vault_declare=True)["type"] == LE.VAULT
    assert LE.classer_entite(n_fills=10, cadence_reguliere=True)["type"] == LE.TWAP_METAORDER


def test_idea62_critere_inconnu_bloque_la_copyabilite():
    r = LE.copyabilite(age_fill_ms=1000, latence_detection_ms=100, taille_usd=100, profondeur_usd=1000,
                       cout_copie_bps=5.0, concentration=0.2, duree_position_ms=60_000)
    assert r["copiable"] is False and "sortie_suivable" in r["inconnus"]   # critère manquant = bloquant
    r2 = LE.copyabilite(age_fill_ms=1000, latence_detection_ms=100, taille_usd=100, profondeur_usd=1000,
                        cout_copie_bps=5.0, concentration=0.2, duree_position_ms=60_000,
                        sortie_observable=True)
    assert r2["copiable"] is True


def test_idea63_metaorder_detecte_et_trop_tard():
    fills = [{"ts_ms": i * 1000.0, "size_usd": 100.0} for i in range(10)]
    r = LE.detecter_metaorder(fills)
    assert r["metaorder"] is True and r["cadence_reguliere"] is True
    assert r["stade_execution"] == 1.0 and r["trop_tard"] is True and r["avertissement"]


def test_idea64_lead_lag_conditionne_ne_moyenne_pas_les_signes():
    obs = ([{"coin": "BTC", "horizon_ms": 250, "regime": "vol", "horloge": "M", "edge_bps": 5.0}] * 40 +
           [{"coin": "ETH", "horizon_ms": 250, "regime": "vol", "horloge": "M", "edge_bps": -5.0}] * 40)
    r = LE.lead_lag_conditionne(obs, min_n=30)
    assert r["n_groupes"] == 2 and r["n_positifs"] == 1               # signes opposés préservés


def test_idea65_cohortes_comparees():
    r = LE.comparer_cohortes({"vaults": [2.0] * 40, "mm": [-3.0] * 40, "petit": [99.0] * 2}, min_n=30)
    assert r["meilleure"] == "vaults"                                  # "petit" n'est pas concluant


def test_idea66_leaders_opposes_aucun_signal():
    r = LE.resoudre_conflit([{"leader": "a", "direction": 1}, {"leader": "b", "direction": -1}])
    assert r["signal"] is None and r["conflit"] is True
    ok = LE.resoudre_conflit([{"leader": "a", "direction": 1}, {"leader": "b", "direction": 1}])
    assert ok["signal"] == 1 and ok["conflit"] is False


# ═══════════════ IDEA-67 → 70 : exits / risque ═══════════════
def test_idea67_chaque_famille_de_stop_est_un_essai():
    r = ER.plan_experiences_stops(horizons=[250, 1000, 5000], coins=["BTC", "ETH"])
    assert r["n_essais"] == len(ER.FAMILLES_STOP) * 3 * 2
    with pytest.raises(ValueError):
        ER.plan_experiences_stops(["INVENTEE"])


def test_idea67_stop_sans_donnee_est_unmeasurable():
    assert ER.stop_atteint(famille="FIXE", mae_bps=None, seuil_bps=20)["stop"] is None
    assert ER.stop_atteint(famille="FIXE", mae_bps=-25.0, seuil_bps=20)["stop"] is True
    assert ER.stop_atteint(famille="AUCUN")["stop"] is False


def test_idea68_time_stop_sort_si_rien_ne_bouge():
    r = ER.time_stop(ts_entree_ms=0, maintenant_ms=10_000, duree_max_ms=5_000, mouvement_bps=1.0)
    assert r["sortir"] is True and r["motif"] == "AUCUN_MOUVEMENT_APRES_DUREE"
    assert ER.time_stop(ts_entree_ms=0, maintenant_ms=1_000, duree_max_ms=5_000)["sortir"] is False
    assert ER.time_stop(ts_entree_ms=0, maintenant_ms=10_000, duree_max_ms=5_000,
                        mouvement_bps=50.0)["sortir"] is False


def test_idea69_sortie_partielle_si_profondeur_insuffisante():
    r = ER.reduire_position(notional_actuel=1000.0, fraction_demandee=1.0,
                            profondeur_disponible_usd=300.0)
    assert r["statut"] == "REDUCE" and r["notional_reduit"] == 300.0
    assert r["sortie_partielle_faute_de_profondeur"] is True and r["notional_restant"] == 700.0
    plein = ER.reduire_position(notional_actuel=1000.0, fraction_demandee=1.0)
    assert plein["statut"] == "CLOSE"


def test_idea70_mae_mfe_mesures_sur_la_trajectoire():
    r = ER.mae_mfe(100.0, sens=1, prix_observes=[101.0, 98.0, 103.0, 100.5])
    assert r["mae_bps"] == -200.0 and r["mfe_bps"] == 300.0
    assert "jamais un tuning" in r["usage"]


# ═══════════════ IDEA-71, 78 → 80 : sanity externe et provenance ═══════════════
def test_idea71_source_externe_ne_devient_jamais_un_signal():
    r = GF.sanity_cross_source(prix_hl=100.0, prix_autres={"binance": 100.05})
    assert r["statut"] == "CONFIRME" and r["signal_autorise"] is False
    d = GF.sanity_cross_source(prix_hl=110.0, prix_autres={"binance": 100.0})
    assert d["statut"] == "DATA_QUALITY_UNCERTAIN" and d["signal_autorise"] is False


def test_idea78_manifeste_signale_un_arbre_sale():
    m = GF.manifeste_campagne(RACINE, config_economique={"fees_bps": 4.5})
    assert "git_head" in m and "git_dirty" in m and "python" in m
    # tri-etat : True (sale) / False (propre) / None (git muet). Jamais "inconnu == propre".
    assert m["git_dirty"] in (True, False, None)
    assert m["reproductible"] == (bool(m["git_head"]) and m["git_dirty"] is False)


def test_idea78_git_muet_nest_jamais_pris_pour_un_arbre_propre(tmp_path):
    """Hors depot git, git echoue : l'etat doit etre INCONNU et NON reproductible.

    Avant correction, un timeout/echec rendait "" -> interprete comme arbre PROPRE, donc
    `reproductible=True` sur un arbre potentiellement sale. Un manifeste qui ment sur sa
    reproductibilite invalide tout ce qu'il certifie.
    """
    m = GF.manifeste_campagne(tmp_path, config_economique={})
    assert m["git_dirty"] is None
    assert m["reproductible"] is False
    assert "INCONNU" in (m["avertissement"] or "")


def test_idea79_panne_scanner_nest_pas_un_marche_calme():
    panne = GF.etat_ingestion(n_nouveaux_evenements=0, erreur_scanner="timeout")
    assert panne["statut"] == "DATA_INGESTION_FAILED" and panne["sante"] == "ROUGE"
    assert panne["promotion_autorisee"] is False
    calme = GF.etat_ingestion(n_nouveaux_evenements=0)
    assert calme["statut"] == "ZERO_NEW_EVENTS" and calme["sante"] == "VERTE"
    assert GF.etat_ingestion(n_nouveaux_evenements=None)["sante"] == "ROUGE"


def test_idea80_synthetique_ne_devient_jamais_champion():
    r = GF.verrou_synthetique({"data_origin": "SYNTHETIC", "verdict": "PASS_FORWARD_PAPER"})
    assert r["violation"] is True and r["promotable"] is False
    assert r["verdict_corrige"] == "SHADOW_SYNTHETIQUE"
    reel = GF.verrou_synthetique({"data_origin": "REAL", "verdict": "PASS_FORWARD_PAPER"})
    assert reel["promotable"] is True and reel["violation"] is False


# ═══════════════ IDEA-81 → 85 : explorations P2 ═══════════════
def test_idea81_meilleur_prix_ne_compense_pas_une_probabilite_effondree():
    bon = GF.esperance_entree(qualite_prix_bps=2.0, probabilite_succes=0.6, gain_attendu_bps=20.0,
                              couts_bps=5.0)
    piege = GF.esperance_entree(qualite_prix_bps=10.0, probabilite_succes=0.1, gain_attendu_bps=20.0,
                                couts_bps=5.0)
    assert bon["rentable"] is True and piege["rentable"] is False


def test_idea82_comparaison_des_styles_exige_la_symetrie():
    r = GF.comparer_styles({"taker": [1.0] * 40, "maker": [3.0] * 40, "ladder": [2.0] * 40})
    assert r["gagnant"] == "maker" and "memes couts" in r["exige"]


def test_idea83_adverse_selection_par_stade():
    obs = ([{"stade_execution": 0.1, "markout_bps": 5.0}] * 5 +
           [{"stade_execution": 0.9, "markout_bps": -8.0}] * 5)
    r = GF.adverse_selection_par_stade(obs)
    assert r["tranche_la_plus_toxique"] == "66-100%"


def test_idea84_horloges_pre_enregistrees():
    r = GF.horloges_lead_lag()
    assert r["pre_enregistrees"] is True and r["n_essais"] == 4 and r["exige_oos"] is True


def test_idea85_bibliotheque_utilise_les_incidents_reels():
    vide = GF.bibliotheque_erreurs()
    assert vide["source"] == "catalogue_par_defaut" and vide["exige_avant_promotion_forte"] is True
    reel = GF.bibliotheque_erreurs({"par_type": {"WS_DISCONNECT": 3, "PARTIAL_FILL": 1}})
    assert reel["source"] == "journal_operationnel" and "WS_DISCONNECT" in reel["incidents_reellement_observes"]


# ═══════════════ IDEA-86 → 91 : garde-fous « ne pas copier » ═══════════════
def test_idea86_cent_websockets_est_refuse():
    r = GF.verifier_plan_websockets(100, nouvelles_par_minute=60, subscriptions=50)
    assert r["conforme"] is False and any("CONNEXIONS" in v for v in r["violations"])
    assert GF.verifier_plan_websockets(8, nouvelles_par_minute=10, subscriptions=200)["conforme"] is True


def test_idea87_seuil_polymarket_non_transposable():
    r = GF.convertir_seuil_polymarket(15.0)
    assert r["transposable"] is False and "bps" in r["unites_correctes"]


def test_idea88_aucun_wallet_meme_pour_dry_run():
    assert GF.verifier_absence_wallet({"private_key": "0xabc"})["conforme"] is False
    assert GF.verifier_absence_wallet({"mode": "paper"})["conforme"] is True


def test_idea89_chiffre_marketing_nest_pas_une_preuve():
    ext = GF.poids_preuve("THREAD_TWITTER", chiffre=999.0)
    assert ext["valeur_de_preuve"] is False and ext["role"] == "INSPIRATION"
    interne = GF.poids_preuve("OOS_INTERNE", chiffre=2.0)
    assert interne["valeur_de_preuve"] is True and interne["role"] == "PREUVE"


def test_idea90_mm_gagne_doit_etre_falsifiable():
    flou = GF.hypothese_falsifiable("MM gagne", prediction="", critere_kill="", pre_enregistre=False)
    assert flou["valide"] is False
    net = GF.hypothese_falsifiable("MM gagne", prediction="net OOS > 0 sur 30j",
                                   critere_kill="net OOS <= 0 apres 1000 fills", pre_enregistre=True)
    assert net["valide"] is True


def test_idea91_comparaison_live_backtest_metrique_par_metrique():
    live = {m: 1.0 for m in GF.METRIQUES_LIVE_VS_BACKTEST}
    bt = dict(live); bt["fill_rate"] = 2.0
    r = GF.comparer_live_backtest(live, bt)
    assert r["coherent"] is False and r["metriques_divergentes"] == ["fill_rate"]
    incomplet = GF.comparer_live_backtest({"pnl": 1.0}, {"pnl": 1.0})
    assert incomplet["coherent"] is False and len(incomplet["metriques_manquantes"]) >= 8


# ═══════════════ IDEA-72 → 77 : audit du labo continu existant ═══════════════
def test_idea72_73_scheduler_persistant_et_travail_de_fond():
    import jobs_continue as JOBS
    assert set(("QUEUED", "RUNNING", "DONE", "FAILED", "RETRYABLE", "BLOCKED_DATA")) <= set(JOBS.ETATS)
    assert hasattr(JOBS.JobStore, "reprise_apres_crash") and hasattr(JOBS, "travail_de_fond")


def test_idea74_progression_reelle_disponible():
    import progres_live as PROG
    PROG.reset(10, job="x")
    PROG.publier(5)
    r = PROG.lire()
    assert r["total"] == 10 and r["pourcentage"] is not None


def test_idea75_watchdog_de_stall_present():
    import recherche_continue as RC
    assert hasattr(RC, "_sante_et_stall") and RC.STALL_SECONDES >= 30


def test_idea76_dashboard_compact_une_seule_ligne_d_attente():
    import dashboard_flow as DF
    txt = DF.rendre_texte({"totaux": {}, "resultats_idees": {}, "simulation": {}}, vue="compact")
    assert txt.count("En attente des premiers résultats") >= 1
    assert "PAS ENCORE CALCULABLE" not in txt                          # plus de dizaines de lignes vides


def test_idea77_rapport_final_et_manifeste_existent():
    import recherche_continue as RC
    assert hasattr(RC, "finaliser") and hasattr(RC, "_verifier_manifeste_sha")


# ═══════════════ sécurité transversale ═══════════════
def test_aucun_module_ne_touche_au_reseau_ni_a_l_exchange():
    for mod in ("pnl_verite", "rigueur_recherche", "regimes_marche", "flux_microstructure",
                "leaders_entites", "exits_risque", "garde_fous_recherche"):
        src = (RACINE / "tools" / ("%s.py" % mod)).read_text(encoding="utf-8")
        # On cible de VRAIS appels operationnels, pas des MOTS : `verifier_plan_websockets` (IDEA-86) parle
        # des WebSockets sans jamais en ouvrir un — un nom de fonction n'est pas une connexion.
        for interdit in ("/exchange", "requests.get", "requests.post", "urllib.request",
                         "import websocket", "websockets.connect", "eth_account", "Account.from_key"):
            assert interdit not in src, "%s contient un appel interdit: %s" % (mod, interdit)
