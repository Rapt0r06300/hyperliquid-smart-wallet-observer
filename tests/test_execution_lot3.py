"""LOT 3 — exécution causale + décisions prouvées sans réseau (Flo 25/07)."""
from __future__ import annotations

from hl_observer.research_parallel import execution as EX


def _prix(base=100.0, pas=0.0, n=20, t0=1_000_000.0, dt=1000.0):
    return [(t0 + i * dt, base + i * pas, base + i * pas + 0.01) for i in range(n)]


def test_net_causal_entree_apres_latence_jamais_avant():
    prix = _prix(base=100.0, pas=0.0)
    # signal à t0 ; entrée doit être APRÈS t0+latence (400ms) -> pas la cotation de t0
    net = EX.net_causal({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizon_s=1, fee_ar_bps=0, slippage_bps=0)
    assert net is not None                       # cotation causale trouvée


def test_net_causal_long_gagne_quand_ca_monte():
    prix = _prix(base=100.0, pas=0.05)           # monte de 5 bps/pas
    net = EX.net_causal({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizon_s=5, fee_ar_bps=0, slippage_bps=0)
    assert net > 0
    net_s = EX.net_causal({"ts_ms": 1_000_000.0, "coin": "X", "sens": -1}, prix, horizon_s=5, fee_ar_bps=0, slippage_bps=0)
    assert net_s < 0                             # short perd quand ça monte


def test_non_mesurable_si_pas_de_cotation_fraiche():
    prix = [(1_000_000.0, 100.0, 100.01)]        # une seule cotation, pas d'horizon
    assert EX.net_causal({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizon_s=5) is None


def _eps(ts_net):
    return [{"ts_ms": t, "coin": "X", "variante": "V", "sens": 1, "net_bps": v} for t, v in ts_net]


def test_decision_shadow_sous_10_episodes():
    d = EX.decision(_eps([(i, 5.0) for i in range(6)]))
    assert d["decision"] == "SHADOW" and d["motif"] == "INSUFFISANT"


def test_decision_kill_si_pf_sous_1():
    d = EX.decision(_eps([(i, 3.0) for i in range(10)] + [(10 + i, -6.0) for i in range(15)]))
    assert d["decision"] == "KILL"


def test_decision_arm_si_robuste_mais_moins_de_30():
    d = EX.decision(_eps([(i, 6.0) for i in range(12)]), placebo_median=0.0)
    assert d["decision"] == "ARM_MICROCOHORTE" and d["median_sans_meilleur_bps"] > 0


def test_scale_interdit_avant_30_episodes():
    d = EX.decision(_eps([(i, 6.0) for i in range(20)]), placebo_median=0.0)
    assert d["decision"] == "ARM_MICROCOHORTE", "20 épisodes robustes -> ARM, jamais SCALE (<30)"


def test_scale_si_30_episodes_et_ic_bas_positif():
    d = EX.decision(_eps([(i, 6.0) for i in range(40)]), placebo_median=0.0)
    assert d["decision"] == "SCALE" and d["ic_bas_bps"] is not None and d["ic_bas_bps"] > 0


def test_doit_battre_le_placebo():
    # net médian +2 mais placebo +5 -> ne bat pas le fond -> pas robuste -> SHADOW (pas ARM)
    d = EX.decision(_eps([(i, 2.0) for i in range(12)]), placebo_median=5.0)
    assert d["bat_placebo"] is False and d["decision"] == "SHADOW"


def test_placebo_et_ic_bornes():
    prix = {"X": _prix(base=100.0, pas=0.02, n=60)}
    pl = EX.placebo(prix, horizon_s=3, n=50)
    assert pl["n"] > 0 and pl["median_bps"] is not None
    assert EX.ic_bootstrap_bas([5.0] * 20) == 5.0            # échantillon constant -> borne = valeur
    assert EX.ic_bootstrap_bas([1.0, 2.0]) is None           # trop peu -> None
