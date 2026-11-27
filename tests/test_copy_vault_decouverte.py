"""Moteur de decouverte CopyVault et champion/challenger PAPER (27/11/2026) : causalite, garde-fous, verite connue."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_champion_challenger as CC  # noqa: E402
from hl_observer.backtesting import copy_vault_decouverte as D  # noqa: E402
from hl_observer.backtesting import copy_vault_decouverte_banc as B  # noqa: E402
from hl_observer.backtesting.copy_vault_copiability_entrees import build_candle_panel  # noqa: E402

H, J = D.HEURE_MS, D.JOUR_MS
CAL = {"par_horizon": {str(h): {"sd_jour": 40.0, "sd_jour_unite": 40.0, "sd_decision": 120.0}
                       for h in D.DecouverteConfig().horizons_h}}
T0 = 20_000 * J


def _episode(i, vault="0xA", coin="BTC", action="OPEN", ts=T0, signe=1, usd=5_000.0):
    return {"fill_id": f"f{i}", "vault": vault, "coin": coin, "action": action, "ts_ms": ts, "fill_sign": signe,
            "taille_usd": usd}


def test_decisions_regroupe_dedoublonne_et_date_le_suivi():
    eps = [_episode(1), _episode(1), _episode(2, ts=T0 + 60_000), _episode(3, ts=T0 + 600_000),
           _episode(4, action="ADD", ts=T0 + 30_000), _episode(5, usd=10.0, ts=T0 + 5 * H),
           {"fill_id": "x", "action": "OPEN"}]
    dec, rejets = D.decisions_depuis_episodes(eps, entree_suivi_ms={"0xa": T0 + J})
    assert rejets["doublon"] == 1 and rejets["illisible"] == 1 and rejets["decision_sous_le_seuil"] == 1
    assert len(dec) == 3                                            # 1+2 regroupes ; 3 (10 min plus tard) ; ADD a part
    premiere = dec[(dec["action"] == "OPEN") & (dec["t0"] == T0)].iloc[0]
    assert premiere["n_fills"] == 2 and premiere["notional"] == 10_000.0
    assert (dec["entree_suivi"] == T0 + J).all() and (dec["unit"] == "0xa").all()


def _panel(prix_par_heure: dict[str, list[float]], debut=T0):
    bougies = [(coin, debut + k * H, px) for coin, serie in prix_par_heure.items() for k, px in enumerate(serie)]
    return build_candle_panel(bougies, interval_ms=H)


def test_enrichir_entre_apres_l_observation_et_paie_le_funding():
    prix = [100.0] * 30 + [110.0] * 60                                 # saut a la cloture de la 30e bougie
    panel = _panel({"BTC": prix})
    dec = pd.DataFrame({"unit": ["u"], "coin": ["BTC"], "signe": [1], "action": ["OPEN"],
                        "t0": [T0 + 30 * H - 30_000], "notional": [5e3], "n_fills": [1], "entree_suivi": [-1]})
    funding = {("BTC", int((T0 + 31 * H) // H) + k): 1e-4 for k in range(-2, 30)}
    out, _ = D.enrichir(dec, panel, bar_ms=H, funding=funding, demi_ecarts={"BTC": 1.0},
                        config=D.DecouverteConfig(horizons_h=(4,)))
    r = out.iloc[0]
    assert r["entree"] == T0 + 31 * H                                  # jamais avant t0 + 60 s + 60 s, arrondi a la bougie
    assert r["brut_4h"] == pytest.approx(0.0)                          # le saut etait deja publie : pas de faux gain
    cout = 2 * (D.DecouverteConfig().taker_bps + 1.0 + 1.0)
    assert r["net_suivre_4h"] == pytest.approx(-cout - 4 * 1e-4 * 1e4)  # long, funding positif : il paie 4 heures
    assert r["net_contrer_4h"] == pytest.approx(-cout + 4 * 1e-4 * 1e4)
    assert r["funding"] == "paie" and r["tendance"] == "avec"


def _table_brute(rows):
    df = pd.DataFrame(rows, columns=["unit", "coin", "signe", "t0", "notional"])
    df["entree"] = df["t0"]
    df["net_suivre_4h"] = 1.0
    return df


def test_consensus_opposition_et_historique_ne_lisent_que_le_passe():
    cfg = D.DecouverteConfig(horizons_h=(4,), historique_min=1, historique_a_priori=0.0, taille_min_historique=2)
    rows = [("a", "BTC", 1, T0, 1e3), ("b", "BTC", 1, T0 + H, 1e3), ("a", "BTC", 1, T0 + 2 * H, 1e3),
            ("c", "BTC", -1, T0 + 3 * H, 1e3), ("b", "BTC", 1, T0 + 9 * H, 9e3), ("a", "BTC", 1, T0 + 20 * H, 1e3)]
    df = _table_brute(rows)
    D._predicats_causaux(df, cfg)
    assert df["consensus"].tolist()[:2] == ["seul", "accompagne"]      # b voit a ; a ne voit pas b (posterieur)
    assert df.loc[2, "consensus"] == "accompagne"                      # a voit b, pas lui-meme
    assert df.loc[3, "opposition"] == "oui" and df.loc[3, "consensus"] == "seul"
    assert df.loc[4, "consensus"] == "seul"                            # la fenetre de 4 h a oublie les autres
    assert df.loc[0, "historique_4h"] == "inconnu"
    assert df.loc[2, "historique_4h"] == "inconnu"                     # la 1re decision de a n'est pas encore denouee
    assert df.loc[5, "historique_4h"] == "gagnant"                     # denouees : comptees
    assert df.loc[4, "taille"] == "inconnue" and df.loc[5, "taille"] == "normale"


def test_populations_exploration_validation_exclue():
    df = pd.DataFrame({"t0": [T0, T0 + 10 * J, T0 + 20 * J, T0 + 21 * J], "entree": [T0, T0 + 10 * J, T0 + 20 * J, T0 + 21 * J],
                       "entree_suivi": [T0 + 10 * J, T0 + 10 * J, T0 + 30 * J, T0 + 10 * J],
                       "mouvement_24h_bps": [10.0, -50.0, 5.0, np.nan]})
    out = D.attribuer_populations(df, coupure_ms=None, config=D.DecouverteConfig())
    assert out["population"].tolist() == ["exploration", "exclue", "exclue", "validation"]
    assert out["volatilite"].tolist()[3] == "inconnue"
    sans_dates = D.attribuer_populations(df.assign(entree_suivi=-1), coupure_ms=None)
    assert set(sans_dates["population"]) == {"exploration"}            # aucune validation fabriquee


def _table(seed=0, n_units=8, n_jours=80, par_jour=6, plantee=None, delta=0.0):
    rng = np.random.default_rng(seed)
    n = n_units * n_jours * par_jour
    jour = np.repeat(np.arange(n_jours), n_units * par_jour) + 20_000
    df = pd.DataFrame({"unit": np.tile(np.repeat([f"u{i}" for i in range(n_units)], par_jour), n_jours),
                       "coin": rng.choice(["BTC", "ETH", "SOL"], n), "signe": rng.choice([1, -1], n),
                       "t0": jour * J + rng.integers(0, J // 2, n)})
    df["entree"] = df["t0"] + H
    df["jour"] = df["entree"] // J
    df["notional"] = 5e3
    df["cout_bps"] = 12.0
    df["entree_suivi"] = (20_000 + 55) * J
    df["mouvement_24h_bps"] = rng.normal(0, 100, n)
    for dim, (valeurs, _) in D.DIMENSIONS.items():
        if dim != "historique":
            df[dim] = rng.choice(valeurs, n)
    for h in D.DecouverteConfig().horizons_h:
        df[f"historique_{h}h"] = rng.choice(["gagnant", "perdant"], n)
    out = D.attribuer_populations(df, coupure_ms=None)
    for dim in ("volatilite",):
        out[dim] = df[dim]
    return B.monde_synthetique(out, D.DecouverteConfig(), graine=seed, calibrage=CAL, plantee=plantee, delta_bps=delta)


def test_generer_cellules_deterministe_et_dans_la_grammaire():
    m, cfg = D.Methode(), D.DecouverteConfig()
    a, b = D.generer_cellules(m, cfg, graine=3), D.generer_cellules(m, cfg, graine=3)
    assert [c["id"] for c in a] == [c["id"] for c in b]
    assert all(len({p[0] for p in c["predicats"]}) == len(c["predicats"]) for c in a)
    un = D.generer_cellules(D.Methode(profondeur=1), cfg)
    assert len(un) == 2 * len(cfg.horizons_h) * (1 + len(D.predicats_disponibles())) and len(a) > len(un)


def test_une_methode_qui_affaiblit_un_garde_fou_est_refusee():
    assert not D.Methode(dsr_seuil=0.9).respecte_les_garde_fous()
    assert all(v.respecte_les_garde_fous() for v in B.voisines(D.Methode()))
    with pytest.raises(ValueError):
        D.juger_campagne(_table(), [], D.Methode(pbo_max=0.8))


def test_un_avantage_plante_est_gele_et_un_monde_nul_ne_gele_rien():
    plantee = D._cellule("suivre", 4, (("consensus", "accompagne"),))
    table = _table(seed=1, plantee=plantee, delta=150.0)
    cfg, m = D.DecouverteConfig(), D.Methode()
    cellules = D.generer_cellules(m, cfg)
    r = D.juger_campagne(table, cellules, m, cfg)
    assert plantee["id"] in {g["id"] for g in r["geles"]}
    assert D.verdict_campagne(r)["status"] == "MORE_DATA"              # une campagne ne prouve jamais rien
    nul = D.juger_campagne(_table(seed=2), cellules, m, cfg)
    assert nul["geles"] == []
    # plus d'essais anterieurs = DSR plus severe pour la meme cellule
    plus = D.juger_campagne(table, cellules, m, cfg, essais_anterieurs=100_000)
    d1 = next(x["dsr"] for x in r["resultats"] if x["id"] == plantee["id"])
    d2 = next(x["dsr"] for x in plus["resultats"] if x["id"] == plantee["id"])
    assert d2 < d1


def test_memoire_retient_ce_qui_aide_et_oriente_les_croisements():
    plantee = D._cellule("suivre", 4, (("taille", "grosse"),))
    r = D.juger_campagne(_table(seed=4, plantee=plantee, delta=150.0), D.generer_cellules(D.Methode(profondeur=1),
                         D.DecouverteConfig()), D.Methode(profondeur=1))
    memo = D.mettre_a_jour_memoire(None, r, campagne="c1")
    assert memo["predicats"]["suivre|taille=grosse"]["aide"] >= 1
    assert D.choisir_croisements(memo, "suivre", 3, 5) == D.choisir_croisements(memo, "suivre", 3, 5)
    assert len(memo["campagnes"]) == 1 and plantee["id"] in memo["cellules"]


def test_banc_a_verite_connue_et_amelioration_sans_affaiblissement():
    table = _table(seed=5)
    cfg = D.DecouverteConfig(tirages=200)
    plantees = B.tirer_plantees(B.cellules_reference(table, cfg), [1, 2, 3])
    e = B.evaluer_methode(table, D.Methode(), cfg, graines=[1, 2, 3], plantees=plantees, calibrage=CAL,
                          delta_bps=300.0)
    assert e["rappel"] >= 2 / 3 and e["mondes_nuls_avec_faux"] <= 1 / 3
    dec = B.ameliorer_methode(table, D.Methode(profondeur=1), cfg, version_banc=1, mondes=2, calibrage=CAL)
    # toutes les methodes affrontent les MEMES mondes : une seule liste de cellules plantees, tiree d'une reference fixe
    assert len(dec["cellules_plantees"]) == 2
    assert all(len(v["banc"]["touches_par_monde"]) == 2 * 2 for v in dec["variantes"])     # 2 mondes x 2 tailles
    assert dec["decision"] in {"CONSERVEE", "ADOPTEE", "RETOUR_ARRIERE", "AUCUNE_VARIANTE_SURE",
                               "CONSERVEE_GAIN_NON_SIGNIFICATIF"}
    assert D.Methode(**dec["methode_retenue"]).respecte_les_garde_fous()


def test_benjamini_hochberg():
    assert D.benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.5}, 0.10) == {"a", "b", "c"}
    assert D.benjamini_hochberg({"a": 0.2, "b": 0.3}, 0.10) == set()


# --------------------------------------------------------------------------- champion / challenger

def _suivi(gel_jour, n_jours, moyenne, seed=0, cellule=None):
    rng = np.random.default_rng(seed)
    lignes = []
    for d in range(n_jours):
        for u in range(4):
            t0 = (gel_jour + 1 + d) * J + 1000 * u
            lignes.append({"unit": f"u{u}", "coin": "BTC", "signe": 1, "t0": t0, "entree": t0 + H,
                           "jour": (t0 + H) // J, "entree_suivi": 1, "consensus": "accompagne",
                           "net_suivre_4h": moyenne + rng.normal(0, 5)})
    return pd.DataFrame(lignes)


def _gele(id_="c1", predicats=(("consensus", "accompagne"),)):
    return {"id": id_, "direction": "suivre", "horizon_h": 4, "predicats": predicats,
            "exploration": {"moyenne_bps": 20.0, "ecart_bps": 5.0}, "dsr": 0.97}


def test_gel_garde_sa_date_et_suivi_apres_gel_seulement():
    etat = CC.enregistrer_geles(CC.etat_initial(), [_gele()], gel_ms=100 * J, campagne="c1", methode_version=1)
    etat = CC.enregistrer_geles(etat, [_gele()], gel_ms=200 * J, campagne="c2", methode_version=1)
    assert etat["challengers"]["c1"]["gel_ms"] == 100 * J
    table = pd.concat([_suivi(90, 5, 50.0), _suivi(100, 3, 20.0)])
    jours, x = CC.serie_de_suivi(table, etat["challengers"]["c1"], now_ms=200 * J)
    assert len(jours) == 3 and abs(x.mean() - 20.0) < 5                 # les jours d'avant le gel ne comptent pas


def test_promotion_puis_invalidation_et_retour_arriere():
    etat = CC.enregistrer_geles(CC.etat_initial(), [_gele()], gel_ms=100 * J, campagne="c1", methode_version=1)
    etat, ev = CC.evaluer(etat, _suivi(100, 35, 20.0), now_ms=200 * J)
    assert etat["champion"] == "c1" and ev[-1]["evenement"] == "PROMOTION"
    assert etat["recommandation_paper"]["applique_au_moteur"] is False
    perdant = pd.concat([_suivi(100, 35, 20.0), _suivi(135, 20, -30.0, seed=1)])
    etat, ev = CC.evaluer(etat, perdant, now_ms=300 * J)
    assert etat["challengers"]["c1"]["etat"] == "INVALIDE"
    assert etat["champion"] == CC.AUCUN_TRADE and any(e["evenement"] == "RETOUR_ARRIERE" for e in ev)


def test_un_challenger_qui_perd_est_invalide_sans_jamais_etre_promu():
    etat = CC.enregistrer_geles(CC.etat_initial(), [_gele()], gel_ms=100 * J, campagne="c1", methode_version=1)
    etat, _ = CC.evaluer(etat, _suivi(100, 12, -25.0), now_ms=200 * J)
    assert etat["challengers"]["c1"]["etat"] == "INVALIDE" and etat["champion"] == CC.AUCUN_TRADE


def test_page_hinkley_detecte_un_decrochage():
    assert not CC.page_hinkley([20.0] * 30, reference=20.0, ecart=5.0)["alarme"]
    assert CC.page_hinkley([20.0] * 10 + [0.0] * 10, reference=20.0, ecart=5.0)["alarme"]


def test_un_progres_de_methode_doit_etre_significatif_sur_les_memes_mondes():
    assert B.p_apparie([True] * 6 + [False] * 2, [False] * 8) == pytest.approx(1 / 64)
    assert B.p_apparie([True, False] * 4, [False, True] * 4) == pytest.approx(0.6367, abs=1e-3)   # 4 contre 4 : rien
    assert B.p_apparie([False] * 5, [False] * 5) == 1.0


def test_puissance_dit_ce_que_le_labo_sait_voir():
    table = _table(seed=6)
    p = B.puissance(table, D.Methode(profondeur=1), D.DecouverteConfig(), graines=[1, 2], deltas=(20.0, 400.0),
                    calibrage=CAL)
    assert p["courbe"]["400"]["rappel"] >= p["courbe"]["20"]["rappel"]
    assert p["effet_minimal_detectable_bps"] in (None, 20.0, 400.0)


# --------------------------------------------------------------------------- juge v2 (relecture du 27/11)

def test_une_copie_deja_tenue_n_est_pas_comptee_deux_fois():
    panel = _panel({"BTC": [100.0 + k for k in range(80)]})
    dec = pd.DataFrame({"unit": ["u", "u", "u"], "coin": ["BTC"] * 3, "signe": [1, 1, 1], "action": ["OPEN", "ADD", "OPEN"],
                        "t0": [T0 + 2 * H, T0 + 3 * H, T0 + 9 * H], "notional": [5e3] * 3, "n_fills": [1] * 3,
                        "entree_suivi": [-1] * 3})
    funding = {("BTC", T0 // H + k): 1e-5 for k in range(80)}           # funding connu : sinon net inconnu (voulu)
    out, rejets = D.enrichir(dec, panel, bar_ms=H, funding=funding, demi_ecarts={"BTC": 1.0},
                             config=D.DecouverteConfig(horizons_h=(4,)))
    nets = out["net_suivre_4h"].tolist()
    assert np.isnan(nets[1]) and not np.isnan(nets[0]) and not np.isnan(nets[2])      # la 2e arrive copie tenue
    assert rejets["chevauchement_4h"] == 1


def test_pbo_par_direction_et_horizon():
    r = D.juger_campagne(_table(seed=7), D.generer_cellules(D.Methode(profondeur=1), D.DecouverteConfig()),
                         D.Methode(profondeur=1), D.DecouverteConfig())
    assert set(r["pbo_par_groupe"]) == {f"{d}_{h}h" for d in D.DIRECTIONS for h in D.DecouverteConfig().horizons_h}
    assert r["juge_version"] == D.JUGE_VERSION and r["jours_selection"] > r["jours_exploration"]


def test_jamais_refutee_sur_des_couts_supposes():
    table = _table(seed=8)
    for h in D.DecouverteConfig().horizons_h:
        table[f"net_suivre_{h}h"] = table[f"net_suivre_{h}h"] - 300.0       # nettement perdant partout
    cellules = D.generer_cellules(D.Methode(profondeur=1), D.DecouverteConfig())
    suppose = D.juger_campagne(table, cellules, D.Methode(profondeur=1), D.DecouverteConfig())
    assert not any(r["statut"] == "REFUTEE" for r in suppose["resultats"])
    mesure = D.juger_campagne(table.assign(ecart_mesure=True), cellules, D.Methode(profondeur=1), D.DecouverteConfig())
    assert any(r["statut"] == "REFUTEE" and r["direction"] == "suivre" for r in mesure["resultats"])


def test_memes_donnees_la_memoire_ne_recompte_rien():
    r = D.juger_campagne(_table(seed=9), D.generer_cellules(D.Methode(profondeur=1), D.DecouverteConfig()),
                         D.Methode(profondeur=1))
    m1 = D.mettre_a_jour_memoire(None, r, campagne="c1", cle_donnees="k")
    m2 = D.mettre_a_jour_memoire(m1, r, campagne="c2", cle_donnees="k")
    assert m2 == m1
    m3 = D.mettre_a_jour_memoire(m1, r, campagne="c3", cle_donnees="k2")
    assert len(m3["campagnes"]) == 2


def test_le_calibrage_reproduit_l_ecart_type_journalier_reel():
    table = _table(seed=10)
    cfg = D.DecouverteConfig()
    cal = B.calibrer_banc(table, cfg)
    verif = B.verifier_calibrage(table, cfg, cal)
    for h in [str(x) for x in D.DecouverteConfig().horizons_h]:
        assert 0.75 <= verif[h]["synthetique"] / verif[h]["reel"] <= 1.25          # recale sur le reel


def test_les_recus_du_depot_sont_emis():
    etat = CC.enregistrer_geles(CC.etat_initial(), [_gele()], gel_ms=100 * J, campagne="c1", methode_version=1)
    etat, _ = CC.evaluer(etat, _suivi(100, 12, 20.0), now_ms=200 * J)
    recus = etat["challengers"]["c1"]["recus"]
    assert recus["forward_freeze"]["verdict"] == "FORWARD_AFTER_FREEZE"
    assert recus["champion_drift"]["verdict"] in ("STABLE", "DEGRADED")


# --------------------------------------------------------------------------- juge v3 : reperage puis confirmation

def test_la_surveillance_repere_mais_ne_promeut_jamais_sans_suivi():
    cfg = D.DecouverteConfig()
    r = D.juger_campagne(_table(seed=2), D.generer_cellules(D.Methode(), cfg), D.Methode(), cfg)
    assert r["geles"] == [] and 0 < len(r["surveillance"]) <= cfg.max_surveillance     # monde nul : reperees au hasard
    assert all(x["statut"] == "SURVEILLANCE" and x["selection"]["moyenne_bps"] > 0 for x in r["surveillance"])
    assert D.verdict_campagne(r)["status"] == "MORE_DATA"
    # suivi d'esperance nulle : jamais promu
    etat = CC.enregistrer_geles(CC.etat_initial(), [_gele()], gel_ms=100 * J, campagne="c1", methode_version=1,
                                palier="SURVEILLANCE")
    etat, ev = CC.evaluer(etat, _suivi(100, 40, 0.0, seed=3), now_ms=300 * J)
    assert etat["champion"] == CC.AUCUN_TRADE and not any(e["evenement"] == "PROMOTION" for e in ev)
    assert etat["challengers"]["c1"]["palier"] == "SURVEILLANCE"



def test_essais_effectifs_li_ji():
    rng = np.random.default_rng(0)
    jours = np.arange(60)
    base = rng.normal(0, 1, 60)
    identiques = [(jours, base.copy()) for _ in range(10)]                # 10 copies d'une meme serie : 1 essai
    assert D.essais_effectifs_li_ji(identiques, jours) == pytest.approx(1.0, abs=1e-6)
    independantes = [(jours, rng.normal(0, 1, 60)) for _ in range(10)]    # independantes : pres de 10
    assert 7.0 <= D.essais_effectifs_li_ji(independantes, jours) <= 10.0
    r = D.juger_campagne(_table(seed=11), D.generer_cellules(D.Methode(profondeur=1), D.DecouverteConfig()),
                         D.Methode(profondeur=1, essais_effectifs=True), D.DecouverteConfig())
    assert r["essais_effectifs_li_ji"] is not None and r["n_essais_dsr"] <= r["n_cellules"]



def test_confirmation_d_une_seule_variante_annoncee():
    table = _table(seed=12)
    cfg = D.DecouverteConfig(tirages=200)
    var = [D.Methode(profondeur=1, essais_effectifs=True, version=2)]
    dec = B.ameliorer_methode(table, D.Methode(profondeur=1), cfg, version_banc=3, mondes=2, calibrage=CAL, variantes=var)
    assert len(dec["variantes"]) == 1 and dec["variantes"][0]["methode"]["essais_effectifs"] is True
    with pytest.raises(ValueError):
        B.ameliorer_methode(table, D.Methode(), cfg, version_banc=3, mondes=1, calibrage=CAL,
                            variantes=[D.Methode(dsr_seuil=0.5)])
