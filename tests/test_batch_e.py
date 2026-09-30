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


def test_fix50_sizing_interdit_avant_preuve_oos_forward():
    # FIX-50 : le sizing ne PARIE pas sur un edge non prouvé. Sans OOS+forward positifs -> notional 0.
    r0 = SZ.sizing_apres_preuve(oos_net_bps=None, forward_net_bps=None, edge_net_bps=10.0,
                                variance_bps2=4.0, capital_usd=1000)
    assert r0["notional_usd"] == 0.0 and "INTERDIT" in r0["raison"]
    r1 = SZ.sizing_apres_preuve(oos_net_bps=8.0, forward_net_bps=-1.0, edge_net_bps=10.0,
                                variance_bps2=4.0, capital_usd=1000)
    assert r1["notional_usd"] == 0.0                        # forward négatif -> toujours interdit
    r2 = SZ.sizing_apres_preuve(oos_net_bps=8.0, forward_net_bps=5.0, edge_net_bps=10.0,
                                variance_bps2=4.0, capital_usd=1000, capacity_usd=50.0)
    assert r2["notional_usd"] > 0 and r2["preuve"] == "OOS+FORWARD>0"   # OOS ET forward >0 -> autorisé


def test_fix50_es_borne_reellement_la_taille():
    # FIX-50 : es_bps n'est plus un paramètre mort — un ES (tail loss) élevé plafonne la taille.
    sans = SZ.taille_notionnelle(50.0, 1.0, capital_usd=1000)                          # Kelly plafonné cap=0.02 -> 20
    avec = SZ.taille_notionnelle(50.0, 1.0, capital_usd=1000, es_bps=1000.0, es_budget_bps=10.0)
    assert avec["notional_usd"] < sans["notional_usd"] and avec["borne_es"] == 1000.0


def test_fix50_sizing_fixe_alimente_un_paperintent():
    from hl_observer.ops.paper_canonique import PaperIntent
    fixe = SZ.sizing_apres_preuve(oos_net_bps=8.0, forward_net_bps=5.0, edge_net_bps=10.0,
                                  variance_bps2=4.0, capital_usd=1000, mode="fixe", frac_fixe=0.01)
    assert fixe["notional_usd"] == 10.0 and fixe["mode"] == "FIXE"
    intent = PaperIntent(strategy="lead_lag", coin="BTC", side=1,
                         notional_usd=fixe["notional_usd"], signal_observable_at_ms=0)
    assert intent.as_dict()["notional_usd"] == 10.0 and intent.as_dict()["real_execution"] is False


def test_portfolio_allocation():
    a = [1.0, 2.0, 1.5, 2.0, 1.0, 1.8]
    b = [1.0, 2.0, 1.5, 2.0, 1.0, 1.8]                     # identique -> corrélé -> pénalisé
    c = [2.0, -1.0, 1.5, -0.5, 2.0, -1.0]                  # décorrélé
    al = PF.allocation({"a": a, "b": b, "c": c})
    assert al["verdict"] == "ALLOUE" and abs(sum(al["poids"].values()) - 1.0) < 1e-2   # tolérance arrondi 4 déc.


def test_fix51_chevauchement_entites_penalise_les_redondants():
    # FIX-51 : deux alphas peu corrélés en PnL mais sur LES MÊMES entités sont redondants -> pénalisés ;
    # l'alpha sur une entité distincte gagne du poids. (l'indépendance ne se juge pas qu'au PnL)
    s1 = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
    s2 = [2.0, 1.0, 2.0, 1.0, 2.0, 1.0]      # anti-corrélé de s1 (corr⁺=0) mais mêmes entités
    d = [1.5, 1.5, 1.5, 1.5, 1.5, 1.5]
    base = PF.allocation({"s1": s1, "s2": s2, "d": d})
    avec = PF.allocation({"s1": s1, "s2": s2, "d": d},
                         entites={"s1": {"BTC"}, "s2": {"BTC"}, "d": {"SOL"}})
    assert avec["poids"]["d"] > base["poids"]["d"]        # l'alpha à entité distincte gagne
    assert avec["poids"]["s1"] < base["poids"]["s1"]      # les redondants (mêmes entités) sont pénalisés
    assert avec["verdict"] == "ALLOUE"


def test_fix51_beta_covariance_et_chevauchements():
    pnl = [1.0, 2.0, 3.0, 4.0, 5.0]
    fac = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(PF.beta(pnl, fac) - 1.0) < 1e-9           # bêta 1 : parfaitement exposé au facteur commun
    assert PF.covariance(pnl, fac) > 0
    assert PF.chevauchement_temporel([0, 100, 200], [50, 150, 250], fenetre_ms=1000) == 1.0
    assert PF.chevauchement_temporel([0, 100], [10000, 10100], fenetre_ms=1000) == 0.0
    assert PF.chevauchement_entites({"BTC", "ETH"}, {"ETH"}) == 0.5


def test_fix51_un_seul_survivant_positif_est_SOLO():
    seul = {"a": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0], "b": [-1.0, -2.0, -1.0, -2.0, -1.0, -2.0]}
    al = PF.allocation(seul)
    assert al["verdict"] == "SOLO" and al["n_positifs"] == 1       # portefeuille non pertinent avec 1 survivant
    assert al["poids"]["a"] == 1.0 and al["poids"]["b"] == 0.0


def test_feature_cache_invariance():
    fc = FC.FeatureCache()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return 42
    assert fc.get_or_compute("k", fn) == 42
    assert fc.get_or_compute("k", fn) == 42                # 2e appel = cache, pas recalcul
    assert calls["n"] == 1 and fc.invariance_ok("k", lambda: 42) is True


def test_fix52_cle_feature_et_immutabilite_stricte():
    import pytest
    fc = FC.FeatureCache()
    cle = FC.cle_feature("sha_source", "charger_fills", version="v1")
    assert fc.get_or_compute(cle, lambda: [1, 2, 3]) == [1, 2, 3]
    assert fc.get_or_compute(cle, lambda: [9, 9, 9]) == [1, 2, 3]   # write-once : ne recalcule/écrase jamais
    assert fc.hits == 1 and fc.miss == 1
    with pytest.raises(ValueError):
        fc.poser_immuable(cle, [9, 9, 9])                          # re-poser une valeur divergente = violation
    assert fc.poser_immuable(cle, [1, 2, 3]) == [1, 2, 3]          # ré-poser la MÊME valeur = OK


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
