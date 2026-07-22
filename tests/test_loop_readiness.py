"""LOOP READINESS — le score de maturité + l'échelle d'autonomie, portés de loop-engineering
(cobusgreyling) avec une lentille TRADING. Ce que ces tests VERROUILLENT : le no-real-trade est
un gate DUR, le réel n'est jamais un niveau atteignable, et deny-by-default (un signal absent =
non prêt). Aucune donnée réseau, aucun ordre."""
from __future__ import annotations

from hl_observer.ops import loop_readiness as LR


def _tout_vert() -> dict:
    return {c: 1.0 for c, _p, _d in LR.DIMENSIONS}


# ─────────────── le gate DUR : no-real-trade prime sur tout ───────────────

def test_une_breche_no_real_trade_force_F_et_N0_meme_si_tout_le_reste_est_parfait():
    s = _tout_vert()
    s["securite_no_real_trade"] = False           # la seule brèche
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.grade == "F"
    assert r.niveau_autonomie == LR.NIVEAU_OBSERVE
    assert r.no_real_trade_intact is False
    assert r.score_0_100 <= 15.0, "un score haut ne doit jamais survivre a une breche securite"
    assert any("NO-REAL-TRADE" in d for d in r.drapeaux_rouges)


def test_securite_ABSENTE_est_traitee_comme_une_breche_deny_by_default():
    s = _tout_vert()
    del s["securite_no_real_trade"]               # évidence absente, pas False
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.grade == "F" and r.niveau_autonomie == LR.NIVEAU_OBSERVE


# ─────────────── le RÉEL est hors échelle (plafond codé en dur) ───────────────

def test_le_niveau_maximal_atteignable_est_le_testnet_verrouille_jamais_le_reel():
    # tout parfait + verrous testnet => on PLAFONNE a N2, il n'existe pas de N3.
    r = LR.evaluer(_tout_vert(), verrous_testnet=True)
    assert r.niveau_autonomie == LR.NIVEAU_TESTNET
    # aucune constante de niveau "réel" n'existe dans le module
    assert not any("REEL" in n or "MAINNET" in n for n in LR.__all__)
    assert "N2" in LR.NIVEAU_TESTNET and r.real_execution is False


def test_N2_testnet_exige_les_verrous_sinon_on_reste_a_N1():
    r = LR.evaluer(_tout_vert(), verrous_testnet=False)
    assert r.niveau_autonomie == LR.NIVEAU_PAPER            # pas N2 sans les verrous
    assert any("verrous testnet" in d.lower() for d in r.drapeaux_rouges)


# ─────────────── deny-by-default & score ───────────────

def test_tout_vert_avec_verrous_donne_A_et_score_plein():
    r = LR.evaluer(_tout_vert(), verrous_testnet=True)
    assert r.score_0_100 == 100.0 and r.grade == "A"


def test_un_signal_absent_coute_ses_points_ET_leve_un_drapeau():
    s = _tout_vert()
    del s["donnees_fraiches"]                     # -16 points, et data pas fraîche
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.score_0_100 == 84.0                  # 100 - 16
    assert r.maillon_faible == "donnees_fraiches"
    assert r.niveau_autonomie == LR.NIVEAU_OBSERVE   # data stale bloque même N1
    assert any("absente" in d.lower() for d in r.drapeaux_rouges)


def test_donnees_a_moitie_fraiches_bloquent_l_autonomie_paper():
    s = _tout_vert()
    s["donnees_fraiches"] = 0.5                    # < seuil 0.80
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.niveau_autonomie == LR.NIVEAU_OBSERVE
    assert any("trop vieilles" in d for d in r.drapeaux_rouges)


def test_tests_rouges_bloquent_paper_et_levent_un_drapeau():
    s = _tout_vert()
    s["tests_verts"] = False
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.niveau_autonomie == LR.NIVEAU_OBSERVE
    assert any("tests rouges" in d for d in r.drapeaux_rouges)


def test_pnl_non_reconcilie_casse_la_verite_et_bloque_paper():
    s = _tout_vert()
    s["pnl_reconcilie"] = False
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.niveau_autonomie == LR.NIVEAU_OBSERVE
    assert any("vérité du PnL" in d or "PnL dashboard" in d for d in r.drapeaux_rouges)


def test_le_maillon_faible_est_la_ou_on_perd_le_PLUS_de_points():
    s = _tout_vert()
    s["pnl_reconcilie"] = 0.0                      # 16 pts perdus = le plus gros poste (hors secu)
    s["journal_present"] = 0.0                     # 6 pts perdus
    r = LR.evaluer(s, verrous_testnet=True)
    assert r.maillon_faible == "pnl_reconcilie"


# ─────────────── l'adaptateur du lanceur & le rendu ───────────────

def test_depuis_etapes_mappe_les_statuts_du_lanceur():
    etapes = {"securite": {"statut": "OK"}, "tests": {"statut": "OK"},
              "cablage": {"statut": "OK"}, "donnees_fraiches_pct": 90.0,
              "pnl_reconcilie": True, "portes_cout_actives": True,
              "kill_switch_cable": True, "journal_present": True}
    r = LR.depuis_etapes(etapes, verrous_testnet=True)
    assert r.no_real_trade_intact is True
    assert r.niveau_autonomie == LR.NIVEAU_TESTNET


def test_depuis_etapes_securite_en_echec_plafonne():
    r = LR.depuis_etapes({"securite": {"statut": "ECHEC"}, "tests": {"statut": "OK"}},
                         verrous_testnet=True)
    assert r.grade == "F" and r.niveau_autonomie == LR.NIVEAU_OBSERVE


def test_le_markdown_montre_le_score_et_le_plafond():
    r = LR.evaluer(_tout_vert(), verrous_testnet=True)
    md = LR.markdown(r)
    assert "BOT-READY" in md and "100/100" in md
    assert "testnet" in md.lower() and "hors" in md.lower()   # le réel est hors échelle
