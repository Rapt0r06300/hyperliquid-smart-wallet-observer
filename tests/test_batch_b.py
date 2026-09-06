"""ALPHA batch B — fee_regime, liquidity_consumption, capacity_curve, exit_factory, maker_toxicity,
book_resiliency, spread_transition, reproducibility."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import book_resiliency as BR  # noqa: E402
from hl_observer.research import capacity_curve as CC  # noqa: E402
from hl_observer.research import exit_factory as EF  # noqa: E402
from hl_observer.research import fee_regime as FR  # noqa: E402
from hl_observer.research import liquidity_consumption as LC  # noqa: E402
from hl_observer.research import maker_toxicity as MT  # noqa: E402
from hl_observer.research import reproducibility as RP  # noqa: E402
from hl_observer.research import spread_transition as ST  # noqa: E402


def test_fee_regime_source_unique():
    m = FR.matrice_frais_bps("HL")
    # FIX-07 : maker inconnu par defaut -> UNMEASURABLE (aucun ratio invente) ; conservateur = taker
    assert m["taker_bps"] == 4.5 and m["maker_bps"] == FR.UNMEASURABLE
    assert m["maker_conservateur_bps"] == 4.5 and m["tier"] == "INCONNU" and m["rebate_bps"] is None
    # le cout maker utilisable sans tier connu = conservateur (taker), jamais un rabais suppose
    assert FR.maker_utilisable_bps("HL") == 4.5


def test_liquidity_consumption_une_seule_fois():
    led = LC.LiquidityLedger()
    led.nouvelle_update("s1", {100.0: 5.0})
    r1 = led.consommer(100.0, 3.0)
    r2 = led.consommer(100.0, 3.0)                          # il ne reste que 2
    assert r1["rempli"] == 3.0 and r2["rempli"] == 2.0 and r2["refuse"] == 1.0


def test_book_walk_buy_asks_analytique():
    book = {"asks": [(100.0, 1.0), (101.0, 1.0), (110.0, 10.0)], "bids": [(99.0, 5.0)]}
    w = CC.book_walk(book, 100.0, side="BUY")               # remplit exactement 1 base @100
    assert abs(w["vwap"] - 100.0) < 1e-9 and w["slippage_bps"] == 0.0 and w["partial"] is False
    # 150$: 100$@100 (base 1) + 50$@101 (base 0.49505) -> vwap 100.331 -> slippage ~33.1 bps
    w2 = CC.book_walk(book, 150.0, side="BUY")
    assert abs(w2["slippage_bps"] - 33.12) < 0.3 and w2["partial"] is False


def test_book_walk_sell_consomme_bids():
    book = {"asks": [(101.0, 5.0)], "bids": [(99.0, 1.0), (98.0, 1.0), (90.0, 10.0)]}
    w = CC.book_walk(book, 99.0, side="SELL")               # 1 base @99
    assert abs(w["vwap"] - 99.0) < 1e-9 and w["slippage_bps"] == 0.0


def test_book_walk_partial_fill():
    book = {"asks": [(100.0, 1.0)]}                          # seulement 100$ disponibles
    w = CC.book_walk(book, 200.0, side="BUY")
    assert w["partial"] is True and abs(w["quote_rempli_usd"] - 100.0) < 1e-6


def test_capacity_curve():
    book = {"asks": [(100.0, 1.0), (100.05, 5.0), (100.1, 100.0)]}
    c = CC.capacity_curve(book, edge_bps=20.0, side="BUY", notionals=(50, 100, 500))
    assert c["capacity_before_edge_decay_usd"] >= 100.0     # rempli plein sous 20 bps


def test_exit_factory_stop_loss():
    chemin = [0.0, -10.0, -35.0, 5.0]
    o = EF.simuler_exit(chemin, regle="STOP_LOSS", sl_bps=30.0)
    assert o["cause"] == "SL" and o["net_bps"] == -35.0
    comp = EF.comparer_exits([chemin], regles=("STOP_LOSS", "HORIZON_FIXE"))
    assert "STOP_LOSS" in comp and comp["STOP_LOSS"]["n"] == 1


def test_fix41_convergence_sort_au_retour_vers_le_fair():
    # markout monte à +40 puis reflue ; CONVERGENCE (conv_frac=0.5) sort quand il rend la moitié du pic.
    chemin = [0.0, 20.0, 40.0, 30.0, 15.0, -5.0]
    o = EF.simuler_exit(chemin, regle="CONVERGENCE", conv_frac=0.5)
    assert o["cause"] == "CONV" and o["sortie_pas"] == 4 and o["net_bps"] == 15.0   # 15 <= 0.5*40


def test_fix41_deterioration_micro_exige_une_sante_micro():
    chemin = [0.0, 10.0, 20.0, 30.0]
    # sans série de santé micro -> UNMEASURABLE (jamais un 0 fabriqué), pas une fausse sortie
    assert EF.simuler_exit(chemin, regle="DETERIORATION_MICRO")["net_bps"] is None
    # avec santé micro qui passe sous le seuil au pas 2 -> sortie au pas 2
    o = EF.simuler_exit(chemin, regle="DETERIORATION_MICRO", sante_micro=[1.0, 1.0, -0.5, 1.0], micro_seuil=0.0)
    assert o["cause"] == "MICRO" and o["sortie_pas"] == 2 and o["net_bps"] == 20.0


def test_fix41_discovery_freeze_oos_ne_reselectionne_pas():
    # DÉCOUVERTE : TAKE_PROFIT domine (spike +50 puis crash) -> gelé. OOS : la règle gelée est MESURÉE même
    # si un autre exit aurait fait mieux sur l'OOS (preuve : aucune re-sélection sur l'OOS).
    disc = [[0.0, 20.0, 50.0, 10.0, -20.0]] * 6
    choix = EF.choisir_regle_gelee(disc)
    assert choix["regle"] == "TAKE_PROFIT"
    oos = [[0.0, 45.0, 100.0, 100.0, 100.0]] * 5      # HORIZON_FIXE ferait +100, mais TP est gelé
    res = EF.factory_exit(disc, oos)
    assert res["regle_gelee"] == "TAKE_PROFIT"
    assert res["oos"]["regle"] == "TAKE_PROFIT" and res["oos"]["net_moyen_bps"] == 45.0   # +45, jamais +100


def test_maker_toxicity_gate():
    tox = MT.toxicity_score(aggr_flow_norm=0.9, queue_depletion=0.8)["toxicity"]
    e = MT.esperance_pnl_fill_bps(20.0, tox, spread_capture_bps=2.0, maker_fee_bps=1.5)
    assert MT.maker_autorise(e) is False                    # toxique -> maker refuse
    e_ok = MT.esperance_pnl_fill_bps(5.0, 0.05, spread_capture_bps=4.0, maker_fee_bps=1.0)
    assert MT.maker_autorise(e_ok) is True


def test_book_resiliency():
    r = BR.resilience([2.0, 3.0, 9.5], profondeur_avant=10.0)   # recupere ~95%
    assert r["regime"] == "REVERSAL"
    r2 = BR.resilience([2.0, 2.0, 3.0], profondeur_avant=10.0)  # reste bas
    assert r2["regime"] == "CONTINUATION"


def test_spread_transition_decisions():
    assert ST.decision(spread_bps=2.0, spread_tendance=-1.0, depth_tendance=1.0)["action"] == "MAKER"
    assert ST.decision(spread_bps=12.0, spread_tendance=1.0, depth_tendance=-1.0)["action"] == "NO_TRADE"
    assert ST.decision(spread_bps=3.0, spread_tendance=1.0, depth_tendance=0.0)["action"] == "TAKER_NOW"
    invalid = ST.decision(spread_bps=None, spread_tendance=1.0, depth_tendance=1.0)
    assert invalid == {"action": "NO_TRADE", "raison": "UNMEASURABLE"}


def test_reproducibility():
    a = RP.empreinte_repro(code_sha="abc", dataset_hash="d1", config_hash="c1", seed=42, start_ts_ms=1, end_ts_ms=9)
    b = RP.empreinte_repro(code_sha="abc", dataset_hash="d1", config_hash="c1", seed=42, start_ts_ms=100, end_ts_ms=200)
    assert RP.meme_repro(a, b) is True                      # timestamps ignores
    c = RP.empreinte_repro(code_sha="abc", dataset_hash="d2", config_hash="c1", seed=42)
    assert RP.meme_repro(a, c) is False
