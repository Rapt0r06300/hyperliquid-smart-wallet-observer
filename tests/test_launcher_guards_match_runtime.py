"""Les garde-fous de risque doivent EXISTER dans la config effective du lanceur.

Reecrit a l'audit 2026-07-11 : ces tests figeaient des VALEURS (min_edge=28, TP=160, levier=1...)
qui (a) ne correspondaient plus a la config calibree, et (b) se CONTREDISAIENT entre elles parce que
le .cmd et le .ps1 divergeaient. On garde l'intention -- "aucun garde-fou ne disparait en silence" --
sans geler des chiffres qu'on calibre volontairement. La coherence .cmd/.ps1 est testee dans
tests/test_launcher_config_coherence.py.
"""
from __future__ import annotations

from tests.test_launcher_config_coherence import effective_launcher_config

# Garde-fous qui doivent TOUJOURS etre presents et strictement positifs.
POSITIVE_GUARDS = [
    "HYPERSMART_SIMULATION_MIN_EDGE_BPS",
    "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE",
    "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS",
    "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS",
    "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS",
    "HYPERSMART_MAX_POSITION_USDT",
    "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT",
    "HYPERSMART_MAX_OPEN_POSITIONS",
    "HYPERSMART_SIMULATION_LEVERAGE",
    "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS",
]

# Interrupteurs qui doivent etre presents (valeur calibrable, presence obligatoire).
REQUIRED_PRESENT = [
    "HYPERSMART_SLTP_ENABLED",
    "HYPERSMART_SLTP_TAKE_PROFIT_BPS",
    "HYPERSMART_SLTP_STOP_LOSS_BPS",
    "HYPERSMART_SLTP_STOP_MIN_HOLD_MS",
    "HYPERSMART_V12_GATE_AUTHORITATIVE",
    "HYPERSMART_V9_PIPELINE_AUTHORITATIVE",
    "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY",
    "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT",
]


def test_every_risk_guard_is_present_and_positive():
    cfg = effective_launcher_config()
    for name in POSITIVE_GUARDS:
        assert name in cfg, f"garde-fou de risque DISPARU du lanceur: {name}"
        assert float(cfg[name]) > 0, f"garde-fou NEUTRALISE (<=0): {name}={cfg[name]}"


def test_every_required_switch_is_declared():
    cfg = effective_launcher_config()
    for name in REQUIRED_PRESENT:
        assert name in cfg, f"reglage obligatoire absent du lanceur: {name}"


def test_add_is_never_treated_as_an_entry():
    """ADD != OPEN : copier un ADD tardif = entrer en retard. Doit rester desactive."""
    cfg = effective_launcher_config()
    assert cfg.get("HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY") == "0"
