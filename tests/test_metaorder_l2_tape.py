"""TAPE L2/OFI SHADOW v3 (rectif Flo 25/07) — cœur PUR, sans réseau, sans position.

On teste : niveaux BRUTS top-5 [px,sz,n] conservés, imbalance/profondeur, **OFI par niveau** + agrégé +
normalisé par profondeur, latence pipeline ≥ 0, stade live (FIRST/CONTINUATION/REVERSAL), ligne_fill
(PRE/ENTRÉE/POST bruts, OFI_NON_MESURABLE sans pré, metaorder_id/fill_id/stade, horloges séparées),
ligne_sortie (retard), et le round-trip écriture→chargement (schéma v3, v1/v2 ignorés).
"""
from __future__ import annotations

import importlib

T = importlib.import_module("hl_observer.experimental.metaorder_l2_tape")


def _book(bid=99.9, ask=100.1, bsz=1000.0, asz=1000.0, bn=3, an=4, t=5000):
    return {"time": t, "levels": [[{"px": str(bid), "sz": str(bsz), "n": bn}, {"px": str(bid - 0.1), "sz": "500", "n": 2}],
                                  [{"px": str(ask), "sz": str(asz), "n": an}, {"px": str(ask + 0.1), "sz": "500", "n": 2}]]}


def test_resume_conserve_px_sz_n_et_exchange_time():
    r = T.resume_book(_book(bsz=1500, asz=900, bn=5, an=7, t=42))
    assert r["book_exchange_time"] == 42 and r["bids5"][0] == [99.9, 1500.0, 5] and r["asks5"][0][2] == 7
    assert T.book_imbalance_top5(r) == (1500 + 500) - (900 + 500)
    assert T.profondeur_top5(r) == (1500 + 500) + (900 + 500)


def test_ofi_par_niveau_agrege_et_normalise():
    prev = {"bids5": [[100.0, 10.0, 1], [99.0, 10.0, 1]], "asks5": [[101.0, 10.0, 1], [102.0, 10.0, 1]]}
    cur = {"bids5": [[100.0, 15.0, 1], [99.0, 10.0, 1]], "asks5": [[101.0, 8.0, 1], [102.0, 10.0, 1]]}
    niv = T.ofi_par_niveau(prev, cur)
    assert niv == [7.0, 0.0, 0.0, 0.0, 0.0] and T.ofi_top5(prev, cur) == 7.0     # +5 bid, +2 (ask retiré) au niveau 0
    assert abs(T.ofi_normalise_profondeur(prev, cur) - 7.0 / (25.0 + 18.0)) < 1e-6  # OFI / profondeur (comparable)
    assert T.ofi_par_niveau(None, cur) is None                                   # sans pré -> None


def test_ofi_multi_niveaux_microprice_et_forme_profondeur():
    prev = {
        "bid": 99.99, "ask": 100.01, "mid": 100.0, "spread_bps": 2.0,
        "bids5": [[99.99, 10.0, 1], [99.98, 10.0, 1], [99.97, 10.0, 1]],
        "asks5": [[100.01, 10.0, 1], [100.02, 10.0, 1], [100.03, 10.0, 1]],
    }
    cur = {
        "bid": 99.99, "ask": 100.01, "mid": 100.0, "spread_bps": 2.0,
        "bids5": [[99.99, 15.0, 1], [99.98, 11.0, 1], [99.97, 10.0, 1]],
        "asks5": [[100.01, 8.0, 1], [100.02, 9.0, 1], [100.03, 10.0, 1]],
    }
    multi = T.ofi_multi_niveaux(prev, cur)
    assert multi["ofi_l1"] == 7.0
    assert multi["ofi_l3"] == 9.0
    assert multi["ofi_l5"] == 9.0
    assert multi["integrated_ofi_normalized"] > 0
    assert T.microprice(cur) > cur["mid"]
    assert T.microprice_deviation_bps(cur) > 0
    shape = T.depth_shape(cur)
    assert set(shape) == {
        "bid_depth_slope", "ask_depth_slope",
        "bid_depth_convexity", "ask_depth_convexity",
    }


def test_depletion_flux_agressif_et_add_cancel_restent_mesurables_seulement_si_observes():
    prev = {
        "bids5": [[99.99, 10.0, 1]],
        "asks5": [[100.01, 20.0, 1]],
    }
    cur = {
        "bids5": [[99.99, 5.0, 1]],
        "asks5": [[100.01, 10.0, 1]],
    }
    depletion = T.queue_depletion(prev, cur)
    assert depletion["status"] == "MEASURED_SAME_PRICE_LEVEL"
    assert depletion["bid_depletion_ratio"] == 0.5
    assert depletion["ask_depletion_ratio"] == 0.5
    trades = [
        {"side": "B", "px": 100, "sz": 3},
        {"side": "A", "px": 100, "sz": 1},
    ]
    assert T.aggressive_trade_imbalance(trades) == 0.5
    assert T.aggressive_trade_imbalance([]) is None
    assert T.add_cancel_imbalance([])["status"] == "ADD_CANCEL_UNMEASURABLE_FROM_SNAPSHOTS"
    events = [
        {"action": "ADD", "side": "BID", "size": 3},
        {"action": "CANCEL", "side": "ASK", "size": 1},
        {"action": "ADD", "side": "ASK", "size": 2},
    ]
    assert T.add_cancel_imbalance(events)["value"] == round((3 + 1 - 2) / 6, 8)


def test_gate_microstructure_abstient_si_opposee_ou_non_mesurable():
    prev = {
        "bid": 99.99, "ask": 100.01, "mid": 100.0, "spread_bps": 2.0,
        "bids5": [[99.99, 10.0, 1]], "asks5": [[100.01, 10.0, 1]],
    }
    aligned = {
        "bid": 99.99, "ask": 100.01, "mid": 100.0, "spread_bps": 2.0,
        "bids5": [[99.99, 18.0, 1]], "asks5": [[100.01, 4.0, 1]],
    }
    opposed = {
        "bid": 99.99, "ask": 100.01, "mid": 100.0, "spread_bps": 2.0,
        "bids5": [[99.99, 4.0, 1]], "asks5": [[100.01, 18.0, 1]],
    }
    assert T.microstructure_timing_gate(prev, aligned, sens=1)["decision"] == "ALLOW_SHADOW"
    rejected = T.microstructure_timing_gate(prev, opposed, sens=1)
    assert rejected["decision"] == "ABSTAIN_SHADOW"
    assert "OFI_OPPOSED" in rejected["reasons"]
    missing = T.microstructure_timing_gate(None, aligned, sens=1)
    assert missing["decision"] == "ABSTAIN_SHADOW"
    assert "OFI_UNMEASURABLE" in missing["reasons"]


def test_ablation_microstructure_ne_promeut_qu_avec_gain_net_et_echantillon():
    rows = [
        {
            "pnl_net_bps": 5.0 if index < 30 else -5.0,
            "microstructure_gate": {
                "decision": "ALLOW_SHADOW" if index < 30 else "ABSTAIN_SHADOW",
            },
        }
        for index in range(60)
    ]
    result = T.ablation_microstructure(rows)
    assert result["base_n"] == 60
    assert result["allowed_n"] == 30
    assert result["base_mean_net_bps"] == 0.0
    assert result["allowed_mean_net_bps"] == 5.0
    assert result["promotion_eligible"] is True
    assert result["real_execution"] is False


def test_latence_pipeline_toujours_positive():
    assert T.latence_pipeline_ms(1000.0, 1300.0) == 300.0 and T.latence_pipeline_ms(1000.0, 900.0) is None


def test_eligibilite_capture_vs_statistiquement_eligible():
    ok = {"fill_exchange_time": 1000, "book_exchange_time": 1200, "latence_pipeline_ms": 300.0}
    assert T.est_eligible(ok) is True and T.statut_eligibilite(ok) == "ELIGIBLE"
    # cas WLD : latence 7067 ms > plafond 2000 -> capturé mais NON synchronisé (exclu des coûts/OOS)
    wld = {"fill_exchange_time": 1784931778238, "book_exchange_time": 1784931828858, "latence_pipeline_ms": 7067.7}
    assert T.est_eligible(wld) is False and T.statut_eligibilite(wld) == "L2_NON_SYNCHRONISE"
    # carnet ANTÉRIEUR au fill (horloge HL) -> non éligible ; latence absente -> non éligible
    assert T.est_eligible({"fill_exchange_time": 2000, "book_exchange_time": 1000, "latence_pipeline_ms": 100.0}) is False
    assert T.est_eligible({"fill_exchange_time": 1000, "book_exchange_time": 1200, "latence_pipeline_ms": None}) is False


def test_stade_live_first_continuation_reversal():
    etat = {}
    f = lambda sens, ft: {"vault": "0xV", "coin": "SOL", "signe": sens, "ts_ms": ft, "hash": "h%d" % ft}
    mo1, s1 = T.stade_live(etat, f(1, 1000));  assert s1 == "FIRST_SLICE"
    mo2, s2 = T.stade_live(etat, f(1, 2000));  assert s2 == "CONTINUATION" and mo2 == mo1   # même métaordre
    _, s3 = T.stade_live(etat, f(-1, 3000));   assert s3 == "REVERSAL"                      # inversion
    _, s4 = T.stade_live(etat, f(1, 1000 + 200_000)); assert s4 == "FIRST_SLICE"            # trou -> nouveau


def test_ligne_fill_niveaux_bruts_ofi_non_mesurable_et_horloges():
    fill = {"coin": "sol", "ts_ms": 1000, "received_at_ms": 1100,
            "hash": "h1", "signe": 1, "vault": "0xV"}
    ent = {"recv_mono": 5500.0, "recv_wall_ms": 1300, "resume": T.resume_book(_book(t=1200))}
    pre = {"recv_mono": 5000.0, "resume": {"bids5": [[99.9, 10.0, 1]], "asks5": [[100.1, 10.0, 1]]}}
    post = {"recv_mono": 6000.0, "resume": T.resume_book(_book(t=1400))}
    l = T.ligne_fill(fill, metaorder_id="mo-x", stade="CONTINUATION", pre=pre, entree=ent, posts=[post], fill_recv_mono=5200.0)
    assert l["schema_version"] == "shadow_l2_v3" and l["stade"] == "CONTINUATION" and l["fill_id"] == "h1"
    assert l["latence_pipeline_ms"] == 300.0 and l["fill_exchange_time"] == 1000 and l["book_exchange_time"] == 1200
    assert l["fill_received_at_ms"] == 1100 and l["book_received_at_ms"] == 1300
    assert l["entree"]["bids"][0] == [99.9, 1000.0, 3] and l["pre"]["bids"] and len(l["posts"]) == 1   # NIVEAUX BRUTS
    assert l["ofi_par_niveau"] is not None and l["ofi_statut"] == "OK" and l["book_imbalance_top5"] is not None
    assert l["microstructure_features"]["shadow"] is True
    assert l["microstructure_gate"]["real_execution"] is False
    l2 = T.ligne_fill(fill, metaorder_id="mo-x", stade="FIRST_SLICE", pre=None, entree=ent, posts=[], fill_recv_mono=5200.0)
    assert l2["ofi_statut"] == "OFI_NON_MESURABLE" and l2["ofi_par_niveau"] is None and l2["ofi_mesurable"] is False
    assert T.ligne_fill(fill, metaorder_id="mo-x", stade="X", pre=pre, entree=None, posts=[], fill_recv_mono=5200.0) is None


def test_ligne_sortie_et_charger_tape_v3_ignore_anciens(tmp_path):
    fill = {"coin": "SOL", "ts_ms": 1000, "hash": "h1"}
    ent = {"recv_mono": 5500.0, "resume": T.resume_book(_book())}
    sortie = {"recv_mono": 306000.0, "resume": T.resume_book(_book())}
    lf = T.ligne_fill(fill, metaorder_id="mo-x", stade="CONTINUATION", pre={"recv_mono": 1, "resume": T.resume_book(_book())},
                      entree=ent, posts=[], fill_recv_mono=5000.0)
    ls = T.ligne_sortie(fill, sortie=sortie, capture_recv_mono=306000.0, horizon_ms=300_000.0, fill_recv_mono=5000.0)
    assert ls["retard_sortie_ms"] == 306000.0 - 305000.0 and ls["bids"][0][2] == 3   # retard + niveaux bruts (n)
    # une ligne v2 périmée doit être IGNORÉE au chargement
    T.ecrire_lignes(tmp_path, [{"schema_version": "shadow_l2_v2", "phase": "continuation", "coin": "SOL",
                                "fill_id": "old", "fill_exchange_time": 1}, lf, ls])
    tape = T.charger_tape(tmp_path)
    assert T.cle_fill("SOL", "h1", 1000) in tape and ("SOL", "old", 1) not in tape   # v2 ignoré
    assert set(tape[T.cle_fill("SOL", "h1", 1000)]) == {"fill", "sortie"}
