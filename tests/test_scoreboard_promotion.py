"""P2.1 — porte économique de promotion deny-by-default + composition avec la porte de déploiement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import scoreboard_promotion as G            # noqa: E402
from hl_observer.simulation.scoreboard_metrics import assembler_ligne   # noqa: E402
from hl_observer.backtesting.promotion_gate import PROMOUVOIR_TESTNET, RESTE_PAPER  # noqa: E402


def _row(**over):
    """Ligne de scoreboard TOTALEMENT mesurée et positive (éligible PROMOTE), surchargée au besoin."""
    base = dict(
        strategy="copy_vault", closed_pnls=[5.0, 3.0, 4.0, -1.0], n_independent=30,
        gross_edge_bps=25.0, fees_bps=1.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0,
        roi_denominator_usd=1000.0, capacity_usd=5000.0, fill_ratios=[1.0, 0.9],
        latency_p50_ms=100.0, latency_p95_ms=200.0, oos_net_bps=6.0, forward_net_bps=4.0,
    )
    base.update(over)
    return assembler_ligne(**base)


def _evidence(**over):
    base = dict(
        ledger_trusted=True, placebo_beaten=True, pbo_robuste=True, dsr_ok=True,
        lower_confidence_bound_bps=3.0, concentration=0.10, n_days=10, n_regimes=3,
        n_coins=2, min_coins=1,
    )
    base.update(over)
    return G.ScoreboardPromotionEvidence(**base)


def test_promote_si_tout_mesure_et_positif():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence())
    assert v.verdict == G.PROMOTE and v.echecs == () and v.manquants == ()


# --- KILL : un négatif décisif suffit ---------------------------------------
def test_kill_si_net_negatif():
    v = G.evaluer_promotion_scoreboard(
        _row(gross_edge_bps=3.0, fees_bps=2.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0),
        _evidence())
    assert v.verdict == G.KILL and "net_bps>0" in v.echecs


def test_kill_si_oos_negatif():
    v = G.evaluer_promotion_scoreboard(_row(oos_net_bps=-1.0), _evidence())
    assert v.verdict == G.KILL and "oos_net_bps>0" in v.echecs


def test_kill_si_placebo_non_battu():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(placebo_beaten=False))
    assert v.verdict == G.KILL and "placebo_beaten" in v.echecs


def test_kill_si_pbo_surajuste():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(pbo_robuste=False))
    assert v.verdict == G.KILL and "pbo_robuste" in v.echecs


def test_kill_si_concentration_depasse():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(concentration=0.50))
    assert v.verdict == G.KILL and "concentration<=cap" in v.echecs


def test_kill_si_borne_confiance_basse_negative():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(lower_confidence_bound_bps=-0.5))
    assert v.verdict == G.KILL and "lower_confidence_bound>0" in v.echecs


# --- MORE_DATA : rien de négatif, mais tout n'est pas prouvé ----------------
def test_more_data_si_cout_unmeasurable():
    v = G.evaluer_promotion_scoreboard(_row(slippage_bps=None), _evidence())
    assert v.verdict == G.MORE_DATA
    assert "costs_measured" in v.manquants and "net_bps>0" in v.manquants


def test_more_data_si_capacite_absente():
    v = G.evaluer_promotion_scoreboard(_row(capacity_usd=None), _evidence())
    assert v.verdict == G.MORE_DATA and "capacity_measured" in v.manquants


def test_more_data_si_latence_absente():
    v = G.evaluer_promotion_scoreboard(_row(latency_p95_ms=None), _evidence())
    assert v.verdict == G.MORE_DATA and "latency_measured" in v.manquants


def test_more_data_si_ledger_non_trusted_ne_tue_pas():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(ledger_trusted=False))
    assert v.verdict == G.MORE_DATA and "ledger_trusted" in v.manquants


def test_more_data_si_pas_assez_de_jours():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(n_days=2))
    assert v.verdict == G.MORE_DATA and "n_days>=min" in v.manquants


def test_more_data_si_dsr_non_calcule():
    v = G.evaluer_promotion_scoreboard(_row(), _evidence(dsr_ok=None))
    assert v.verdict == G.MORE_DATA and "dsr_ok" in v.manquants


def test_kill_prime_sur_more_data():
    v = G.evaluer_promotion_scoreboard(_row(oos_net_bps=-1.0, capacity_usd=None), _evidence())
    assert v.verdict == G.KILL


# --- composition avec la porte de déploiement -------------------------------
def test_promotion_finale_exige_les_deux_portes():
    r = G.promotion_finale(_row(), _evidence(), deployment_decision=PROMOUVOIR_TESTNET)
    assert r["promue"] is True and r["verdict_economique"] == G.PROMOTE and r["blocage"] is None


def test_promotion_finale_bloquee_si_deploiement_reste_paper():
    r = G.promotion_finale(_row(), _evidence(), deployment_decision=RESTE_PAPER)
    assert r["promue"] is False and r["blocage"] == "DEPLOIEMENT_NON_PROMU"


def test_promotion_finale_bloquee_si_deploiement_inconnu():
    r = G.promotion_finale(_row(), _evidence(), deployment_decision=None)
    assert r["promue"] is False and r["blocage"] == "DEPLOIEMENT_INCONNU"


def test_promotion_finale_bloquee_si_economie_kill_meme_si_deploiement_ok():
    r = G.promotion_finale(_row(oos_net_bps=-1.0), _evidence(), deployment_decision=PROMOUVOIR_TESTNET)
    assert r["promue"] is False and r["blocage"] == "ECONOMIE_KILL"
    assert r["real_execution"] is False


def test_to_dict_expose_les_portes():
    d = G.evaluer_promotion_scoreboard(_row(), _evidence()).to_dict()
    assert d["verdict"] == G.PROMOTE and d["real_execution"] is False
    noms = {g["gate"] for g in d["gates"]}
    assert {"net_bps>0", "placebo_beaten", "pbo_robuste", "costs_measured", "capacity_measured"} <= noms
