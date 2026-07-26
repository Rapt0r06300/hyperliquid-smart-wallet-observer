"""LABO-CONTINU-ULTIMATE (slice UF) — tests (Flo 26/07). Chemins d'ingestion réels, moteur éco fini
(frais 4.5/1.5, exit APPROXIMATE non-promouvable, pas de double-comptage, capacité), métriques qui
débloquent les pépites (plateau/concentration/capacité), réconciliation GLOBALE (un capital, une equity
curve, drawdown non additionné), et CMD/vérif-finalisation. Paper-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import curseurs_continue as CUR       # noqa: E402
import moteur_execution_prod as MEP   # noqa: E402
import metriques_pepites as MP        # noqa: E402
import reconciliation_prod as RECO    # noqa: E402
import portefeuille_paper as PP       # noqa: E402
import recherche_continue as RC       # noqa: E402


# ─────────── UF-1 : le scanner surveille les VRAIS dossiers (research_lab/data) ───────────
def test_scanner_lit_research_lab_data(tmp_path):
    rd = tmp_path / "run"; rd.mkdir()
    d = tmp_path / "runtime" / "research_lab" / "data"; d.mkdir(parents=True)
    lignes = [{"coin": "BTC", "ts_wall_ms": 1000 + i, "bid": 100, "ask": 100.1} for i in range(5)]
    (d / "bbo_tape.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")
    scan = CUR.scanner_nouveautes(tmp_path, rd)
    assert scan["n_new"] == 5                                    # AVANT : 0 (le scanner ne regardait que runtime/data)
    assert any("research_lab/data" in s for s in scan["par_source"])
    assert "runtime/research_lab/data" in CUR.DOSSIERS_INGESTION and "logs" in CUR.DOSSIERS_INGESTION


# ─────────── UF-2 : moteur éco fini ───────────
def test_frais_defaut_taker_45_maker_15():
    assert MEP.frais_par_jambe(MEP.PROFIL_DEFAUT, maker=False) == 4.5
    assert MEP.frais_par_jambe(MEP.PROFIL_DEFAUT, maker=True) == 1.5
    assert MEP.frais_par_jambe(MEP.PROFIL_DEFAUT, maker=False, user_fees_bps=1.0) == 1.0   # userFees réel prioritaire


def test_exit_approximate_ne_promeut_pas():
    ep_mid = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.5}}
    o = MEP.evaluer_episode(ep_mid, sens=1, horizon_ms=1000)
    assert o["approximate"] is True and o["promotable"] is False   # exit dérivé de fwd_mid = APPROXIMATE
    ep_book = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}}
    o2 = MEP.evaluer_episode(ep_book, sens=1, horizon_ms=1000)
    assert o2["approximate"] is False and o2["promotable"] is True  # vrai carnet futur = promouvable


def test_pas_de_double_comptage_slippage_vwap():
    ep = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.5},
          "asks": [[100.1, 0.5], [100.2, 5.0]]}          # profondeur -> VWAP d'entrée
    o = MEP.evaluer_episode(ep, sens=1, horizon_ms=1000, notional_usd=100.0)
    assert o["slippage_source"] == "DANS_PRIX_VWAP" and o["slippage_bps"] == 0.0   # déjà dans entry_px, pas 2×


def test_courbe_capacite():
    corpus = [{"coin": "BTC", "ts_ms": i, "bid": 100 - 0.05, "ask": 100 + 0.05, "fwd_mid": {1000: 100.2}} for i in range(20)]
    courbe = MEP.courbe_capacite(corpus, sens=1, horizon_ms=1000)
    assert [p["notional_usd"] for p in courbe] == list(MEP.NOTIONALS_CAPACITE)
    assert all("net_median_bps" in p for p in courbe)


# ─────────── UF-3 : métriques qui débloquent les pépites ───────────
def test_plateau_concentration_capacite_calcules():
    # corpus multi-coins avec vrai carnet futur (FWD_BOOK) -> stabilité horizons + concentration calculables
    corpus = []
    for coin, base in (("BTC", 100.0), ("ETH", 50.0)):
        for i in range(30):
            corpus.append({"coin": coin, "ts_ms": i, "bid": base - 0.02, "ask": base + 0.02,
                           "fwd_bid": {250: base * 1.0008, 1000: base * 1.0018, 5000: base * 1.0028},
                           "fwd_ask": {250: base * 1.0012, 1000: base * 1.0022, 5000: base * 1.0032}})
    evp = lambda corp, s, h: [o["net_bps"] for o in MEP.evaluer_episodes(corp, sens=s, horizon_ms=h)
                              if o.get("status") == "OK" and o.get("promotable") and o.get("exit_source") == "FWD_BOOK"]
    stab = MP.stabilite_horizons(corpus, sens=1, horizon_ms=1000, evaluer_nets=evp)
    conc = MP.concentration_reelle(coins=["BTC", "ETH"], evaluer_coin=lambda coin: evp([e for e in corpus if e["coin"] == coin], 1, 1000))
    # plateau de PARAMÈTRES : sans famille à prédicat -> None (PAS_DE_PARAMETRE_ACTIF), honnête
    plat_sans = MP.plateau_parametres(seuil=8, evaluer_seuil=lambda s: [1, 2, 3], famille_a_predicat=False)
    plat_avec = MP.plateau_parametres(seuil=8, evaluer_seuil=lambda s: [5.0, 6.0, 5.5], famille_a_predicat=True)
    capa_sans_l2 = MP.capacite_reelle(corpus, sens=1, horizon_ms=1000, courbe_capacite=MEP.courbe_capacite)
    assert stab["stabilite_horizons"] is not None and stab["n_horizons"] >= 3
    assert conc["un_seul_coin_dominant"] is not None and conc["n_coins"] == 2
    assert plat_sans["plateau_parametres"] is None and plat_sans["motif"] == "PAS_DE_PARAMETRE_ACTIF"
    assert plat_avec["plateau_parametres"] is True                       # vrai plateau de paramètres
    assert capa_sans_l2["capacite_non_nulle"] is None and capa_sans_l2["motif"] == "DATA_MISSING_L2"  # pas de profondeur
    assert MP.statut_simple("PASS_FORWARD_PAPER", net_bps=5) == MP.STATUTS_SIMPLES["MEILLEURE"]


# ─────────── UF-4 : réconciliation GLOBALE (un capital, une equity curve) ───────────
def test_reconciliation_globale_un_seul_capital(tmp_path):
    leds = []
    for k in range(2):
        pf = PP.PortefeuillePaper(1000.0, levier=3.0)
        pf.ouvrir("p%d" % k, coin="BTC", sens=1, notional=300.0, prix=100.0, ts_ms=10 * k)
        pf.fermer("p%d" % k, prix=101.0, ts_ms=10 * k + 5)
        led = tmp_path / ("l%d.jsonl" % k); pf.ecrire_ledger(led); leds.append(led)
    ec = tmp_path / "equity_curve.jsonl"
    glob = RECO.reconstruire_global(leds, capital_initial=1000.0, equity_curve_out=ec)
    assert glob["capital_initial"] == 1000.0                    # UN capital (jamais 2000)
    assert glob["n_ledgers"] == 2 and glob["evenements"]["open"] == 2 and glob["evenements"]["close"] == 2
    assert glob["drawdown_usd"] >= 0                            # drawdown GLOBAL, pas une somme
    assert ec.exists() and len(ec.read_text().splitlines()) == 4   # une equity curve unique (4 events)


# ─────────── UF-5 : CMD menu + vérif finalisation ───────────
def test_cmd_menu_et_verifier_finalisation(tmp_path):
    cmd = (RACINE / "LANCER-RECHERCHE-CONTINUE.cmd").read_text(encoding="utf-8", errors="ignore")
    for item in ("1 - Demarrer", "2 - Reprendre", "5 - Arreter et creer le rapport", "6 - Verifier"):
        assert item in cmd
    assert "verifier-finalisation" in cmd and "errorlevel" in cmd.lower()
    # verifier_finalisation : False si rien, True si rapport + manifeste
    assert RC.verifier_finalisation(tmp_path)["finalisation_confirmee"] is False
    (tmp_path / "Rapports en continu").mkdir(parents=True)
    (tmp_path / "Rapports en continu" / "RAPPORT-RECHERCHE-CONTINUE_x_1.md").write_text("x")
    man = tmp_path / "runtime" / "research_lab" / "continuous" / "r" / "manifeste"
    man.mkdir(parents=True)
    (man / "SHA256_MANIFEST_FINAL.json").write_text("{}")
    assert RC.verifier_finalisation(tmp_path)["finalisation_confirmee"] is True


# ─────────── 14h/18h intacts ───────────
def test_14h_18h_intacts_ultimate():
    assert (RACINE / "LANCER-RECHERCHE-14H.cmd").exists() and (RACINE / "LANCER-RECHERCHE-18H.cmd").exists()
    import recherche_18h  # noqa: F401
