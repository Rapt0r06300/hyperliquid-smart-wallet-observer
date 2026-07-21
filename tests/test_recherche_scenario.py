"""RECHERCHE DE SCÉNARIO — le « parfait » qu'on accepte est celui qui SURVIT.

Trois exécutions du même piège, tuées par trois barres :
  * le GAGNANT CHANCEUX (brille sur la moitié 1, meurt sur la 2) -> rejeté ;
  * le PIC ISOLÉ (passe les moitiés, ses voisins meurent)        -> rejeté (plateau W8) ;
  * le FRAGILE AUX COÛTS (net <= 0 à frais x1,5)                  -> rejeté (F29).
Et la fuite du 13/07 ne peut pas revenir : l'embargo jette les candidats à moins d'un
horizon de la coupe, DES DEUX côtés.
"""
from __future__ import annotations

from hl_observer.backtesting.recherche_scenario import (
    DonneesReplay, chercher, grille_configs, porte_robuste, voisins,
    MIN_TRADES_PAR_MOITIE,
)


def _cand(ts: float) -> dict:
    return {"recorded_at": ts, "coin": "HYPE", "strategie": "carry"}


DONNEES = DonneesReplay(
    candidats=[_cand(t) for t in (0, 1000, 2000, 3000, 30000, 40000, 50000, 60000)],
    marks=[])


# ------------------------------------------------------------------ 1. la coupe + embargo

def test_l_embargo_jette_les_candidats_trop_pres_de_la_coupe_DES_DEUX_COTES():
    """Fuite du 13/07 : sans embargo, les outcomes de fin de moitié 1 se réalisent dans la
    moitié 2. Ici : horizon 60 min -> 3600 s de marge. Le candidat pile sur la coupe meurt."""
    m1, m2 = DONNEES.moities_avec_embargo(60.0)
    assert [c["recorded_at"] for c in m1] == [0, 1000, 2000, 3000]
    assert [c["recorded_at"] for c in m2] == [40000, 50000, 60000]   # 30000 = la coupe, jetée


def test_sans_candidats_les_moities_sont_vides_pas_une_exception():
    assert DonneesReplay().moities_avec_embargo(60.0) == ([], [])


# ------------------------------------------------------------------ 2. l'espace de recherche

def test_la_grille_ne_genere_JAMAIS_un_ratio_perdant_par_construction():
    configs = list(grille_configs())
    assert configs and all(c["tp"] > c["sl"] for c in configs)


def test_les_voisins_restent_valides_et_au_nombre_attendu():
    vs = voisins({"sl": 40.0, "tp": 70.0, "horizon_min": 60.0})
    assert len(vs) == 4 and all(v["tp"] > v["sl"] > 0 for v in vs)
    # au bord de la grille (tp-20 <= sl), le voisin invalide disparait au lieu d'etre absurde
    assert len(voisins({"sl": 40.0, "tp": 55.0})) == 3


# ------------------------------------------------------------------ 3. la porte robuste

def _moitie(net: float, trades: int = 50, pf: float = 1.5) -> dict:
    return {"net_total_usd": net, "trades": trades, "profit_factor": pf}


def test_la_porte_exige_les_DEUX_moities_ET_le_stress():
    bon = {"moitie_1": _moitie(5.0), "moitie_2": _moitie(3.0), "stress": _moitie(1.0)}
    assert porte_robuste(bon) is True
    assert porte_robuste({**bon, "moitie_2": _moitie(-0.1)}) is False       # gagnant chanceux
    assert porte_robuste({**bon, "stress": _moitie(-0.5)}) is False         # fragile aux couts
    assert porte_robuste({**bon, "moitie_1": _moitie(5.0, trades=MIN_TRADES_PAR_MOITIE - 1)}) \
        is False                                                            # pas assez de preuves
    assert porte_robuste({**bon, "moitie_2": _moitie(3.0, pf=1.05)}) is False  # PF sous la barre
    assert porte_robuste({**bon, "moitie_1": _moitie(5.0, pf="inf")}) is True  # 0 perte = ok


# ------------------------------------------------------------------ 4. la recherche complète

def _fake_ab(nets: dict[float, tuple[float, float]]):
    """Fabrique un faux run_ab_replay : nets[sl] = (net_moitie_1, net_moitie_2).
    La moitié se reconnaît à son 1er candidat ; le stress aux coûts > défaut."""
    def evaluer_ab(candidats, marks, *, base_config, horizon_min, cost_bps):
        sl = base_config.stop_loss_bps
        n1, n2 = nets.get(sl, (-1.0, -1.0))
        if cost_bps > 15.0:                             # stress x1,5 (défaut 12 -> 18)
            net = (n1 + n2) - 1.0                       # les coûts mangent 1 $
        elif candidats and candidats[0]["recorded_at"] < 30000:
            net = n1
        else:
            net = n2
        return {"arm_a": {"net_total_usd": net, "trades": 60, "profit_factor": 1.5}}
    return evaluer_ab


def test_le_gagnant_chanceux_est_REJETE_et_le_survivant_PROMU(tmp_path):
    """CHANCEUX gagne 10 $ sur la moitié 1 et perd sur la 2 -> rejeté. SURVIVANT gagne
    modestement PARTOUT (et ses voisins aussi) -> promu. Le « parfait » est le second."""
    nets = {50.0: (10.0, -2.0),                          # le chanceux (sl=50)
            40.0: (3.0, 2.5),                            # le survivant (sl=40)
            30.0: (2.0, 2.0), 45.0: (2.0, 1.5), 35.0: (1.0, 1.0)}   # ses voisins vivants
    configs = [{"sl": 50.0, "tp": 90.0, "horizon_min": 60.0},
               {"sl": 40.0, "tp": 70.0, "horizon_min": 60.0}]
    r = chercher(tmp_path, configs=configs, donnees=DONNEES, evaluer_ab=_fake_ab(nets))
    assert r["statut"] == "PROMU"
    assert r["gagnant"]["sl"] == 40.0
    assert [e["verdict"] for e in r["essais"]] == ["REJETE", "PROMU"]
    assert (tmp_path / "runtime" / "replay" / "recherche_scenario_etat.json").exists()


def test_le_PIC_ISOLE_est_rejete_par_le_plateau(tmp_path):
    """sl=40 brille sur les deux moitiés... mais TOUS ses voisins perdent : pic isolé dans
    la grille = artefact (W8). La porte le refuse malgré ses belles moitiés."""
    nets = {40.0: (5.0, 4.0)}                            # voisins absents -> (-1,-1) perdants
    r = chercher(tmp_path, configs=[{"sl": 40.0, "tp": 70.0, "horizon_min": 60.0}],
                 donnees=DONNEES, evaluer_ab=_fake_ab(nets))
    assert r["statut"] == "ESPACE_EPUISE" and r["gagnant"] is None


def test_zero_candidat_est_un_INSUFFISANT_honnete(tmp_path):
    r = chercher(tmp_path, donnees=DonneesReplay(), evaluer_ab=_fake_ab({}))
    assert r["statut"] == "INSUFFISANT" and "W2" in r["motif"]


def test_le_resolveur_prefere_les_consolides_de_MERGED(tmp_path):
    """21/07 : le consolidateur ecrit dans _merged/ (pour ne pas se re-lire) mais la recherche
    lisait la RACINE -> INSUFFISANT devant 331 366 candidats. Un resolveur, trois lecteurs."""
    from hl_observer.backtesting.recherche_scenario import repertoire_replay_consolide
    base = tmp_path / "runtime" / "replay"
    (base / "_merged").mkdir(parents=True)
    assert repertoire_replay_consolide(tmp_path) == base          # pas de consolide -> racine
    (base / "_merged" / "candidates.jsonl").write_text("{}\n", encoding="utf-8")
    assert repertoire_replay_consolide(tmp_path) == base / "_merged"


# ---------------- 21/07 : PEPITES — tous les modules, populations JAMAIS melangees ----------------

def test_charger_filtre_par_strategie_les_seaux_d_alias(tmp_path):
    """262k signaux copy + candidats carry dans une meme grille = le scenario moyen de RIEN.
    Les '?' historiques sont du COPY (firehose) ; carry et arbitrage ont leurs seaux."""
    import json as _j
    base = tmp_path / "runtime" / "replay" / "_merged"; base.mkdir(parents=True)
    (base / "candidates.jsonl").write_text("\n".join([
        _j.dumps({"recorded_at": 1, "strategie": "carry"}),
        _j.dumps({"recorded_at": 2, "strategie": "?"}),
        _j.dumps({"recorded_at": 3}),                       # sans etiquette -> copy
        _j.dumps({"recorded_at": 4, "strategie": "arbitrage"}),
    ]) + "\n", encoding="utf-8")
    (base / "marks.jsonl").write_text("", encoding="utf-8")
    from hl_observer.backtesting.recherche_scenario import DonneesReplay
    assert len(DonneesReplay.charger(tmp_path, strategie="carry").candidats) == 1
    assert len(DonneesReplay.charger(tmp_path, strategie="copy").candidats) == 2
    assert len(DonneesReplay.charger(tmp_path, strategie="arbitrage").candidats) == 1
    assert len(DonneesReplay.charger(tmp_path).candidats) == 4      # compat : tout


def test_cross_venue_episode_paye_quand_la_dispersion_couvre_les_4_jambes():
    """20 bps/h pendant 2 h = 40 bps captures - 22 bps de couts = +18 bps -> +0.18$ /100$."""
    from hl_observer.backtesting.recherche_scenario import evaluer_episodes_cross_venue
    serie = ([{"coin": "BTC", "ts": 1000 + k * 600, "dispersion_bps_h": 20.0} for k in range(13)]
             + [{"coin": "BTC", "ts": 1000 + 13 * 600, "dispersion_bps_h": 0.0}])
    r = evaluer_episodes_cross_venue(serie, {"seuil_entree": 10.0, "seuil_sortie": 5.0})
    assert r["trades"] == 1
    # 13 intervalles de detention (on encaisse JUSQU'A l'observation de sortie incluse)
    assert abs(r["net_total_usd"] - ((20.0 * (13 * 600) / 3600 - 22.0) / 1e4 * 100)) < 1e-6
    # sous le seuil d'entree : aucun episode, jamais un trade invente
    r2 = evaluer_episodes_cross_venue(serie, {"seuil_entree": 50.0, "seuil_sortie": 5.0})
    assert r2["trades"] == 0


def test_cross_venue_INSUFFISANT_sous_500_observations(tmp_path):
    from hl_observer.backtesting.recherche_scenario import chercher_cross_venue
    r = chercher_cross_venue(tmp_path, series=[{"coin": "BTC", "ts": 1, "dispersion_bps_h": 1.0}])
    assert r["statut"] == "INSUFFISANT" and "cross_venue" == r["strategie"]


def test_chercher_toutes_ecrit_le_rapport_PEPITES_meme_sans_donnees(tmp_path):
    """4 modules balayes, verdicts honnetes (INSUFFISANT partout sur un dossier vide), et le
    rapport PEPITES.md existe avec l'avertissement anti-promesse."""
    from hl_observer.backtesting.recherche_scenario import chercher_toutes
    r = chercher_toutes(tmp_path, max_essais_par_strategie=2)
    assert set(r) == {"carry", "copy", "arbitrage", "cross_venue"}
    assert all(x["statut"] == "INSUFFISANT" for x in r.values())
    t = (tmp_path / "runtime" / "replay" / "PEPITES.md").read_text(encoding="utf-8")
    assert "PAS une promesse" in t and "cross_venue" in t


# ---------------- 21/07 : « ultra intelligent » — collection, filtres, raffinage ----------------

def test_mode_collection_balaie_TOUT_et_classe_les_pepites_par_net_sous_stress(tmp_path):
    """PLUSIEURS pepites : on ne s'arrete plus a la premiere. Le gagnant final = le plus
    robuste SOUS STRESS (pas le plus clinquant sur une moitie)."""
    nets = {40.0: (3.0, 2.5), 50.0: (6.0, 5.0),          # DEUX gagnants potentiels
            30.0: (2.0, 2.0), 45.0: (2.0, 1.5), 35.0: (1.0, 1.0),
            60.0: (2.0, 1.0), 55.0: (1.0, 1.0)}          # voisins vivants
    configs = [{"sl": 40.0, "tp": 70.0, "horizon_min": 60.0},
               {"sl": 50.0, "tp": 90.0, "horizon_min": 60.0}]
    r = chercher(tmp_path, configs=configs, donnees=DONNEES, evaluer_ab=_fake_ab(nets),
                 s_arreter_au_premier=False)
    assert r["statut"] == "PROMU" and len(r["promus"]) == 2
    assert r["gagnant"]["sl"] == 50.0, "sl=50 a le meilleur net sous stress (11-1 > 5.5-1)"


def test_filtrer_candidats_reduit_a_la_sous_population_mesuree():
    from hl_observer.backtesting.recherche_scenario import FILTRES_PRESETS, filtrer_candidats
    cands = [{"signal_age_ms": 5000, "consensus_wallets": 4, "liquidity_score": 0.7},
             {"signal_age_ms": 60000, "consensus_wallets": 4, "liquidity_score": 0.7},
             {"consensus_wallets": 1}]
    assert len(filtrer_candidats(cands, FILTRES_PRESETS["frais"])) == 1
    assert len(filtrer_candidats(cands, FILTRES_PRESETS["consensus"])) == 2
    assert len(filtrer_candidats(cands, FILTRES_PRESETS["frais_liquide"])) == 1
    assert len(filtrer_candidats(cands, {})) == 3
    # champ absent = exclu du sous-echantillon (deny-by-default), jamais suppose conforme
    assert filtrer_candidats([{}], FILTRES_PRESETS["frais"]) == []


def test_la_grille_large_croise_les_presets_de_filtres():
    from hl_observer.backtesting.recherche_scenario import FILTRES_PRESETS, grille_large
    configs = list(grille_large())
    assert len(configs) > 400
    assert {c["filtre"] for c in configs} == set(FILTRES_PRESETS)
    assert all(c["tp"] > c["sl"] for c in configs)


def test_le_raffinage_resserre_autour_des_graines_et_regate_tout(tmp_path):
    """Grossier -> fin : les promus ET les meilleurs presque-promus recoivent des voisins a
    pas/2, juges par LES MEMES portes (dedup par cle : rien n'est calcule deux fois)."""
    nets = {40.0: (3.0, 2.5), 30.0: (2.0, 2.0), 45.0: (2.0, 1.5), 35.0: (2.0, 1.5),
            50.0: (1.0, 1.0)}
    r = chercher(tmp_path, configs=[{"sl": 40.0, "tp": 70.0, "horizon_min": 60.0}],
                 donnees=DONNEES, evaluer_ab=_fake_ab(nets),
                 s_arreter_au_premier=False, raffiner=True)
    assert r["statut"] == "PROMU"
    assert len(r["essais"]) > 1, "le raffinage a bien juge des configs supplementaires"


# ---------------- 21/07 soir : les canons integres (CPCV + successive halving + rapport) ----------------

def test_folds_purges_decoupent_en_epoques_disjointes_avec_embargo():
    from hl_observer.backtesting.recherche_scenario import folds_purges
    d = DonneesReplay(candidats=[_cand(t) for t in range(0, 40000, 1000)], marks=[])
    folds = folds_purges(d, horizon_min=10.0, k=4)
    assert len(folds) == 4 and all(f for f in folds)
    fins = [max(c["recorded_at"] for c in f) for f in folds]
    debuts = [min(c["recorded_at"] for c in f) for f in folds]
    for i in range(3):
        assert debuts[i + 1] - fins[i] >= 600.0, "embargo d'un horizon ENTRE les folds"


def test_le_crible_multi_fidelite_epargne_les_perdants_evidents_jamais_n_admet():
    """Successive halving : net<=0 sur le quart recent -> pas d'evaluation complete. Un crible
    n'ADMET jamais (la porte reste juge) : il epargne du calcul."""
    from hl_observer.backtesting.recherche_scenario import _cribler_configs
    d = DonneesReplay(candidats=[_cand(t) for t in range(0, 30000)], marks=[])
    def eval_crible(cands, marks, *, base_config, horizon_min, cost_bps):
        return {"arm_a": {"net_total_usd": 1.0 if base_config.stop_loss_bps == 40.0 else -1.0}}
    configs = [{"sl": 40.0, "tp": 70.0, "horizon_min": 60.0},
               {"sl": 90.0, "tp": 150.0, "horizon_min": 60.0}]
    retenues = _cribler_configs(d, configs, evaluer_ab=eval_crible)
    assert [c["sl"] for c in retenues] == [40.0]


def test_rang_OR_exige_3_folds_vivants_sur_4(tmp_path):
    from hl_observer.backtesting.recherche_scenario import rang_pepite
    d = DonneesReplay(candidats=[_cand(t) for t in range(0, 40000, 1000)], marks=[])
    def ab(cands, marks, *, base_config, horizon_min, cost_bps):
        # le fold se reconnait a son premier candidat : 3 premiers folds gagnent, le 4e perd
        t0 = min(c["recorded_at"] for c in cands) if cands else 0
        return {"arm_a": {"net_total_usd": 1.0 if t0 < 30000 else -0.5}}
    r = rang_pepite(d, {"sl": 40.0, "tp": 70.0, "horizon_min": 10.0}, evaluer_ab=ab)
    assert r["rang"] == "OR" and r["folds_vivants"] == "3/4"


def test_le_rapport_RESULTATS_est_ecrit_avec_le_bloc_JSON_machine_lisible(tmp_path):
    from hl_observer.backtesting.recherche_scenario import chercher_toutes
    chercher_toutes(tmp_path, max_essais_par_strategie=2)
    t = (tmp_path / "runtime" / "replay" / "RESULTATS_RECHERCHE.md").read_text(encoding="utf-8")
    assert "JSON_RESULTATS" in t and "AUCUNE promesse" in t
    assert "cross_venue" in t and "Module `carry`" in t


# ---------------- 21/07 : la RECOMMANDATION en francais, derivee des resultats ----------------

def test_la_recommandation_dit_quoi_faire_dans_les_quatre_cas():
    from hl_observer.backtesting.recherche_scenario import recommandation
    # 1. pepite OR -> cable-la en paper
    r_or = {"promus": [{"config": {"sl": 40}, "rang": "OR",
                        "nets": {"stress": 2.0}, "folds_vivants": "3/4"}]}
    assert "FAIS ÇA" in recommandation("carry", r_or) and "paper" in recommandation("carry", r_or)
    # 2. donnees insuffisantes -> patience
    assert "PATIENCE" in recommandation("arbitrage", {"statut": "INSUFFISANT", "motif": "0 candidat"})
    # 3. tout negatif -> arreter de chercher ICI (le verrou est la bonne decision)
    r_neg = {"statut": "ESPACE_EPUISE", "essais": [
        {"verdict": "REJETE", "nets": {"moitie_1": -132.4, "moitie_2": -191.4}}]}
    assert "ARRÊTE DE CHERCHER ICI" in recommandation("copy", r_neg)
    # 4. des configs frolent les portes -> presque
    r_presque = {"statut": "ESPACE_EPUISE", "essais": [
        {"verdict": "REJETE", "nets": {"moitie_1": 2.0, "moitie_2": -0.1}}]}
    assert "PRESQUE" in recommandation("carry", r_presque)


def test_le_rapport_contient_les_recommandations_et_la_synthese_par_module(tmp_path):
    from hl_observer.backtesting.recherche_scenario import chercher_toutes
    chercher_toutes(tmp_path, max_essais_par_strategie=1)
    t = (tmp_path / "runtime" / "replay" / "RESULTATS_RECHERCHE.md").read_text(encoding="utf-8")
    assert "RECOMMANDATION" in t and "En une phrase par module" in t
