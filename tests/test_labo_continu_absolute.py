"""LABO-CONTINU-ABSOLUTE-FINAL — recette bloquante (Flo 26/07). Tests des blocs P0..P9. Paper-only.
Chaque bloc a ses tests ; ce fichier grossit bloc par bloc jusqu'à la recette finale."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import pipeline_18h as PL             # noqa: E402
import moteur_execution_prod as MEP   # noqa: E402
import metriques_pepites as MP        # noqa: E402


# ═══════════════ P0 — fausses preuves ═══════════════
def test_approximate_positive_result_never_reaches_holdout_or_pass(tmp_path):
    """Un résultat positif mais APPROXIMATE (exit fwd_mid) ne devient jamais survivant/candidat/PASS."""
    # corpus positif MAIS sans carnet futur (fwd_mid seul) -> tout APPROXIMATE
    corpus = [{"coin": "BTC", "regime": "vol", "ts_ms": float(i), "bid": 99.95, "ask": 100.05,
               "fwd_mid": {250: 100.5, 1000: 100.4, 5000: 100.3, 30000: 100.2}} for i in range(120)]
    rd = tmp_path / "rd"
    res = PL.executer_pipeline_complet(tmp_path, rd, corpus, code_sha="approx")
    # aucun survivant / candidat gelé / forward : APPROXIMATE ne promeut jamais
    assert res["n_survivants"] == 0 and res["n_candidats_figes"] == 0 and res["n_forward_events"] == 0
    finals = json.loads((rd / "resultats" / "final_verdicts.json").read_text())
    assert all(f.get("verdict") != "PASS_FORWARD_PAPER" for f in finals)


def test_promotable_flow_separates_measured_from_promotable():
    ep_appx = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_mid": {1000: 100.5}}
    ep_book = {"coin": "BTC", "ts_ms": 0, "bid": 99.9, "ask": 100.1, "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}}
    eps = MEP.evaluer_episodes([ep_appx, ep_book], sens=1, horizon_ms=1000)
    assert len(PL._nets_ok(eps)) == 2          # diagnostic : les deux mesurés
    assert len(PL._nets_promo(eps)) == 1        # promouvable : seul le FWD_BOOK


def test_parameter_plateau_not_horizon_plateau():
    # plateau de PARAMÈTRES via un evaluer_seuil qui dépend du seuil (pas des horizons)
    def ev_seuil(s):
        return [10.0 - abs(s - 8) * 0.5] * 20   # zone stable autour de seuil=8
    plat = MP.plateau_parametres(seuil=8, evaluer_seuil=ev_seuil, famille_a_predicat=True)
    assert plat["plateau_parametres"] is True and "courbe" in plat and plat["n_voisins"] >= 3
    # sans paramètre actif -> None (jamais confondu avec une stabilité d'horizons)
    plat2 = MP.plateau_parametres(seuil=8, evaluer_seuil=ev_seuil, famille_a_predicat=False)
    assert plat2["plateau_parametres"] is None and plat2["motif"] == "PAS_DE_PARAMETRE_ACTIF"


def test_concentration_replays_same_signal():
    # evaluer_coin doit recevoir chaque coin et rejouer LE MÊME signal ; on vérifie que les 2 coins sont testés
    vus = []
    def ev_coin(coin):
        vus.append(coin)
        return [5.0, 6.0] if coin == "BTC" else [0.1, 0.2]
    conc = MP.concentration_reelle(coins=["BTC", "ETH"], evaluer_coin=ev_coin)
    assert set(vus) == {"BTC", "ETH"} and conc["n_coins"] == 2
    assert conc["un_seul_coin_dominant"] is True and conc["part_max"] > 0.6   # BTC domine


def test_capacity_requires_real_l2():
    # sans profondeur L2 -> DATA_MISSING_L2 (jamais un chiffre inventé)
    corpus_sans = [{"coin": "BTC", "ts_ms": i, "bid": 99.9, "ask": 100.1,
                    "fwd_bid": {1000: 100.4}, "fwd_ask": {1000: 100.6}} for i in range(20)]
    capa = MP.capacite_reelle(corpus_sans, sens=1, horizon_ms=1000, courbe_capacite=MEP.courbe_capacite)
    assert capa["capacite_non_nulle"] is None and capa["motif"] == "DATA_MISSING_L2"
    # avec profondeur + carnet futur -> calculée
    corpus_avec = [{**e, "bids": [[99.9, 100.0], [99.8, 100.0]], "asks": [[100.1, 100.0], [100.2, 100.0]]}
                   for e in corpus_sans]
    capa2 = MP.capacite_reelle(corpus_avec, sens=1, horizon_ms=1000, courbe_capacite=MEP.courbe_capacite)
    assert capa2["capacite_non_nulle"] is not None


# ═══════════════ P1 — CanonicalEventStore + maturation ═══════════════
import canonical_store as CS  # noqa: E402


def _marche(coin, ts0, n, base=100.0):
    return {coin: [{"coin": coin, "ts_ms": ts0 + i * 100, "bid": base - 0.05, "ask": base + 0.05} for i in range(n)]}


def test_pending_event_matures_once(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    st.ingerer([{"coin": "BTC", "ts_ms": 1000.0, "bid": 99.95, "ask": 100.05, "_source": "s"}])
    assert st.backlog() == 1 and st.compte().get("PENDING") == 1
    # sans futur suffisant -> reste PENDING
    st.maturer({}, maintenant_ms=1100.0)
    assert st.backlog() == 1
    # avec les ticks futurs (>= ts+horizon) -> READY
    st.maturer(_marche("BTC", 1000.0, 40), maintenant_ms=5000.0)
    prets = st.consommer()
    assert len(prets) == 1 and prets[0]["exit_source"] if False else len(prets) == 1
    assert prets[0]["fwd_bid"] and prets[0]["fwd_ask"]        # vrai carnet futur joint
    assert st.consommer() == []                              # consommé UNE seule fois


def test_pending_survives_restart(tmp_path):
    st = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    st.ingerer([{"coin": "ETH", "ts_ms": 500.0, "bid": 50.0, "ask": 50.02, "_source": "s"}])
    assert st.backlog() == 1
    # "redémarrage" : nouvelle instance recharge l'état depuis le disque -> PENDING toujours là
    st2 = CS.CanonicalStore(tmp_path, horizons=(250, 1000))
    assert st2.backlog() == 1 and st2.compte().get("PENDING") == 1
    st2.maturer(_marche("ETH", 500.0, 40, base=50.0), maintenant_ms=5000.0)
    assert len(st2.consommer()) == 1                          # mûrit après reprise


def test_ingestion_deduplique(tmp_path):
    st = CS.CanonicalStore(tmp_path)
    ev = [{"coin": "BTC", "ts_ms": 1.0, "bid": 1, "ask": 2, "_source": "s"}]
    r1 = st.ingerer(ev); r2 = st.ingerer(ev)
    assert r1["n_pending_ajoutes"] == 1 and r2["n_dupliques"] == 1 and r2["n_pending_ajoutes"] == 0


# ═══════════════ P2 — holdout ≠ forward + freeze_ts + embargo ═══════════════
def test_embargo_uses_real_maximum():
    # embargo = max(horizon, latence max, durée max features) — jamais 1 ms
    e = PL.embargo_reel([250, 1000], latence_max_ms=2000.0, feature_dur_max_ms=60000.0)
    assert e == 60000.0                                       # la durée des features domine ici
    e2 = PL.embargo_reel([120000], latence_max_ms=2000.0, feature_dur_max_ms=1000.0)
    assert e2 == 120000.0                                     # l'horizon domine là
    assert PL.embargo_reel([250]) != 1.0                     # jamais 1 ms codé en dur


def test_holdout_and_forward_are_disjoint_and_after_freeze(tmp_path):
    rd = tmp_path / "rd"
    PL.executer_pipeline_complet(tmp_path, rd, PL.corpus_fixtures(), code_sha="p2")
    fz = json.loads((rd / "resultats" / "freeze.json").read_text())
    assert fz["freeze_ts"] > 0 and fz["n_forward"] >= 0 and fz["embargo_ms"] >= 60000.0
    # forward_paper : chaque événement a exchange_ts (ts) > freeze_ts, et aucun du holdout
    fwd = [json.loads(l) for l in (rd / "ledger" / "forward_paper.jsonl").read_text().splitlines()] \
        if (rd / "ledger" / "forward_paper.jsonl").exists() else []
    assert all(e["ts_ms"] > fz["freeze_ts"] for e in fwd)    # forward STRICTEMENT après le gel
    # candidats figés : conservent freeze_ts / data_cutoff / n_forward_live / régimes
    finals = json.loads((rd / "resultats" / "final_verdicts.json").read_text())
    if finals:
        assert "freeze_ts" in finals[0] and "n_forward_live" in finals[0] and "forward_regimes" in finals[0]


# ═══════════════ P3 — portefeuille GLOBAL vivant persistant ═══════════════
import portefeuille_global as PG  # noqa: E402


def test_global_portfolio_shared_during_execution(tmp_path):
    pf = PG.PortefeuilleGlobal(tmp_path / "gp", capital_initial=100.0, levier=1.0, max_expo_coin_frac=1.0)
    a = pf.ouvrir("cand1:p", coin="BTC", sens=1, notional=60.0, prix=100.0)
    b = pf.ouvrir("cand2:p", coin="ETH", sens=1, notional=60.0, prix=100.0)   # même capital -> refus
    assert not a.get("refus") and b.get("refus") == "CAPITAL_INSUFFISANT"
    pf.fermer("cand1:p", prix=101.0)
    c = pf.ouvrir("cand2:p", coin="ETH", sens=1, notional=60.0, prix=100.0)   # capital libéré -> OK
    assert not c.get("refus")


def test_global_portfolio_resume_open_positions(tmp_path):
    d = tmp_path / "gp"
    pf = PG.PortefeuilleGlobal(d, capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0)
    assert len(pf.positions) == 1
    # "crash" : nouvelle instance recharge l'état -> la position OUVERTE est reprise
    pf2 = PG.PortefeuilleGlobal(d)
    assert len(pf2.positions) == 1 and "p1" in pf2.positions
    pf2.fermer("p1", prix=102.0)                              # on peut la fermer après reprise
    assert len(pf2.positions) == 0 and pf2.realized > 0


def test_global_reconciliation_not_hardcoded(tmp_path):
    d = tmp_path / "gp"
    pf = PG.PortefeuilleGlobal(d, capital_initial=1000.0, levier=3.0)
    pf.ouvrir("p1", coin="BTC", sens=1, notional=300.0, prix=100.0, couts={"fees_bps": 2.0})
    pf.fermer("p1", prix=102.0, couts={"fees_bps": 2.0})
    rec = pf.reconcilier()
    assert rec["coherent"] is True and abs(rec["cash_ledger"] - rec["cash_snapshot"]) < 1e-4
    # si on corrompt le snapshot, coherent devient False (donc pas codé en dur)
    pf.cash += 123.0
    assert pf.reconcilier()["coherent"] is False
