"""Jalon 1 — l'assembleur de scoreboard réconcilié et sa règle UNMEASURABLE."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import scoreboard_metrics as S  # noqa: E402


# --- profit_factor -----------------------------------------------------------
def test_profit_factor_gains_sur_pertes():
    assert S.profit_factor([10.0, -5.0, 4.0, -1.0]) == round(14.0 / 6.0, 6)


def test_profit_factor_sans_trade_est_unmeasurable():
    assert S.profit_factor([]) is None


def test_profit_factor_sans_perte_est_unmeasurable_pas_un_grand_nombre():
    # Que des gains → ratio non défini : None, jamais 999 ni 0.
    assert S.profit_factor([3.0, 1.0, 2.0]) is None


def test_profit_factor_ignore_les_non_finis():
    assert S.profit_factor([float("nan"), 10.0, -5.0]) == round(10.0 / 5.0, 6)


# --- max_drawdown ------------------------------------------------------------
def test_max_drawdown_est_positif_et_correct():
    # cumul: +10, +4, +9, +2 ; sommet 10 ; pire creux 10-2 = 8.
    assert S.max_drawdown([10.0, -6.0, 5.0, -7.0]) == 8.0


def test_max_drawdown_courbe_monotone_est_zero():
    assert S.max_drawdown([1.0, 2.0, 3.0]) == 0.0


def test_max_drawdown_vide_est_unmeasurable():
    assert S.max_drawdown([]) is None


# --- expected_shortfall ------------------------------------------------------
def test_expected_shortfall_moyenne_de_la_queue_basse():
    # 20 pnl, q=0.05 → k=1, pire = -50.
    vals = [-50.0] + [1.0] * 19
    assert S.expected_shortfall(vals, q=0.05) == -50.0


def test_expected_shortfall_signe_negatif_pour_pertes():
    es = S.expected_shortfall([-10.0, -20.0, 5.0, 8.0], q=0.5)
    assert es is not None and es < 0


def test_expected_shortfall_vide_est_unmeasurable():
    assert S.expected_shortfall([]) is None


def test_expected_shortfall_queue_plus_grande_que_l_echantillon_est_unmeasurable():
    assert S.expected_shortfall([-10.0, 5.0], q=2.0) is None


# --- hit_rate ----------------------------------------------------------------
def test_hit_rate_fraction_gagnante():
    assert S.hit_rate([1.0, -1.0, 2.0, -3.0]) == 0.5


def test_hit_rate_vide_est_unmeasurable():
    assert S.hit_rate([]) is None


# --- costs_bps : la règle dure ----------------------------------------------
def test_costs_bps_somme_si_toutes_mesurees():
    assert S.costs_bps(fees_bps=1.0, spread_bps=2.0, slippage_bps=0.5, latency_bps=0.5) == 4.0


def test_costs_bps_une_composante_absente_est_unmeasurable_jamais_zero():
    # slippage manquant → None, PAS 3.0 (sinon on sous-estime les coûts = faux edge).
    assert S.costs_bps(fees_bps=1.0, spread_bps=2.0, slippage_bps=None, latency_bps=0.5) is None


def test_costs_bps_zero_reel_reste_zero():
    # Zéro MESURÉ (toutes composantes présentes et nulles) est légitime.
    assert S.costs_bps(fees_bps=0.0, spread_bps=0.0, slippage_bps=0.0, latency_bps=0.0) == 0.0


# --- assembler_ligne : net_bps et verdict -----------------------------------
def test_net_bps_unmeasurable_si_un_cout_manque():
    row = S.assembler_ligne(
        "cross_venue_dislocation",
        gross_edge_bps=12.0,
        fees_bps=1.0, spread_bps=2.0, slippage_bps=None, latency_bps=0.5,  # slippage absent
    )
    assert row.costs_bps is None and row.net_bps is None
    assert "net_bps" in row.unmeasured and "costs_bps" in row.unmeasured
    assert row.verdict == "MORE_DATA"          # rien n'est prouvé → surtout pas PROMOTE


def test_net_bps_unmeasurable_si_gross_manque():
    row = S.assembler_ligne(
        "lead_lag",
        fees_bps=1.0, spread_bps=1.0, slippage_bps=1.0, latency_bps=1.0,
    )
    assert row.costs_bps == 4.0 and row.net_bps is None
    assert row.verdict == "MORE_DATA"


def test_verdict_promote_seulement_si_net_oos_forward_positifs_et_n_suffisant():
    row = S.assembler_ligne(
        "copy_vault",
        closed_pnls=[5.0, 3.0, -1.0, 4.0],
        n_independent=25,
        gross_edge_bps=20.0,
        fees_bps=1.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0,   # coûts=5 → net=15
        oos_net_bps=6.0, forward_net_bps=4.0,
    )
    assert row.net_bps == 15.0 and row.verdict == "PROMOTE"


def test_pas_de_promote_si_n_independant_insuffisant():
    row = S.assembler_ligne(
        "copy_vault",
        n_independent=5,                              # < N_INDEP_MIN_PROMOTE
        gross_edge_bps=20.0,
        fees_bps=1.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0,
        oos_net_bps=6.0, forward_net_bps=4.0,
    )
    assert row.net_bps == 15.0 and row.verdict == "MORE_DATA"


def test_verdict_kill_si_net_negatif_meme_sans_oos():
    row = S.assembler_ligne(
        "lead_lag",
        gross_edge_bps=3.0,
        fees_bps=2.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0,   # coûts=6 → net=-3
    )
    assert row.net_bps == -3.0 and row.verdict == "KILL"


def test_verdict_kill_si_oos_negatif_malgre_net_positif():
    row = S.assembler_ligne(
        "cross_venue_dislocation",
        n_independent=30,
        gross_edge_bps=20.0,
        fees_bps=1.0, spread_bps=2.0, slippage_bps=1.0, latency_bps=1.0,   # net=15
        oos_net_bps=-2.0, forward_net_bps=3.0,       # OOS négatif : overfit démasqué
    )
    assert row.net_bps == 15.0 and row.verdict == "KILL"


def test_roi_unmeasurable_sans_denominateur():
    row = S.assembler_ligne("copy_vault", closed_pnls=[10.0, -2.0])
    assert row.pnl_usd == 8.0 and row.roi is None and "roi" in row.unmeasured


def test_roi_calcule_avec_denominateur():
    row = S.assembler_ligne("copy_vault", closed_pnls=[10.0, -2.0], roi_denominator_usd=100.0)
    assert row.roi == 0.08


def test_fill_ratio_est_la_moyenne_mesuree():
    row = S.assembler_ligne("lead_lag", fill_ratios=[1.0, 0.5, 0.0])
    assert row.fill_ratio == 0.5


def test_to_dict_marque_paper_only_et_schema():
    d = S.assembler_ligne("copy_vault").to_dict()
    assert d["paper_only"] is True and d["real_execution"] is False
    assert d["schema_version"] == S.SCHEMA_VERSION
    assert isinstance(d["unmeasured"], list)


def test_tout_absent_reste_unmeasurable_et_more_data():
    row = S.assembler_ligne("copy_vault")
    # Aucune donnée : tout UNMEASURABLE, aucun faux verdict positif.
    assert row.net_bps is None and row.pnl_usd is None and row.roi is None
    assert row.verdict == "MORE_DATA"
    for champ in ("net_bps", "costs_bps", "pnl_usd", "roi", "gross_edge_bps"):
        assert champ in row.unmeasured
