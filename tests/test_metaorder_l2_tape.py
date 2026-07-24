"""TAPE L2/OFI SHADOW synchronisée (rectif Flo 24/07) — cœur PUR, sans réseau, sans position.

On teste : résumé de carnet, OFI top-5, construction de ligne (entrée avec latence réelle + OFI ; sortie avec
délai), sélection des fills frais à enregistrer, échéances de sortie, et le round-trip écriture→chargement.
"""
from __future__ import annotations

import importlib

T = importlib.import_module("hl_observer.experimental.metaorder_l2_tape")


def _book(bid=99.9, ask=100.1, sz=1000.0):
    return {"levels": [[{"px": str(bid), "sz": str(sz)}, {"px": str(bid - 0.1), "sz": str(sz)}],
                       [{"px": str(ask), "sz": str(sz)}, {"px": str(ask + 0.1), "sz": str(sz)}]]}


def test_resume_book_et_ofi():
    r = T.resume_book(_book())
    assert abs(r["mid"] - 100.0) < 1e-6 and abs(r["spread_bps"] - 20.0) < 0.5 and len(r["bids5"]) == 2
    assert T.resume_book({}) is None
    prev = {"bids5": [[99.9, 1000.0]], "asks5": [[100.1, 1000.0]]}
    cur = {"bids5": [[99.9, 1500.0]], "asks5": [[100.1, 900.0]]}
    assert T.ofi_top5(prev, cur) == 600.0                        # +500 bid, -100 ask -> OFI +600 (pression acheteuse)


def test_ligne_tape_entree_latence_et_sortie_delai():
    fill = {"coin": "sol", "ts_ms": 1000, "hash": "h1", "signe": 1, "vault": "0xV"}
    e = T.ligne_tape(phase="entry", fill=fill, book_brut=_book(), capture_ts=2500,
                     prev_resume={"bids5": [[99.9, 1000.0]], "asks5": [[100.1, 1000.0]]})
    assert e["phase"] == "entry" and e["coin"] == "SOL" and e["latence_ms"] == 1500   # capture 2500 - fill 1000
    assert e["ofi_top5"] == 0.0 and e["real_execution"] is False and "top5" in e
    x = T.ligne_tape(phase="exit", fill=fill, book_brut=_book(), capture_ts=301000, entry_ts=2500)
    assert x["phase"] == "exit" and x["delai_sortie_ms"] == 301000 - 2500
    assert T.ligne_tape(phase="entry", fill=fill, book_brut={}, capture_ts=2500) is None   # carnet illisible -> None


def test_fills_a_enregistrer_et_exits_dus():
    now = 1_000_000
    fills = [{"coin": "SOL", "ts_ms": now - 1000, "hash": "a"},   # frais -> à enregistrer
             {"coin": "SOL", "ts_ms": now - 60_000, "hash": "b"}]  # trop vieux -> ignoré
    a = T.fills_a_enregistrer(fills, set(), now_ms=now, age_max_ms=5_000)
    assert [f["hash"] for f in a] == ["a"]
    assert T.fills_a_enregistrer(fills, {T.cle_fill("SOL", "a", now - 1000)}, now_ms=now) == []   # déjà vu
    assert T.exits_dus({("SOL", "a", 1): now - 1, ("SOL", "b", 2): now + 10_000}, now) == [("SOL", "a", 1)]


def test_ecrire_et_charger_roundtrip(tmp_path):
    fill = {"coin": "SOL", "ts_ms": 1000, "hash": "h1", "signe": 1}
    e = T.ligne_tape(phase="entry", fill=fill, book_brut=_book(), capture_ts=2500)
    x = T.ligne_tape(phase="exit", fill=fill, book_brut=_book(), capture_ts=301000, entry_ts=2500)
    T.ecrire_lignes(tmp_path, [e, x])
    tape = T.charger_tape(tmp_path)
    k = T.cle_fill("SOL", "h1", 1000)
    assert k in tape and tape[k]["entry"]["latence_ms"] == 1500 and tape[k]["exit"]["phase"] == "exit"
