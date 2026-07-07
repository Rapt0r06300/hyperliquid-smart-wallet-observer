from hl_observer.strategies.dip_hedge import propose_contrarian_favorite_dip_hedge, propose_panic_dip_hedge
from hl_observer.strategies.models import is_actionable, approve_with_risk
from hl_observer.calibration.emos import crps_binary, emos_apply, emos_fit, promotion_gate, reliability_diagram
from hl_observer.signals.deb_ensemble import deb_combine, deb_weights


# ---- #162 ----
def test_panic_dip_triggers_only_on_fast_big_drop():
    assert propose_panic_dip_hedge(coin="BTC", recent_return_pct=-20, window_ms=2000) is not None
    assert propose_panic_dip_hedge(coin="BTC", recent_return_pct=-5, window_ms=2000) is None   # not panic
    assert propose_panic_dip_hedge(coin="BTC", recent_return_pct=-20, window_ms=9000) is None  # too slow


def test_contrarian_favorite_dip_and_paper_only():
    intent = propose_contrarian_favorite_dip_hedge(coin="ETH", favorite_prob=0.8, short_term_return_pct=-2)
    assert intent is not None and intent.simulation_only is True
    # must go through risk engine to be actionable (never trades on its own)
    approved = approve_with_risk(intent, lambda i: (True, ["ok"]))
    assert is_actionable(approved) is True
    assert propose_contrarian_favorite_dip_hedge(coin="ETH", favorite_prob=0.5, short_term_return_pct=-2) is None


# ---- #164 ----
def test_emos_calibration_improves_and_gate():
    # raw over-confident probs; emos should pull them toward reality
    raw = [0.99]*10 + [0.01]*10
    out = [1]*7 + [0]*3 + [0]*7 + [1]*3      # not perfectly separable
    a, b = emos_fit(raw, out)
    cal = [(emos_apply(p, a, b), y) for p, y in zip(raw, out)]
    rawp = list(zip(raw, out))
    gate = promotion_gate(rawp, cal)
    assert gate["calibrated_brier"] <= gate["raw_brier"] + 1e-6
    rd = reliability_diagram(rawp)
    assert isinstance(rd, list)


def test_crps_binary_equals_brier():
    assert abs(crps_binary([(0.5, 1), (0.5, 0)]) - 0.25) < 1e-9


# ---- #165 ----
def test_deb_downweights_bad_signal():
    w = deb_weights({"good": 0.1, "bad": 0.9})
    assert w["good"] > w["bad"]               # lower error -> higher weight
    # combine: good signal says +1, bad says -1 -> result leans positive
    assert deb_combine({"good": 1.0, "bad": -1.0}, {"good": 0.1, "bad": 0.9}) > 0
