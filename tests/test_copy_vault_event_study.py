"""Étude d'événements des décisions agressives des leaders (décisions, pas fills ; entrée après observation)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from hl_observer.backtesting import copy_vault_event_study as E
from hl_observer.backtesting.copy_vault_copiability_entrees import PricePanel
from hl_observer.fees.hyperliquid_fees import TAKER_PERP_BPS

BAR = 300_000
HEURE = 3_600_000
JOUR = 86_400_000
T0 = 1_780_000_000_000 // JOUR * JOUR
COINS = ("BTC", "ETH", "SOL", "HYPE", "kPEPE", "xyz:XYZ100")
ECARTS = {c: 1.0 for c in COINS}
CONFIG = E.EventStudyConfig(bootstrap_samples=300)
COUT = 2 * (TAKER_PERP_BPS + 1.0)


def _fill(vault, coin, t, *, signe=1, taker=True, ouverture=True, notionnel=5_000.0, obs_s=30, post=True):
    return {"vault": vault, "coin": coin, "time": int(t), "obs": int(t + obs_s * 1000), "signe": signe,
            "crossed": 1.0 if taker else 0.0, "is_open": ouverture, "notional": notionnel, "post": post}


def _monde(jours=60, leaders=12, *, derive_bps=40.0, bruit_bps=0.0, seed=1, post=True):
    """Chaque leader ouvre agressivement une fois par jour (heure et coin au hasard) et passivement une fois.
    Après une ouverture agressive, le prix dérive de ``derive_bps`` dans son sens pendant 4 h."""
    rng = np.random.default_rng(seed)
    n = jours * JOUR // BAR + 1
    ts = T0 + np.arange(n, dtype=np.int64) * BAR
    logp = np.zeros((n, len(COINS)))
    if bruit_bps:
        logp += np.cumsum(rng.normal(0.0, bruit_bps / 1e4, logp.shape), axis=0)
    fills = []
    for jour in range(15, jours - 2):                       # les témoins à -7 et -14 jours existent
        for k in range(leaders):
            coin = int(rng.integers(len(COINS)))
            t = T0 + jour * JOUR + int(rng.integers(0, 19 * HEURE))
            signe = 1 if rng.random() < 0.5 else -1
            fills.append(_fill(f"0x{k:040x}", COINS[coin], t, signe=signe, post=post))
            entree = -(-(t + 30_000 + CONFIG.reaction_ms) // BAR) * BAR
            i0 = (entree - T0) // BAR
            i1 = i0 + 4 * HEURE // BAR
            rampe = np.clip((np.arange(n) - i0) / (i1 - i0), 0.0, 1.0)
            logp[:, coin] += signe * derive_bps / 1e4 * rampe
            passif = T0 + jour * JOUR + int(rng.integers(0, 19 * HEURE))
            fills.append(_fill(f"0x{k:040x}", COINS[int(rng.integers(len(COINS)))], passif, taker=False, post=post))
    panel = PricePanel(ts=ts, px=100.0 * np.exp(logp), coins=COINS, provenance="test", stale_ms=BAR + 60_000)
    return pd.DataFrame(fills), panel


def _etude(fills, panel, config=CONFIG, ecarts=ECARTS):
    return E.run_event_study(fills, {}, {"bougies_5m": (panel, BAR)}, ecarts, config)


def _cellule(etude, segment, periode=E.PERIODES[0], horizon=4):
    return next(c for c in etude["cells"] if c["segment"] == segment and c["periode"] == periode
                and c["horizon_h"] == horizon)


def test_une_derive_apres_les_ouvertures_agressives_est_detectee_et_pas_ailleurs():
    fills, panel = _monde()
    etude = _etude(fills, panel)
    primaire = etude["primary"]
    assert primaire["evenements"] >= 400 and primaire["leaders"] == 12 and primaire["jours"] >= 30
    assert primaire["brut"]["moyenne_bps"] == pytest.approx(40.0, abs=4.0)
    assert primaire["net"]["moyenne_bps"] == pytest.approx(40.0 - COUT, abs=4.0)        # coûts réellement retirés
    assert primaire["net"]["intervalle_bps"][0] > 0 and primaire["timing"]["intervalle_bps"][0] > 0
    assert etude["verdicts"][0]["status"] == "PROMISING" and etude["economically_proven"] is False
    passif = _cellule(etude, "MAKER_OPEN")
    assert abs(passif["brut"]["moyenne_bps"]) < 8.0 and passif["net"]["moyenne_bps"] < 0   # rien à copier là
    capital = etude["capital_350"]
    assert capital["status"] == "OK" and capital["taille_ligne_usd"] == 70.0 and capital["net_usd_par_jour"] > 0
    # l'espérance applique au débit du compte le net moyen de TOUTES les décisions, pas des seules retenues
    assert capital["esperance_usd_par_jour"] == pytest.approx(
        capital["trades_par_jour"] * 70.0 * capital["net_moyen_toutes_decisions_bps"] / 1e4)
    assert capital["net_moyen_toutes_decisions_bps"] == pytest.approx(40.0 - COUT, abs=4.0)
    assert capital["refus_sans_place"] > 0                     # 12 décisions par jour, 5 places : le capital borne


def test_du_bruit_pur_n_est_jamais_declare_prometteur():
    fills, panel = _monde(derive_bps=0.0, bruit_bps=6.0, seed=4)
    etude = _etude(fills, panel)
    assert etude["verdicts"][0]["status"] in {"REJECTED", "MORE_DATA"}
    assert etude["primary"]["net"]["moyenne_bps"] == pytest.approx(-COUT, abs=6.0)       # on paie les frais, rien d'autre


def test_une_tendance_du_coin_n_est_pas_une_competence_les_temoins_la_retirent():
    """Le leader achète un coin qui monte tout seul : brut positif, mais autant que 7 et 14 jours plus tôt."""
    n = 60 * JOUR // BAR + 1
    ts = T0 + np.arange(n, dtype=np.int64) * BAR
    px = 100.0 * np.exp(np.arange(n)[:, None] * 0.5 / 1e4 * np.ones((1, len(COINS))))     # +0,5 bps par bougie
    panel = PricePanel(ts=ts, px=px, coins=COINS, provenance="test", stale_ms=BAR + 60_000)
    fills = pd.DataFrame([_fill(f"0x{k:040x}", "BTC", T0 + j * JOUR + k * HEURE)
                          for j in range(15, 58) for k in range(12)])
    primaire = _etude(fills, panel)["primary"]
    assert primaire["brut"]["moyenne_bps"] == pytest.approx(24.0, abs=0.5)                # 48 bougies x 0,5 bps
    assert primaire["timing"]["moyenne_bps"] == pytest.approx(0.0, abs=0.5)
    assert primaire["timing"]["intervalle_bps"][0] <= 0
    assert _etude(fills, panel)["verdicts"][0]["status"] != "PROMISING"


def test_une_decision_n_est_pas_un_fill_et_des_clones_ne_comptent_qu_une_fois():
    t = T0 + 20 * JOUR
    fills = pd.DataFrame(
        [_fill("0xaaa", "BTC", t + k * 20_000, notionnel=400.0) for k in range(5)]        # 5 fills en 100 s
        + [_fill("0xbbb", "BTC", t + 10_000 + k * 20_000, notionnel=400.0) for k in range(5)]   # un clone
        + [_fill("0xaaa", "BTC", t + 2 * HEURE, notionnel=300.0)]                         # trop petit : pas une décision
        + [_fill("0xccc", "ETH", t, signe=-1, taker=True, ouverture=False)])
    seuls = E.build_events(fills, {}, CONFIG)
    assert sorted(seuls["segment"]) == ["TAKER_CLOSE", "TAKER_OPEN", "TAKER_OPEN"]
    assert set(seuls.loc[seuls["segment"] == "TAKER_OPEN", "n_fills"]) == {5}
    groupes = E.build_events(fills, {"0xaaa": "0xaaa", "0xbbb": "0xaaa"}, CONFIG)
    ouvertures = groupes[groupes["segment"] == "TAKER_OPEN"]
    assert len(ouvertures) == 1 and int(ouvertures["n_fills"].iloc[0]) == 10              # un opérateur, une décision
    assert ouvertures["notional"].iloc[0] == pytest.approx(4_000.0)
    assert int(ouvertures["obs"].iloc[0]) == t + 30_000                                   # observable dès le 1er fill


def test_pas_de_nouvelle_entree_tant_que_la_position_est_tenue():
    fills, panel = _monde(jours=40, leaders=1, seed=2)
    t = int(fills["time"].iloc[0])
    coin, signe = fills["coin"].iloc[0], int(fills["signe"].iloc[0])
    doubles = pd.concat([fills, pd.DataFrame([_fill("0x" + "0" * 40, coin, t + HEURE, signe=signe),
                                              _fill("0x" + "0" * 40, coin, t + 2 * HEURE, signe=signe)])])
    table, rejets = E.event_returns(E.build_events(doubles, {}, CONFIG), panel, ECARTS, horizon_h=4, bar_ms=BAR,
                                    config=CONFIG)
    reference, _ = E.event_returns(E.build_events(fills, {}, CONFIG), panel, ECARTS, horizon_h=4, bar_ms=BAR,
                                   config=CONFIG)
    assert rejets["position_deja_tenue"] >= 2 and len(table) == len(reference)


def test_l_entree_ne_precede_jamais_l_observation():
    """Métamorphique : les prix publiés avant la bougie d'entrée ne changent rien ; observer plus tard retarde."""
    fills, panel = _monde(jours=40, leaders=3, seed=3)
    evenements = E.build_events(fills, {}, CONFIG)
    table, _ = E.event_returns(evenements, panel, ECARTS, horizon_h=4, bar_ms=BAR, config=CONFIG)
    assert (table["entree"] >= table["obs"] + CONFIG.reaction_ms).all()
    assert (table["entree"] - table["obs"] - CONFIG.reaction_ms < BAR).all() and (table["entree"] % BAR == 0).all()
    # trucage de la bougie qui PRÉCÈDE l'entrée du premier événement : son rendement ne bouge pas
    cible = table.iloc[0]
    index = int((cible["entree"] - T0) // BAR) - 1
    truque = panel.px.copy()
    truque[index, COINS.index(cible["coin"])] *= 1.5
    autre = PricePanel(ts=panel.ts, px=truque, coins=COINS, provenance="test", stale_ms=panel.stale_ms)
    apres, _ = E.event_returns(evenements, autre, ECARTS, horizon_h=4, bar_ms=BAR, config=CONFIG)
    memes = apres[(apres["unit"] == cible["unit"]) & (apres["entree"] == cible["entree"])]
    assert float(memes["brut_bps"].iloc[0]) == pytest.approx(float(cible["brut_bps"]))
    # observé 20 minutes plus tard : on entre plus tard et on capte moins de la dérive
    lents = fills.assign(obs=fills["obs"] + 20 * 60_000)
    tard = _etude(lents, panel)["primary"]["brut"]["moyenne_bps"]
    assert tard < _etude(fills, panel)["primary"]["brut"]["moyenne_bps"] - 1.0


def test_les_decisions_reconstruites_sont_rapportees_mais_ne_decident_pas():
    fills, panel = _monde(post=False)
    etude = _etude(fills, panel)
    assert etude["primary"]["evenements"] == 0 and etude["verdicts"][0]["status"] == "MORE_DATA"
    avant = _cellule(etude, "TAKER_OPEN", E.PERIODES[1])
    assert avant["evenements"] >= 400 and avant["net"]["moyenne_bps"] > 20          # mesuré, affiché, non retenu
    assert etude["inputs"]["decisions_observees_en_direct"] == 0


def test_observe_en_direct_ou_reconstruit_la_frontiere_est_le_delai_reel_d_observation():
    t = T0 + 20 * JOUR
    colonnes = dict(px=100.0, sz=50.0, tid=1, oid=1)
    observes = pd.DataFrame([
        {**_fill("0xa", "BTC", t, obs_s=20), **colonnes, "tid": 1},                  # vu en 20 s : en direct
        {**_fill("0xa", "BTC", t + 60_000, obs_s=3 * 86_400), **colonnes, "tid": 2},  # relevé 3 jours plus tard
        {**_fill("0xa", "ETH", t, obs_s=10), **colonnes, "tid": 3},                  # aussi présent au backfill
    ]).drop(columns="post")
    reconstruits = pd.DataFrame([
        {**_fill("0xa", "ETH", t, obs_s=120), **colonnes, "tid": 3},
        {**_fill("0xb", "SOL", t, obs_s=120), **colonnes, "tid": 4},
    ]).drop(columns="post")
    reunis = E.assembler_fills(observes, reconstruits, assumed_lag_ms=120_000)
    assert len(reunis) == 4                                                          # le doublon n'entre qu'une fois
    etat = {int(r.tid): (bool(r.post), int(r.obs - r.time)) for r in reunis.itertuples()}
    assert etat == {1: (True, 20_000),          # délai réel conservé
                    2: (False, 120_000),        # relevé tardif : reconstruit, instant d'observation SUPPOSÉ
                    3: (True, 10_000),          # la version observée en direct l'emporte sur le backfill
                    4: (False, 120_000)}
    assert E.MAX_DELAI_OBSERVATION_DIRECTE_MS == 300_000
    assert len(E.assembler_fills(observes.iloc[:0], reconstruits.iloc[:0], assumed_lag_ms=1)) == 0


def test_ni_rejet_ni_promotion_sur_quelques_jours_meme_avec_un_intervalle_etroit():
    """Cas réel du 2026-11-11 : 4 jours, intervalle net entièrement négatif -> ce n'est PAS un rejet."""
    def primaire(jours, intervalle):
        return {"evenements": 1452, "leaders": 54, "net": {"jours": jours, "moyenne_bps": sum(intervalle) / 2,
                                                           "intervalle_bps": intervalle},
                "timing": {"intervalle_bps": intervalle}}
    assert E.verdict_ouvertures(primaire(4, (-33.6, -27.2)))["status"] == "MORE_DATA"
    assert E.verdict_ouvertures(primaire(4, (5.0, 30.0)))["status"] == "MORE_DATA"
    assert E.verdict_ouvertures(primaire(40, (-33.6, -27.2)))["status"] == "REJECTED"
    assert E.verdict_ouvertures(primaire(40, (5.0, 30.0)))["status"] == "PROMISING"
    assert E.verdict_ouvertures(primaire(40, (-5.0, 30.0)))["status"] == "MORE_DATA"


def test_ecart_inconnu_net_inconnu_et_le_compte_de_350_usd_ne_trade_pas():
    fills, panel = _monde(jours=40, leaders=4, seed=5)
    etude = _etude(fills, panel, ecarts={})
    assert etude["primary"]["net"]["moyenne_bps"] is None and etude["primary"]["brut"]["moyenne_bps"] > 0
    assert etude["capital_350"]["status"] == "UNMEASURABLE"
    assert etude["verdicts"][0]["status"] == "MORE_DATA"
    # coin sans prix : compté, jamais valorisé
    inconnu = pd.concat([fills, pd.DataFrame([_fill("0xzzz", "ABSENT", T0 + 20 * JOUR)])])
    assert _etude(inconnu, panel)["inputs"]["rejets_primaire"]["coin_sans_prix"] == 1


def test_le_compte_borne_par_ses_places_et_l_ordre_des_lignes_ne_change_rien():
    fills, panel = _monde(jours=45, leaders=12, seed=6)
    table, _ = E.event_returns(E.build_events(fills, {}, CONFIG), panel, ECARTS, horizon_h=4, bar_ms=BAR, config=CONFIG)
    table = table[table["segment"] == "TAKER_OPEN"]
    a = E.simulate_capital(table, horizon_h=4, config=CONFIG)
    b = E.simulate_capital(table.sample(frac=1.0, random_state=7), horizon_h=4, config=CONFIG)
    assert a == b and a["trades"] + a["refus_sans_place"] == len(table)
    large = E.simulate_capital(table, horizon_h=4, config=replace(CONFIG, slots=35))      # 10 USD : encore permis
    assert large["status"] == "OK" and large["trades"] > a["trades"]
    trop = E.simulate_capital(table, horizon_h=4, config=replace(CONFIG, slots=36))       # 9,72 USD : refusé
    assert trop["status"] == "UNMEASURABLE"
    assert E.run_event_study(fills.iloc[:0], {}, {"p": (panel, BAR)}, ECARTS, CONFIG)["primary"]["evenements"] == 0


# ------------------------------------------------------------------ sélection des leaders en marche avant

def _monde_deux_sortes(jours=70, seed=8, *, bons=6, mauvais=6):
    """La moitié des leaders ouvre AVANT une hausse (+40 bps en 4 h), l'autre moitié avant une baisse."""
    rng = np.random.default_rng(seed)
    n = jours * JOUR // BAR + 1
    ts = T0 + np.arange(n, dtype=np.int64) * BAR
    logp = np.zeros((n, len(COINS)))
    fills = []
    for jour in range(15, jours - 2):
        for k in range(bons + mauvais):
            coin = k % 3 if k < bons else 3 + k % 3             # les bons et les mauvais ne tradent pas les mêmes coins
            t = T0 + jour * JOUR + (k * 97 + jour * 31) % (18 * 60) * 60_000
            fills.append(_fill(f"0x{k:040x}", COINS[coin], t, signe=1))
            entree = -(-(t + 30_000 + CONFIG.reaction_ms) // BAR) * BAR
            i0 = (entree - T0) // BAR
            rampe = np.clip((np.arange(n) - i0) / (4 * HEURE // BAR), 0.0, 1.0)
            logp[:, coin] += (40.0 if k < bons else -40.0) / 1e4 * rampe + rng.normal(0, 1e-6)
    panel = PricePanel(ts=ts, px=100.0 * np.exp(logp), coins=COINS, provenance="test", stale_ms=BAR + 60_000)
    return pd.DataFrame(fills), panel


def test_la_selection_en_marche_avant_retient_les_leaders_au_passe_gagnant():
    fills, panel = _monde_deux_sortes(bons=12, mauvais=12)
    etude = _etude(fills, panel)
    choix = etude["selection"]["primaire"]
    retenus, eligibles, ecartes = choix["retenus"], choix["eligibles"], choix["ecartes"]
    assert retenus["leaders"] == 12 and ecartes["leaders"] == 12          # exactement les bons d'un côté, les mauvais de l'autre
    assert retenus["net"]["moyenne_bps"] > 20 and ecartes["net"]["moyenne_bps"] < -40
    assert abs(eligibles["net"]["moyenne_bps"] + COUT) < 8                # tout copier : on ne paie que les frais
    ecart = choix["ecart_retenus_moins_eligibles"]
    assert ecart["moyenne_bps"] > 30 and ecart["intervalle_bps"][0] > 0
    assert choix["capital_350"]["esperance_usd_par_jour"] > 0
    verdicts = {v["hypothesis"]: v["status"] for v in etude["verdicts"]}
    assert verdicts[E.H_SELECTED_LEADERS] == "PROMISING" and verdicts[E.H_AGGRESSIVE_OPEN] != "PROMISING"
    assert etude["hypotheses_tested"] == (3 * 3 + 1) * 1 * 2             # la règle de sélection est comptée


def test_la_note_d_un_leader_ne_lit_que_ses_decisions_deja_denouees():
    """Métamorphique : changer l'issue des décisions à partir d'un instant ne change aucune sélection antérieure,
    et une décision n'est jamais retenue sur la foi de sa propre issue."""
    fills, panel = _monde_deux_sortes(jours=60)
    table, _ = E.event_returns(E.build_events(fills, {}, CONFIG), panel, ECARTS, horizon_h=4, bar_ms=BAR, config=CONFIG)
    avant = E.walk_forward_selection(table, horizon_h=4, niveau=0.95, config=CONFIG)
    coupe = int(table["entree"].quantile(0.6))
    truque = table.copy()
    truque.loc[truque["entree"] >= coupe, "net_bps"] = -500.0
    apres = E.walk_forward_selection(truque, horizon_h=4, niveau=0.95, config=CONFIG)
    # les décisions prises AVANT la coupure et retenues restent exactement les mêmes
    def retenues_avant(resultat_table, borne):
        return E.walk_forward_selection(resultat_table[resultat_table["entree"] < borne], horizon_h=4, niveau=0.95,
                                        config=CONFIG)["retenus"]["evenements"]
    assert retenues_avant(table, coupe) == retenues_avant(truque, coupe) > 0
    assert apres["retenus"]["evenements"] <= avant["retenus"]["evenements"]
    # un leader sans historique dénoué n'est jamais retenu, même si toutes ses décisions gagnent
    debutant = table[table["unit"] == table["unit"].iloc[0]].head(CONFIG.selection_min_history)
    seul = E.walk_forward_selection(debutant, horizon_h=4, niveau=0.95, config=CONFIG)
    assert seul["retenus"]["evenements"] == 0 and seul["eligibles"]["evenements"] == 0


def test_sans_competence_la_selection_ne_trouve_rien_et_n_est_pas_declaree_prometteuse():
    fills, panel = _monde(derive_bps=0.0, bruit_bps=6.0, seed=12, jours=70)
    etude = _etude(fills, panel)
    choix = etude["selection"]["primaire"]
    verdict = next(v for v in etude["verdicts"] if v["hypothesis"] == E.H_SELECTED_LEADERS)
    assert verdict["status"] in {"REJECTED", "MORE_DATA"}
    ecart = choix["ecart_retenus_moins_eligibles"]
    assert ecart["intervalle_bps"] is None or ecart["intervalle_bps"][0] <= 0     # pas mieux que tout copier
    vide = E.walk_forward_selection(E.build_events(fills.iloc[:0], {}, CONFIG).assign(entree=[], net_bps=[]),
                                    horizon_h=4, niveau=0.95, config=CONFIG)
    assert vide["retenus"]["evenements"] == 0 and vide["capital_350"]["status"] == "UNMEASURABLE"
