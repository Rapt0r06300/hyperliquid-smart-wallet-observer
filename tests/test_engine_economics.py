"""L'ARITHMÉTIQUE AVANT LE SIGNAL (2026-07-11) — pistes 41-50.

Le test qui compte vraiment est le premier : ce module aurait-il vu venir le −64 $ ?

La config qui a perdu : take-profit raboté à **28 bps** par le facteur de volatilité, stop-loss
**126 bps**, coût aller-retour **13 bps**. Winrate d'équilibre : **90 %**. Aucune stratégie ne fait
90 %. **La perte était garantie avant le premier trade** — ce n'était pas de la malchance.

Les autres tests verrouillent l'honnêteté du verdict : ne pas crier au loup sur une config saine,
ne pas absoudre une config perdante, et ne jamais promettre un gain.

Aucun ordre réel.
"""
from __future__ import annotations

import pytest

from hl_observer.strategies.engine_economics import (
    EXIGEANT,
    IMPOSSIBLE,
    MAKER_BPS,
    TAKER_BPS,
    VIABLE,
    cout_aller_retour_bps,
    edge_minimum_requis_bps,
    evaluer_economie,
)


# ----------------------------------------------------- LE test : voir venir le −64 $

def test_it_would_have_caught_the_configuration_that_lost_64_dollars():
    """TP 28 (raboté par la vol), SL 126, coût 13. Il fallait 90 % de réussite pour ne rien gagner."""
    eco = evaluer_economie(take_profit_bps=28.0, stop_loss_bps=126.0, cout_bps=13.0)
    assert eco.winrate_equilibre == pytest.approx(139.0 / (139.0 + 15.0), rel=1e-3)
    assert eco.winrate_equilibre > 0.89
    assert eco.verdict == IMPOSSIBLE, (
        "cette configuration a réellement perdu 64 $ : elle DOIT être déclarée impossible"
    )


def test_the_corrected_configuration_is_no_longer_impossible():
    """Après correction (plancher TP 45, SL 60) : le mur tombe. Cela ne PROMET rien — cela rend
    seulement le gain arithmétiquement possible."""
    eco = evaluer_economie(take_profit_bps=110.0, stop_loss_bps=60.0, cout_bps=13.0)
    assert eco.verdict == VIABLE
    assert eco.winrate_equilibre < 0.50


# ----------------------------------------------------- le coût réel Hyperliquid

def test_a_taker_round_trip_costs_nine_bps():
    """Le chiffre du brief : 0,045 % × 2 = 9 bps, avant spread et slippage."""
    assert cout_aller_retour_bps() == pytest.approx(9.0)
    assert TAKER_BPS == 4.5


def test_the_maker_is_cheaper_but_never_free():
    """Le maker COÛTE 0,015 %. Le traiter comme un rebate était le bug déjà corrigé."""
    assert MAKER_BPS == 1.5
    maker = cout_aller_retour_bps(maker_entree=True, maker_sortie=True)
    assert maker == pytest.approx(3.0)
    assert 0.0 < maker < cout_aller_retour_bps()


def test_spread_and_slippage_are_not_forgotten():
    assert cout_aller_retour_bps(spread_bps=2.0, slippage_bps=1.5) == pytest.approx(12.5)


# ----------------------------------------------------- le verdict ne ment pas

def test_a_target_below_the_cost_is_impossible_whatever_the_signal():
    """LE CAS LE PLUS BRUTAL : viser 8 bps quand l'aller-retour en coûte 13.
    Un trade GAGNANT perd de l'argent. Aucun signal ne sauve ça."""
    eco = evaluer_economie(take_profit_bps=8.0, stop_loss_bps=50.0, cout_bps=13.0)
    assert eco.verdict == IMPOSSIBLE
    assert eco.winrate_equilibre is None, "il n'y a pas de winrate qui sauve une espérance négative"
    assert eco.gain_net_si_gagne_bps < 0
    assert "impossible" in eco.explication.lower()


def test_a_demanding_but_not_absurd_config_is_flagged_as_demanding():
    """Entre les deux : ni un mur, ni un feu vert. On le dit tel quel."""
    eco = evaluer_economie(take_profit_bps=40.0, stop_loss_bps=90.0, cout_bps=13.0)
    assert eco.verdict == EXIGEANT
    assert 0.65 <= eco.winrate_equilibre < 0.80


def test_a_healthy_config_is_not_cried_wolf_over():
    """Symétrie de l'honnêteté : on n'alarme pas sur une config saine."""
    eco = evaluer_economie(take_profit_bps=100.0, stop_loss_bps=50.0, cout_bps=9.0)
    assert eco.verdict == VIABLE


def test_the_verdict_never_promises_a_profit():
    """RÈGLE DURE (CLAUDE.md) : ne jamais promettre un PnL positif."""
    eco = evaluer_economie(take_profit_bps=100.0, stop_loss_bps=50.0, cout_bps=9.0)
    texte = eco.explication.lower()
    for promesse in ("gagnant", "rentable", "profitable", "assure", "garanti"):
        assert promesse not in texte, f"le verdict promet un gain : « {promesse} »"
    assert "ne promet" in texte or "pas exclu" in texte


# ----------------------------------------------------- le plancher d'edge

def test_the_minimum_edge_is_above_the_cost_not_equal_to_it():
    """Viser exactement le coût, c'est une espérance NULLE avant même la moindre erreur de mesure."""
    plancher = edge_minimum_requis_bps(cout_bps=13.0)
    assert plancher > 13.0
    assert plancher == pytest.approx(18.0)


def test_the_cost_floor_matches_the_configured_min_edge():
    """Cohérence avec le launcher : le plancher d'edge (16 bps) doit rester ≥ au coût maker
    aller-retour + marge. Si le coût dépassait le plancher, le gate serait un leurre."""
    cout_maker = cout_aller_retour_bps(maker_entree=True, maker_sortie=True, spread_bps=2.0)
    assert edge_minimum_requis_bps(cout_bps=cout_maker) <= 16.0


# ----------------------------------------------------- robustesse

def test_garbage_never_crashes_the_verdict():
    for tp, sl, c in ((0, 0, 0), (-5, -5, -5), (0, 100, 13), (100, 0, 0)):
        eco = evaluer_economie(take_profit_bps=tp, stop_loss_bps=sl, cout_bps=c)
        assert eco.verdict in {VIABLE, EXIGEANT, IMPOSSIBLE}
        assert isinstance(eco.as_dict(), dict)


# ----------------------------------------------------- LE VRAI LAUNCHER, PAS UNE FIXTURE

def _config_launcher() -> dict[str, float]:
    """Lit la CONFIG RÉELLE (le .ps1 est l'autorité). Une fixture ne protège de rien."""
    import re
    from pathlib import Path

    ps1 = Path(__file__).resolve().parents[1] / "tools" / "start_hypersmart_simulation.ps1"
    texte = ps1.read_text(encoding="utf-8", errors="ignore")

    def env(nom: str, defaut: float) -> float:
        m = re.search(rf'"{nom}",\s*"([^"]+)"', texte)
        try:
            return float(m.group(1)) if m else defaut
        except (TypeError, ValueError):
            return defaut

    return {
        "tp": env("HYPERSMART_SLTP_TAKE_PROFIT_BPS", 110.0),
        "sl": env("HYPERSMART_SLTP_STOP_LOSS_BPS", 60.0),
        "vol_min": env("HYPERSMART_V26_VOL_FACTOR_MIN", 0.8),
        "vol_max": env("HYPERSMART_V26_VOL_FACTOR_MAX", 1.5),
        "tp_floor": env("HYPERSMART_V26_TP_FLOOR_BPS", 45.0),
    }


def test_the_live_configuration_is_not_a_wall():
    """GARDE-FOU DE NON-RÉGRESSION. Si un futur réglage réintroduit un mur arithmétique,
    ce test tombe AVANT que le bot ne perde de l'argent en le découvrant tout seul."""
    c = _config_launcher()
    cout = cout_aller_retour_bps(spread_bps=2.0, slippage_bps=2.0)   # 13 bps, le coût mesuré
    eco = evaluer_economie(take_profit_bps=c["tp"], stop_loss_bps=c["sl"], cout_bps=cout)
    assert eco.verdict != IMPOSSIBLE, (
        f"la config du launcher est arithmétiquement perdante : {eco.explication}"
    )
    assert eco.winrate_equilibre is not None and eco.winrate_equilibre < 0.65


def test_the_worst_case_volatility_does_not_rebuild_the_wall():
    """C'EST ICI QUE LE BUG S'ÉTAIT CACHÉ. Le facteur de volatilité rabotait le TP à 28 bps —
    la config nominale était saine, la config RÉELLEMENT APPLIQUÉE ne l'était pas.
    On juge donc le pire cas, pas l'affichage."""
    c = _config_launcher()
    cout = cout_aller_retour_bps(spread_bps=2.0, slippage_bps=2.0)

    tp_pire = max(c["tp"] * c["vol_min"], c["tp_floor"])       # le plancher doit tenir
    sl_pire = c["sl"] * c["vol_max"]                           # et le stop peut s'élargir

    eco = evaluer_economie(take_profit_bps=tp_pire, stop_loss_bps=sl_pire, cout_bps=cout)
    assert eco.verdict != IMPOSSIBLE, (
        f"sous volatilité, la config redevient un mur (TP={tp_pire:.0f}, SL={sl_pire:.0f}) : "
        f"{eco.explication}"
    )


def test_the_tp_floor_actually_protects_the_target():
    """Le plancher de TP doit rester AU-DESSUS du coût — sinon il ne protège rien."""
    c = _config_launcher()
    cout = cout_aller_retour_bps(spread_bps=2.0, slippage_bps=2.0)
    assert c["tp_floor"] > cout * 2.0, (
        f"le plancher de TP ({c['tp_floor']:.0f} bps) est trop proche du coût ({cout:.0f} bps) : "
        f"un trade gagnant ne rapporterait presque rien"
    )
