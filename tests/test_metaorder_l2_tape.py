"""TAPE L2/OFI SHADOW v2 (rectif Flo 24/07) — cœur PUR, sans réseau, sans position.

On teste : résumé (imbalance STATIQUE + book_exchange_time), **vrai OFI** entre snapshots SUCCESSIFS,
latence pipeline TOUJOURS ≥ 0 (horloges séparées), extraction pré/entrée/post, ligne continuation
(OFI_NON_MESURABLE sans pré), ligne de sortie (retard réel), et le round-trip écriture→chargement (schéma v2).
"""
from __future__ import annotations

import importlib

T = importlib.import_module("hl_observer.experimental.metaorder_l2_tape")


def _book(bid=99.9, ask=100.1, bsz=1000.0, asz=1000.0, t=5000):
    return {"time": t, "levels": [[{"px": str(bid), "sz": str(bsz)}, {"px": str(bid - 0.1), "sz": "500"}],
                                  [{"px": str(ask), "sz": str(asz)}, {"px": str(ask + 0.1), "sz": "500"}]]}


def test_resume_book_imbalance_statique_et_exchange_time():
    r = T.resume_book(_book(bsz=1500, asz=900, t=42))
    assert abs(r["mid"] - 100.0) < 1e-6 and r["book_exchange_time"] == 42
    assert r["book_imbalance_top5"] == (1500 + 500) - (900 + 500)   # Σbid − Σask top-5 (STATIQUE, pas un OFI)
    assert T.book_imbalance_top5(r) == r["book_imbalance_top5"] and T.resume_book({}) is None


def test_vrai_ofi_entre_snapshots_successifs():
    prev = {"bids5": [[100.0, 10.0], [99.0, 10.0]], "asks5": [[101.0, 10.0], [102.0, 10.0]]}
    cur = {"bids5": [[100.0, 15.0], [99.0, 10.0]], "asks5": [[101.0, 8.0], [102.0, 10.0]]}   # +5 bid, -2 ask
    assert T.ofi_top5(prev, cur) == 7.0                             # e_bid(+5) − e_ask(−2) = +7 (pression acheteuse)
    assert T.ofi_top5(None, cur) is None                           # snapshot manquant -> None (OFI_NON_MESURABLE)


def test_latence_pipeline_toujours_positive():
    assert T.latence_pipeline_ms(1000.0, 1300.0) == 300.0          # book reçu 300 ms APRÈS le fill
    assert T.latence_pipeline_ms(1000.0, 900.0) is None            # book AVANT le fill -> pas un snapshot d'entrée


def test_etats_pre_entree_post():
    buf = [{"recv_mono": 100.0, "resume": {"m": "a"}}, {"recv_mono": 200.0, "resume": {"m": "b"}},
           {"recv_mono": 300.0, "resume": {"m": "c", "book_exchange_time": None}}, {"recv_mono": 400.0, "resume": {"m": "d"}}]
    assert T.etat_pre(buf, 250.0)["resume"]["m"] == "b"           # dernier AVANT 250
    assert T.etat_entree(buf, 250.0, None)["resume"]["m"] == "c"  # 1er APRÈS 250 (postérieur au fill)
    assert [e["resume"]["m"] for e in T.etats_post(buf, 300.0, n=3)] == ["d"]
    assert T.etat_pre(buf, 50.0) is None                          # rien avant -> pré-fill absent


def test_ligne_continuation_ofi_non_mesurable_sans_pre_et_horloges_separees():
    fill = {"coin": "sol", "ts_ms": 1000, "hash": "h1", "signe": 1}
    ent = {"recv_mono": 5500.0, "resume": T.resume_book(_book(t=1200))}
    pre = {"recv_mono": 5000.0, "resume": {"bids5": [[99.9, 10.0]], "asks5": [[100.1, 10.0]]}}
    l = T.ligne_continuation(fill, pre=pre, entree=ent, posts=[], fill_recv_mono=5200.0)
    assert l["schema_version"] == "shadow_l2_v2" and l["latence_pipeline_ms"] == 300.0   # 5500-5200 ≥ 0
    assert l["fill_exchange_time"] == 1000 and l["book_exchange_time"] == 1200           # horloges HL séparées
    assert l["ofi_statut"] == "OK" and l["book_imbalance_top5"] is not None              # imbalance ≠ OFI
    # sans état pré-fill -> OFI_NON_MESURABLE (rien inventé)
    l2 = T.ligne_continuation(fill, pre=None, entree=ent, posts=[], fill_recv_mono=5200.0)
    assert l2["ofi_statut"] == "OFI_NON_MESURABLE" and l2["ofi_top5"] is None and l2["ofi_mesurable"] is False
    assert T.ligne_continuation(fill, pre=pre, entree=None, posts=[], fill_recv_mono=5200.0) is None   # pas d'entrée


def test_ligne_sortie_retard_reel(tmp_path):
    fill = {"coin": "SOL", "ts_ms": 1000, "hash": "h1"}
    r = T.resume_book(_book())
    s = T.ligne_sortie(fill, entree_resume=r, capture_recv_mono=306000.0, horizon_ms=300_000.0, fill_recv_mono=5000.0)
    assert s["phase"] == "sortie" and s["retard_sortie_ms"] == 306000.0 - (5000.0 + 300000.0)   # 1000 ms de retard
    T.ecrire_lignes(tmp_path, [T.ligne_continuation(fill, pre={"recv_mono": 1, "resume": r}, entree={"recv_mono": 5500.0, "resume": r}, posts=[], fill_recv_mono=5200.0), s])
    tape = T.charger_tape(tmp_path)
    k = T.cle_fill("SOL", "h1", 1000)
    assert k in tape and "continuation" in tape[k] and "sortie" in tape[k]   # schéma v2 rechargé
