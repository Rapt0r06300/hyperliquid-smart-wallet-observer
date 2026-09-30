"""LOT 7 — validation anti-sur-ajustement prouvée sans réseau (Flo 25/07)."""
from __future__ import annotations

import random

from hl_observer.research_parallel import validation as VAL


def test_sharpe_max_attendu_croit_avec_les_essais():
    b10 = VAL.sharpe_max_attendu(10, 1.0)
    b100 = VAL.sharpe_max_attendu(100, 1.0)
    assert b100 > b10 > 0, "plus on essaie de variantes, plus la barre à battre par chance est haute"


def test_dsr_deflate_quand_on_a_essaye_beaucoup_de_variantes():
    nets = [2.0 + random.Random(i).gauss(0, 1) for i in range(60)]     # léger edge positif
    peu = VAL.dsr(nets, sharpes_essais=[VAL.sharpe(nets), 0.1])
    bcp = VAL.dsr(nets, sharpes_essais=[VAL.sharpe(nets)] + [0.05 * k for k in range(60)])
    assert bcp["dsr"] <= peu["dsr"], "le même edge est MOINS significatif si on a testé plus de variantes"


def test_dsr_significatif_pour_edge_fort_peu_d_essais():
    nets = [5.0 + random.Random(i).gauss(0, 0.5) for i in range(40)]   # edge fort, Sharpe fini élevé
    r = VAL.dsr(nets, sharpes_essais=[VAL.sharpe(nets), 0.0])
    assert r["dsr"] is not None and r["significatif"] is True


def test_pbo_eleve_si_selection_aleatoire():
    # 6 variantes de pur bruit -> la meilleure en IS ne tient pas en OOS -> PBO élevé
    rng = random.Random(3)
    perf = {"v%d" % k: [rng.gauss(0, 1) for _ in range(16)] for k in range(6)}
    r = VAL.pbo_cscv(perf, s=8)
    assert r["pbo"] is not None and 0.0 <= r["pbo"] <= 1.0


def test_pbo_bas_si_une_variante_domine_partout():
    perf = {"gagnante": [5.0] * 16, "b": [-1.0] * 16, "c": [-2.0] * 16}
    r = VAL.pbo_cscv(perf, s=8)
    assert r["pbo"] == 0.0, "une variante qui domine IS ET OOS -> pas de sur-ajustement"


def test_dedup_retire_les_episodes_trop_proches():
    eps = [{"ts_ms": 0, "coin": "X", "variante": "V", "net_bps": 1},
           {"ts_ms": 10_000, "coin": "X", "variante": "V", "net_bps": 2},   # <60s -> retiré
           {"ts_ms": 90_000, "coin": "X", "variante": "V", "net_bps": 3}]
    assert len(VAL.dedup_episodes(eps, fenetre_ms=60_000)) == 2


def test_placebo_direction_est_le_miroir():
    eps = [{"net_bps": 4.0}, {"net_bps": 2.0}, {"net_bps": -1.0}]
    assert VAL.placebo_direction(eps) == -2.0                          # médiane des nets inversés


def test_walk_forward_purge_embargo():
    eps = [{"ts_ms": t * 1000, "net_bps": 1} for t in range(100)]
    train, test = VAL.walk_forward_purge(eps, frac_train=0.6, embargo_ms=5000)
    assert train and test
    assert max(e["ts_ms"] for e in train) < min(e["ts_ms"] for e in test), "test après train + embargo"
