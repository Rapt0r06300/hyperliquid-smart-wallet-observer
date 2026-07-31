"""ALPHA batch F — capstones : factory_families, parallel_factory, runtime_loop, acceptance."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

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
    assert PF.resultat_invariant(m1, m2) is True         # meme resultat quel que soit l'ordre


def test_runtime_loop_forward_isole():
    caps = [{"cible_candidat": "frozen1"}, {"cible_candidat": None}, {"cible_candidat": "libre"}]
    r = RL.router_capture(caps, forward_frozen_ids={"frozen1"})
    assert r["n_refuses"] == 1 and r["n_discovery"] == 2 and r["forward_isole"] is True


def test_acceptance_done_global():
    tout_ok = {c: ("BLOCKED_EXTERNAL" if c in ("data_hf", "l4_teste") else "SATISFAIT") for c in AC.CRITERES}
    assert AC.evaluer(tout_ok)["verdict_global"] == "DONE_GLOBAL"     # blocked documente tolere
    partiel = dict(tout_ok, oos="MANQUANT")
    assert AC.evaluer(partiel)["verdict_global"] == "PAS_DONE" and "oos" in AC.evaluer(partiel)["manquants"]
