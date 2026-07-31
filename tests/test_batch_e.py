"""ALPHA batch E — validation/runtime/portfolio : forward_frozen, purged_cv, sizing, portfolio,
feature_cache, replay_consistency."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pytest  # noqa: E402

from hl_observer.research import feature_cache as FC  # noqa: E402
from hl_observer.research import forward_frozen as FF  # noqa: E402
from hl_observer.research import portfolio as PF  # noqa: E402
from hl_observer.research import purged_cv as PC  # noqa: E402
from hl_observer.research import replay_consistency as RC  # noqa: E402
from hl_observer.research import sizing as SZ  # noqa: E402


def test_forward_frozen_scelle_et_refuse_retune():
    ff = FF.ForwardFrozen()
    ff.promouvoir("c1", {"seuil": 5, "h": 2})
    ff.promouvoir("c1", {"seuil": 5, "h": 2})              # meme config -> ok (idempotent)
    with pytest.raises(ValueError):
        ff.promouvoir("c1", {"seuil": 9, "h": 2})          # retune -> refuse
    ff.observer("c1", {"net_bps": 4.0})
    assert ff.etat("c1")["net_moyen_forward_bps"] == 4.0


def test_forward_frozen_persistant_reprise(tmp_path):
    # FIX-47 : l'etat survit au process (journal JSONL rechargé)
    p = str(tmp_path / "forward.jsonl")
    ff = FF.ForwardFrozen(p)
    ff.promouvoir("cand", {"seuil": 5})
    ff.observer("cand", {"net_bps": 6.0})
    ff.observer("cand", {"net_bps": 8.0})
    # nouveau process : on relit le journal
    ff2 = FF.ForwardFrozen(p)
    assert ff2.candidats() == ["cand"]
    assert ff2.etat("cand")["n_observations"] == 2 and ff2.etat("cand")["net_moyen_forward_bps"] == 7.0
    with pytest.raises(ValueError):                        # config scellee -> retune refuse apres reprise
        ff2.promouvoir("cand", {"seuil": 99})


def test_purged_cv():
    folds = PC.splits_purged(100, n_folds=5, horizon=2, embargo=1)
    assert len(folds) == 5
    f0 = folds[0]
    assert PC.fuite_presente(f0["train"], f0["test"], horizon=2) is False   # train purgé -> pas de fuite
    assert PC.prefix_stable([1, 2, 3, 4], [1, 2, 3]) is True


def test_sizing_ne_repare_pas_mauvais_edge():
    assert SZ.kelly_fraction(-5.0, 4.0) == 0.0
    assert SZ.taille_notionnelle(-1.0, 4.0, capital_usd=1000)["notional_usd"] == 0.0
    bon = SZ.taille_notionnelle(10.0, 4.0, capital_usd=1000, capacity_usd=50.0)
    assert 0 < bon["notional_usd"] <= 50.0                 # borné par capacité


def test_portfolio_allocation():
    a = [1.0, 2.0, 1.5, 2.0, 1.0, 1.8]
    b = [1.0, 2.0, 1.5, 2.0, 1.0, 1.8]                     # identique -> corrélé -> pénalisé
    c = [2.0, -1.0, 1.5, -0.5, 2.0, -1.0]                  # décorrélé
    al = PF.allocation({"a": a, "b": b, "c": c})
    assert al["verdict"] == "ALLOUE" and abs(sum(al["poids"].values()) - 1.0) < 1e-2   # tolérance arrondi 4 déc.


def test_feature_cache_invariance():
    fc = FC.FeatureCache()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 42
    assert fc.get_or_compute("k", fn) == 42
    assert fc.get_or_compute("k", fn) == 42                # 2e appel = cache, pas recalcul
    assert calls["n"] == 1 and fc.invariance_ok("k", lambda: 42) is True


def test_replay_consistency():
    assert RC.deterministe([1, 2, 3], [1, 2, 3]) is True
    assert RC.prefix_stable([1, 2, 3, 4], [1, 2]) is True
    evs = [{"seq": 1}, {"seq": 1}, {"seq": 0}, {"seq": 2, "book_ts_ms": 0}]
    r = RC.filtre_evenements(evs, dernier_seq=0, now_ms=10000, book_max_age_ms=5000)
    assert r["rejets"]["doublon"] >= 1 and r["rejets"]["out_of_order"] >= 1 and r["rejets"]["stale"] >= 1


def test_fix14_classer_desync_taxonomie():
    evs = [
        {"seq": 0},                                   # OK
        {"seq": 1},                                   # OK
        {"seq": 1},                                   # DUPLICATE (seq 1 deja vue)
        {"seq": 5},                                   # SOURCE_GAP (1 -> 5, evenements manquants)
        {"seq": 3},                                   # ORDERING (3 < dernier=5, jamais vue)
        {"seq": 6, "is_snapshot": True},              # BOOTSTRAP (backfill, pas du live)
        {"px": 1},                                    # SCHEMA (pas de seq)
        {"seq": 7, "book_ts_ms": 0},                  # STALE (now=10000, max=5000)
    ]
    r = RC.classer_desync(evs, now_ms=10000, book_max_age_ms=5000)
    c = r["compteur"]
    assert c["OK"] == 2 and c["DUPLICATE"] == 1 and c["ORDERING"] == 1
    assert c["SOURCE_GAP"] == 1 and c["BOOTSTRAP"] == 1 and c["SCHEMA"] == 1 and c["STALE"] == 1
    assert r["n_propres"] == 2 and [e["seq"] for e in r["propres"]] == [0, 1]   # seuls les OK sont propres
    assert sum(c.values()) == r["n_total"] == 8
