from __future__ import annotations

from pathlib import Path

import pytest

from hl_observer.runtime import research_guardrails as G

ROOT = Path(__file__).resolve().parents[1]


def test_idea_81_esperance_prix_probabilite_refuse_probability_invalid():
    bad = G.esperance_entree(
        qualite_prix_bps=2,
        probabilite_succes=1.2,
        gain_attendu_bps=20,
        couts_bps=5,
    )
    assert bad["mesurable"] is False
    assert bad["motif"] == "PROBABILITE_HORS_BORNES"


def test_idea_82_styles_ne_designent_pas_de_gagnant_sans_echantillon():
    result = G.comparer_styles({"taker": [1, 2], "maker": [3, 4]}, min_n=30)
    assert result["gagnant"] is None
    assert all(row["concluant"] is False for row in result["lignes"])


def test_idea_83_adverse_selection_est_conditionnee_au_stade():
    result = G.adverse_selection_par_stade(
        [
            {"stade_execution": 0.10, "markout_bps": -1.0},
            {"stade_execution": 0.20, "markout_bps": -2.0},
            {"stade_execution": 0.90, "markout_bps": -8.0},
        ]
    )
    assert result["tranche_la_plus_toxique"] == "66-100%"


def test_idea_84_horloges_sont_pre_enregistrees_et_oos():
    result = G.horloges_lead_lag()
    assert result["pre_enregistrees"] is True
    assert result["exige_oos"] is True
    assert result["n_essais"] == 4


def test_idea_85_bibliotheque_priorise_incidents_reels():
    result = G.bibliotheque_erreurs({"par_type": {"WS_GAP": 2, "RATE_LIMIT": 1}})
    assert result["source"] == "journal_operationnel"
    assert result["incidents_reellement_observes"] == ["RATE_LIMIT", "WS_GAP"]


def test_idea_86_plan_ws_fail_closed_sur_connexions_et_users():
    result = G.verifier_plan_websockets(11, users_uniques=11)
    assert result["conforme"] is False
    assert "CONNEXIONS>10" in result["violations"]
    assert "USERS_UNIQUES>10" in result["violations"]


def test_idea_87_seuil_polymarket_ne_se_transpose_jamais():
    result = G.convertir_seuil_polymarket(5)
    assert result["transposable"] is False
    assert "bps" in result["unites_correctes"]


def test_idea_88_aucun_wallet_cle_ou_signer():
    assert G.verifier_absence_wallet({"paper_only": True})["conforme"] is True
    bad = G.verifier_absence_wallet({"private_key": "secret"})
    assert bad["conforme"] is False
    assert bad["champs_interdits_presents"] == ["private_key"]


def test_idea_89_marketing_nest_pas_une_preuve():
    assert G.poids_preuve("thread_x", chiffre=999)["role"] == "INSPIRATION"
    assert G.poids_preuve("OOS_INTERNE", chiffre=1.2)["role"] == "PREUVE"


def test_idea_90_hypothese_exige_prediction_kill_et_preregistration():
    assert G.hypothese_falsifiable("mm", prediction="", critere_kill="net<0", pre_enregistre=True)["valide"] is False
    assert G.hypothese_falsifiable(
        "mm",
        prediction="net OOS > 0",
        critere_kill="net OOS <= 0",
        pre_enregistre=True,
    )["valide"] is True


def test_idea_91_live_backtest_compare_toutes_les_metriques_separement():
    base = {metric: 100.0 for metric in G.METRIQUES_LIVE_VS_BACKTEST}
    live = dict(base)
    live["slippage"] = 130.0
    result = G.comparer_live_backtest(live, base, tolerance_relative=0.10)
    assert result["coherent"] is False
    assert result["metriques_divergentes"] == ["slippage"]
    assert result["metriques_manquantes"] == []


def test_idea_91_une_metrique_absente_est_bloquante_pas_ignoree():
    result = G.comparer_live_backtest({"pnl": 1.0}, {"pnl": 1.0})
    assert result["coherent"] is False
    assert "roi" in result["metriques_manquantes"]


def test_equivalence_canonique_legacy_sur_garde_fous_86_91():
    legacy = pytest.importorskip("garde_fous_recherche")
    assert G.convertir_seuil_polymarket(5)["transposable"] == legacy.convertir_seuil_polymarket(5)["transposable"]
    assert G.verifier_absence_wallet({"private_key": "x"})["conforme"] == legacy.verifier_absence_wallet({"private_key": "x"})["conforme"]
    assert G.poids_preuve("THREAD_X")["role"] == legacy.poids_preuve("THREAD_X")["role"]
    assert G.hypothese_falsifiable(
        "x", prediction="p", critere_kill="k", pre_enregistre=True
    )["valide"] == legacy.hypothese_falsifiable(
        "x", prediction="p", critere_kill="k", pre_enregistre=True
    )["valide"]


def test_runtime_guardrails_sont_purs_sans_surface_execution_reelle():
    source = (ROOT / "src" / "hl_observer" / "runtime" / "research_guardrails.py").read_text(encoding="utf-8")
    for forbidden in (
        '"/exchange"',
        "'/exchange'",
        "requests.get",
        "requests.post",
        "websockets.connect",
        "import websocket",
        "eth_account",
        "Account.from_key",
        "place_order",
        "market_order",
    ):
        assert forbidden not in source
