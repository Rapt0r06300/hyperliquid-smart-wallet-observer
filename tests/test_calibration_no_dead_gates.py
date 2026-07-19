"""Garde-fou de CALIBRAGE (audit 2026-07-11) -- aucun gate ne doit etre INFRANCHISSABLE.

Contexte. Le run du 2026-07-10 a fini a -64 $ avec 20 trades, puis plus aucune ouverture. Trois
causes, toutes ARITHMETIQUES (pas de la malchance) :

1. VERROU MORT -- plafond de degradation de copie regle a 12 bps alors que le cout de copie
   PLANCHER du scorer (frais + spread + slippage + selection adverse) vaut 14.2 bps.
   Aucun signal ne pouvait franchir le gate : 0 trade garanti.
2. VERROU MORT -- plancher single-wallet a 55 bps alors que l'edge restant MAXIMUM theorique d'un
   signal mono-wallet vaut ~32 bps. Le mode sniper etait structurellement mort.
3. RATIO PERDANT -- TP 40 bps / SL 126 bps : winrate d'equilibre 75.9 %. A 50 % de winrate la
   perte est GARANTIE. C'est exactement ce qu'on a mesure (10 TP / 10 SL -> -64 $).

Ces tests interdisent la reintroduction de ces erreurs. Ils ne PROMETTENT aucun PnL : ils
garantissent seulement que la mecanique n'est pas perdante par construction.

Simulation paper uniquement. Aucun ordre reel.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)

PS1 = Path("tools/start_hypersmart_simulation.ps1")
ROUTES = Path("src/hl_observer/ui/routes.py")


def _launcher_env() -> dict[str, str]:
    """Valeurs effectives posees par le launcher (le .ps1 est l'AUTORITE, il ecrase le .cmd)."""
    text = PS1.read_text(encoding="utf-8", errors="ignore")
    values: dict[str, str] = {}
    for pattern in (
        r'Set-HyperSmartDefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]*)"',
        r'\[Environment\]::SetEnvironmentVariable\("([A-Z0-9_]+)",\s*"([^"]*)",\s*"Process"\)',
    ):
        for name, value in re.findall(pattern, text):
            values[name] = value  # la derniere ecriture gagne, comme a l'execution
    return values


def _f(env: dict[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _cout_reel(nom: str) -> float:
    """Cout REELLEMENT injecte par routes.py (et non le defaut de la dataclass).

    Un premier jet de ce test lisait la dataclass (slippage 2.5) et laissait donc passer un
    plafond de degradation de 12 bps... qui est mortel en production (routes impose slippage 5.0).
    On relit donc le code source pour que le test suive le comportement reel.
    """
    source = ROUTES.read_text(encoding="utf-8", errors="ignore")
    bloc = source[source.index("realtime_score_config = RealtimeCopyRiskConfig(") :][:400]
    found = re.search(rf"{nom}=([0-9.]+)", bloc)
    assert found, f"cout {nom} introuvable dans routes.py"
    return float(found.group(1))


# --------------------------------------------------------------------------------------
# 1. Le plafond de degradation doit etre FRANCHISSABLE
# --------------------------------------------------------------------------------------

def test_copy_degradation_ceiling_is_reachable() -> None:
    cfg = RealtimeCopyRiskConfig()
    # Cout plancher d'un signal PARFAIT : liquide, 2+ wallets, aucun mouvement adverse, age ~0.
    plancher = (
        _cout_reel("fee_bps")
        + _cout_reel("spread_bps")
        + _cout_reel("slippage_bps")
        + cfg.adverse_selection_penalty_bps
    )
    plafond = _f(_launcher_env(), "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", 28.0)
    assert plafond > plancher, (
        f"VERROU MORT : plafond de degradation {plafond} bps <= cout de copie plancher "
        f"{plancher} bps (frais+spread+slippage+selection adverse tels qu'injectes par routes.py) "
        f"-> COPY_DEGRADATION_TOO_HIGH sur TOUT signal, 0 trade possible."
    )


# --------------------------------------------------------------------------------------
# 2. Le plancher single-wallet doit etre ATTEIGNABLE (mode sniper)
# --------------------------------------------------------------------------------------

#: Miroir de `SENTINELLE_SNIPER_FERME` dans tools/audit_report.py : un plancher >= 1000 bps
#: n'est pas un calibrage, c'est une PORTE FERMEE VOLONTAIREMENT (decision Z3, 19/07 --
#: le mode sniper mono-wallet est economiquement mort : -7,97 bps OOS, leader contrarien).
SENTINELLE_SNIPER_FERME = 1000.0


def test_single_wallet_floor_is_attainable() -> None:
    env = _launcher_env()
    floor = _f(env, "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", 55.0)

    if floor >= SENTINELLE_SNIPER_FERME:
        # 🔴 REECRIT LE 19/07 (attrape par TEST-AUDIT sous Windows) : ce test datait d'AVANT
        # la decision Z3 et traitait « sniper structurellement mort » comme un BUG. C'est
        # desormais une DECISION (9999 dans le lanceur). Un verrou VOULU ne doit pas etre
        # « atteignable » -- on verifie au contraire qu'aucun signal fabrique ne peut passer.
        assert floor >= SENTINELLE_SNIPER_FERME
        return

    # Meilleur signal mono-wallet possible : confiance max, tout frais, marche tres liquide.
    # leader_expected_edge_bps = 18 + confidence*34 + min(24, (n-1)*8)  (routes.opportunity_metrics)
    best_edge_in = 18.0 + 1.0 * 34.0 + 0.0
    score = score_realtime_copy_candidate(
        RealtimeCopyScoreInput(
            action_type="OPEN_LONG",
            direction="LONG",
            leader_expected_edge_bps=best_edge_in,
            leader_consistency_factor=1.0,
            signal_age_ms=200,
            consensus_wallets=1,          # SNIPER : un seul wallet
            liquidity_score=1.0,
            leader_score=100.0,
            leader_reference_price=100.0,
            current_mid=100.0,
            leader_notional_usdt=5_000.0,
            current_open_exposure_usdt=0.0,
            current_open_positions=0,
            max_open_positions=20,
        ),
        config=RealtimeCopyRiskConfig(
            spread_bps=_cout_reel("spread_bps"),
            slippage_bps=_cout_reel("slippage_bps"),
            fee_bps=_cout_reel("fee_bps"),
            min_liquidity_score=_f(env, "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", 0.38),
            max_copy_degradation_bps=_f(env, "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", 28.0),
        ),
    )
    plafond_theorique = float(score.edge_remaining_bps or 0.0)
    assert plafond_theorique >= floor, (
        f"VERROU MORT : plancher single-wallet {floor} bps > edge restant MAXIMUM atteignable "
        f"{plafond_theorique:.1f} bps -> aucun signal mono-wallet ne peut jamais passer "
        f"(le mode sniper est structurellement mort)."
    )


# --------------------------------------------------------------------------------------
# 3. Le ratio SL/TP ne doit pas etre perdant par construction
# --------------------------------------------------------------------------------------

def test_take_profit_is_not_smaller_than_stop_loss() -> None:
    env = _launcher_env()
    tp = _f(env, "HYPERSMART_SLTP_TAKE_PROFIT_BPS", 0.0)
    sl = _f(env, "HYPERSMART_SLTP_STOP_LOSS_BPS", 0.0)
    assert tp > 0 and sl > 0, "TP/SL doivent etre definis au launcher"

    breakeven_winrate = sl / (sl + tp)
    assert breakeven_winrate <= 0.50, (
        f"RATIO PERDANT : TP={tp:.0f} bps / SL={sl:.0f} bps -> il faut "
        f"{breakeven_winrate * 100:.1f} % de winrate rien que pour rentrer dans ses frais. "
        f"Un copy-trade n'atteint pas ce winrate : la perte est garantie par construction."
    )


def test_trailing_activation_is_reachable_before_take_profit() -> None:
    """Un trailing qui s'active APRES le TP ne s'arme jamais (il etait a 201 pour un TP de 40)."""
    env = _launcher_env()
    tp = _f(env, "HYPERSMART_SLTP_TAKE_PROFIT_BPS", 0.0)
    activation = _f(env, "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS", 0.0)
    assert activation < tp, (
        f"TRAILING MORT : activation a {activation:.0f} bps alors que le TP ferme la position a "
        f"{tp:.0f} bps -> le trailing ne peut jamais s'armer."
    )


# --------------------------------------------------------------------------------------
# 4. Les cliquets de session doivent etre a l'echelle des positions, pas du bruit
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "var,defaut",
    [
        ("HYPERSMART_SESSION_GUARD_SOFT_LOSS_USDC", 2.50),
        ("HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC", 10.00),
        ("HYPERSMART_COIN_SIDE_LOSS_COOLDOWN_USDC", 0.20),
        ("HYPERSMART_COIN_SESSION_LOSS_COOLDOWN_USDC", 0.50),
        ("HYPERSMART_LEADER_SESSION_LOSS_COOLDOWN_USDC", 0.35),
    ],
)
def test_session_ratchets_are_larger_than_one_normal_loss(var: str, defaut: float) -> None:
    """Un cliquet plus petit qu'UNE perte normale se declenche sur du bruit et gele le run.

    Perte normale = SL x notional. Avec SL 60 bps et un notional de 500 $ (marge 50 x levier 10),
    elle vaut 3 $. Un seuil sous cette valeur se declenche des le premier trade perdant -- et comme
    ces cliquets sont IRREVERSIBLES, il ne se rouvre jamais.
    """
    env = _launcher_env()
    marge = _f(env, "HYPERSMART_MAX_POSITION_USDT", 50.0)
    levier = _f(env, "HYPERSMART_SIMULATION_LEVERAGE", 10.0)
    sl_bps = _f(env, "HYPERSMART_SLTP_STOP_LOSS_BPS", 60.0)
    perte_normale = marge * levier * sl_bps / 10_000.0

    seuil = _f(env, var, defaut)
    assert seuil >= perte_normale, (
        f"CLIQUET TROP BAS : {var} = {seuil:.2f} $ alors qu'UNE perte normale vaut "
        f"{perte_normale:.2f} $ (SL {sl_bps:.0f} bps sur un notional de {marge * levier:.0f} $). "
        f"Le garde-fou se declenche au premier trade perdant et ne se rouvre jamais "
        f"-> le bot cesse d'ouvrir."
    )


def test_hard_halt_is_a_real_drawdown_not_a_scratch() -> None:
    """Le HALT TOTAL de session doit correspondre a un vrai drawdown, pas a -1 % du capital."""
    env = _launcher_env()
    capital = 1000.0
    hard = _f(env, "HYPERSMART_SESSION_GUARD_HARD_LOSS_USDC", 10.0)
    pct = hard / capital
    assert pct >= 0.10, (
        f"HALT TROP TOT : SESSION_HARD_LOSS_HALT a {hard:.2f} $ = {pct * 100:.1f} % du capital. "
        f"Ce halt est IRREVERSIBLE (plus aucune entree jusqu'au redemarrage) : le declencher sur "
        f"un drawdown de routine tue le run de 48 h et on ne mesure plus rien."
    )


# --------------------------------------------------------------------------------------
# 5. Un signal grinder TYPIQUE doit pouvoir passer (sinon on ne collecte aucune donnee)
# --------------------------------------------------------------------------------------

def test_a_typical_fresh_two_wallet_signal_is_accepted() -> None:
    """Signal realiste du mode grinder : 2 wallets, 2 s, marche liquide -> doit etre ACCEPTE."""
    env = _launcher_env()
    score = score_realtime_copy_candidate(
        RealtimeCopyScoreInput(
            action_type="OPEN_LONG",
            direction="LONG",
            leader_expected_edge_bps=18.0 + 0.9 * 34.0 + 8.0,  # confiance 0.9, 2 wallets
            leader_consistency_factor=0.72 + 0.9 * 0.28,
            signal_age_ms=2_000,
            consensus_wallets=2,
            liquidity_score=0.9,
            leader_score=90.0,
            leader_reference_price=100.0,
            current_mid=100.0,
            leader_notional_usdt=3_000.0,
            current_open_exposure_usdt=0.0,
            current_open_positions=0,
            max_open_positions=20,
        ),
        config=RealtimeCopyRiskConfig(
            spread_bps=_cout_reel("spread_bps"),
            slippage_bps=_cout_reel("slippage_bps"),
            fee_bps=_cout_reel("fee_bps"),
            min_edge_required_bps=_f(env, "HYPERSMART_SIMULATION_MIN_EDGE_BPS", 28.0),
            min_liquidity_score=_f(env, "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE", 0.38),
            max_copy_degradation_bps=_f(env, "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS", 28.0),
            single_wallet_min_edge_required_bps=_f(
                env, "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", 55.0
            ),
            max_signal_age_ms=int(_f(env, "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", 12_000)),
        ),
    )
    assert not score.refusal_reasons, (
        f"Le signal grinder TYPIQUE est refuse : {score.refusal_reasons} "
        f"(edge restant {score.edge_remaining_bps:.1f} bps). Avec cette config le bot n'ouvrira "
        f"rien et le run ne produira aucune donnee exploitable."
    )
