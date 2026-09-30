"""ALPHA batch F — capstones : factory_families, parallel_factory, runtime_loop, acceptance."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

import pytest  # noqa: E402

from hl_observer.research import acceptance as AC  # noqa: E402
from hl_observer.research import factory_families as FF  # noqa: E402
from hl_observer.research import parallel_factory as PF  # noqa: E402
from hl_observer.research import runtime_loop as RL  # noqa: E402


def test_factory_families_exhaustivite():
    couvrir = FF.familles_a_couvrir()
    assert "lead_lag" in couvrir and "l4_intent" not in couvrir     # l4 est BLOCKED, exempte
    modules = {v["module"] for v in FF.FAMILLES.values()}
    v = FF.verifier_exhaustivite(modules)
    assert v["exhaustif"] is True and "l4_intent" in v["bloquees"]


def test_parallel_factory_deterministe():
    w1 = [{"trial_id": "a", "net_bps": 1}, {"trial_id": "b", "net_bps": 2}]
    w2 = [{"trial_id": "b", "net_bps": 2}, {"trial_id": "c", "net_bps": 3}]
    m1 = PF.merge_deterministe([w1, w2])
    m2 = PF.merge_deterministe([w2, w1])                 # ordre workers inverse
    assert [r["trial_id"] for r in m1] == ["a", "b", "c"]
    assert PF.resultat_invariant(m1, m2) is True         # meme CONTENU quel que soit l'ordre


def test_parallel_factory_conflit_contenu_error():
    w1 = [{"trial_id": "a", "net_bps": 1}]
    w2 = [{"trial_id": "a", "net_bps": 999}]              # meme id, CONTENU different -> non-determinisme
    with pytest.raises(ValueError):
        PF.merge_deterministe([w1, w2])


def _worker_det(shard):
    return [{"trial_id": "t%03d" % i, "config_hash": "t%03d" % i, "valeur": i * i} for i in shard]


def _worker_nondet(shard):
    # contenu dépend de la TAILLE du shard -> change avec le nombre de workers -> NON déterministe
    return [{"trial_id": "t%03d" % i, "config_hash": "t%03d" % i, "taille_shard": len(shard)} for i in shard]


def test_fix54_sharder_stable():
    assert PF.sharder([1, 2, 3, 4, 5], 2) == [[1, 3, 5], [2, 4]]
    assert PF.sharder([1, 2, 3], 1) == [[1, 2, 3]]


def test_fix54_parallelisation_seulement_apres_determinisme_prouve():
    items = list(range(60))
    res = PF.prouver_puis_executer(items, _worker_det, n_workers=4)
    assert res["parallelise"] is True and res["n_workers"] == 4      # déterministe -> parallélisation validée
    seq = PF.executer_parallele(items, _worker_det, n_workers=1, parallele=False)
    assert PF.resultat_invariant(res["resultat"], seq)               # 1 worker == N workers (contenu identique)


def test_fix54_non_determinisme_force_repli_sequentiel():
    items = list(range(60))
    res = PF.prouver_puis_executer(items, _worker_nondet, n_workers=4)
    assert res["parallelise"] is False and res["n_workers"] == 1     # non déterministe -> on ne parallélise PAS
    assert "non-déterminisme" in res["raison"]
    assert all(r["taille_shard"] == 60 for r in res["resultat"])     # repli séquentiel cohérent (1 shard = tout)


def test_fix54_benchmark_rapporte_temps_et_ram_reels():
    bench = PF.benchmark(list(range(300)), _worker_det, n_workers=4)
    assert bench["invariant"] is True and bench["n_items"] == 300
    assert bench["seq_ms"] >= 0 and bench["par_ms"] >= 0 and bench["speedup"] is not None
    assert bench["seq_peak_kb"] > 0 and bench["par_peak_kb"] > 0     # pic mémoire réel mesuré (tracemalloc)


def test_runtime_loop_forward_isole():
    caps = [{"cible_candidat": "frozen1"}, {"cible_candidat": None}, {"cible_candidat": "libre"}]
    r = RL.router_capture(caps, forward_frozen_ids={"frozen1"})
    assert r["n_refuses"] == 1 and r["n_discovery"] == 2 and r["forward_isole"] is True


def test_acceptance_done_global():
    tout_ok = {c: ("BLOCKED_EXTERNAL" if c in ("data_hf", "l4_teste") else "SATISFAIT") for c in AC.CRITERES}
    assert AC.evaluer(tout_ok)["verdict_global"] == "DONE_GLOBAL"     # blocked documente tolere
    partiel = dict(tout_ok, oos="MANQUANT")
    assert AC.evaluer(partiel)["verdict_global"] == "PAS_DONE" and "oos" in AC.evaluer(partiel)["manquants"]
