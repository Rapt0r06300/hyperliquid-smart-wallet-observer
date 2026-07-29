"""Garde-fous issus de l'AUTOPSIE DU PnL (2026-07-11).

Le run du 09-10 juillet a perdu 64,02 $ (ROI -6,4 %). L'autopsie comptable montre que la perte
n'avait RIEN a voir avec la qualite du signal : elle etait garantie par la STRUCTURE DES SORTIES.

  facteur de volatilite median mesure : 0,71
  -> TP effectif : 40 x 0,71 = 28 bps, dont 13 bps de frais  => 15 bps de gain reel
  -> SL effectif : 126 x 0,71 = 90 bps, plus 13 bps de frais => 103 bps de perte
  => ratio 1 : 6,65  =>  il fallait 87 % de winrate pour rentrer dans ses frais. On en fait 50.

Trois defauts, tous corriges ici :
  1. aucun PLANCHER DE TP : la volatilite rabotait le take-profit sous le niveau des frais ;
  2. le STOP CATASTROPHIQUE ne fermait RIEN (il ne servait qu'a contourner le delai minimum) ;
     les 2 trades concernes (ARB -323 bps, ZEC -321 bps) pesent 46 % de toute la perte ;
  3. le facteur de volatilite montait jusqu'a x2,5 -> SL a 315 bps sur un notionnel de 500 $.

Simulation paper uniquement. Aucun ordre reel.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp
from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits
from hl_observer.paper_trading.vol_adjusted_barriers import adjust_config

PS1 = Path("tools/start_hypersmart_simulation.ps1")
FRAIS_ALLER_RETOUR_BPS = 13.0     # mesure sur le ledger reel (entree 1 bps + sortie 12 bps)


def _env() -> dict[str, str]:
    text = PS1.read_text(encoding="utf-8", errors="ignore")
    out: dict[str, str] = {}
    for pat in (r'Set-HyperSmartDefaultEnv\s+"([A-Z0-9_]+)"\s+"([^"]*)"',
                r'\[Environment\]::SetEnvironmentVariable\("([A-Z0-9_]+)",\s*"([^"]*)",\s*"Process"\)'):
        for k, v in re.findall(pat, text):
            out[k] = v
    return out


def _f(name: str, default: float) -> float:
    try:
        return float(_env().get(name, default))
    except (TypeError, ValueError):
        return float(default)


# ---------------------------------------------------------------- 1. plancher de TP

def test_volatility_can_never_shave_the_take_profit_below_the_fees():
    """LE BUG CENTRAL : un TP rabote sous les frais transforme chaque gain en quasi-neant."""
    tp_floor = _f("HYPERSMART_V26_TP_FLOOR_BPS", 0.0)
    assert tp_floor >= 3 * FRAIS_ALLER_RETOUR_BPS, (
        f"PLANCHER DE TP TROP BAS : {tp_floor} bps pour {FRAIS_ALLER_RETOUR_BPS} bps de frais. "
        f"Un take-profit doit valoir au moins 3x les frais, sinon ils mangent le gain."
    )
    base = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0)
    # meme au facteur de volatilite le plus bas, le TP tient le plancher
    cfg = adjust_config(base, 0.1, sl_floor_bps=12.0, tp_floor_bps=tp_floor)
    assert cfg.take_profit_bps >= tp_floor
    assert cfg.take_profit_bps - FRAIS_ALLER_RETOUR_BPS > 0, "le TP doit laisser un gain NET positif"


def test_the_exact_configuration_that_lost_the_money_is_now_impossible():
    """Reproduction du run reel : TP 40 x 0,71 = 28 bps. Le plancher doit l'interdire."""
    tp_floor = _f("HYPERSMART_V26_TP_FLOOR_BPS", 0.0)
    ancien = adjust_config(SLTPConfig(take_profit_bps=40.0, stop_loss_bps=126.0), 0.71,
                           sl_floor_bps=12.0, tp_floor_bps=0.0)
    assert ancien.take_profit_bps == pytest.approx(28.4, abs=0.1)   # ce qui a vraiment tourne
    nouveau = adjust_config(SLTPConfig(take_profit_bps=40.0, stop_loss_bps=126.0), 0.71,
                            sl_floor_bps=12.0, tp_floor_bps=tp_floor)
    assert nouveau.take_profit_bps >= tp_floor > ancien.take_profit_bps


# ---------------------------------------------------------------- 2. ratio net apres frais

def test_the_net_ratio_after_fees_is_not_a_losing_machine():
    """Le ratio doit se juger APRES frais, au facteur de volatilite le PLUS DEFAVORABLE."""
    env = _env()
    tp = _f("HYPERSMART_SLTP_TAKE_PROFIT_BPS", 0.0)
    sl = _f("HYPERSMART_SLTP_STOP_LOSS_BPS", 0.0)
    f_min = _f("HYPERSMART_V26_VOL_FACTOR_MIN", 1.0)
    tp_floor = _f("HYPERSMART_V26_TP_FLOOR_BPS", 0.0)
    assert tp > 0 and sl > 0

    tp_eff = max(tp * f_min, tp_floor)
    sl_eff = sl * f_min
    gain = tp_eff - FRAIS_ALLER_RETOUR_BPS
    perte = sl_eff + FRAIS_ALLER_RETOUR_BPS
    assert gain > 0, f"un gain NET de {gain:.1f} bps : les frais mangent tout le take-profit"

    breakeven = perte / (perte + gain)
    assert breakeven <= 0.50, (
        f"STRUCTURE PERDANTE : TP {tp_eff:.0f} / SL {sl_eff:.0f} bps apres frais -> il faut "
        f"{breakeven * 100:.1f} % de winrate pour seulement rentrer dans ses frais. "
        f"Le run mesure en exigeait 86,9 % et en realisait 50 : la perte etait certaine."
    )


def test_volatility_factor_cannot_blow_the_stop_loss_up():
    """Au facteur 2,5, le SL montait a 315 bps. Ces 2 trades ont fait 46 % de la perte."""
    f_max = _f("HYPERSMART_V26_VOL_FACTOR_MAX", 2.5)
    sl = _f("HYPERSMART_SLTP_STOP_LOSS_BPS", 126.0)
    cata = _f("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", 1e9)
    sl_pire = sl * f_max
    assert sl_pire <= 150.0, (
        f"SL MAXIMUM {sl_pire:.0f} bps (= {sl:.0f} x {f_max}) : sur un notionnel de 500 $ c'est "
        f"{sl_pire / 10000 * 500:.2f} $ de perte, soit {sl_pire / 10000 * 500 / 50 * 100:.0f} % "
        f"de la marge, sur UN seul trade."
    )
    assert cata <= sl_pire + 30, (
        f"Le stop catastrophique ({cata:.0f} bps) doit rester un vrai plafond, proche du pire SL "
        f"({sl_pire:.0f} bps) -- sinon il ne protege de rien."
    )


# ---------------------------------------------------------------- 3. le stop catastrophique FERME

def _position(entry: float, size: float, coin: str = "ARB"):
    return {
        f"0xw|{coin}|SHORT": {
            "coin": coin, "direction": "SHORT", "side": "SHORT",
            "size": -abs(size), "avg_price": entry, "opened_at_ms": 0,
            "wallet_address": "0xw", "entry_costs": 0.0,
        }
    }


def test_catastrophic_stop_actually_closes_the_position(monkeypatch):
    """LE BUG : il ne fermait RIEN. La perte d'ARB a couru jusqu'a -323 bps."""
    monkeypatch.setenv("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", "110")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "45000")

    # SL volontairement enorme (comme quand la volatilite le gonflait) : seul le CATA peut sauver
    cfg = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=315.0)
    positions = _position(entry=100.0, size=5.0)
    ledger: list[dict] = []
    # SHORT : le prix MONTE de 200 bps -> perte de 200 bps, sous le SL (315) mais au-dela du CATA (130)
    closed = apply_sltp_exits(positions, ledger, {"ARB": 102.0}, now_ms=1_000, config=cfg)

    assert closed, "le stop catastrophique n'a PAS ferme la position -> la perte court sans limite"
    assert closed[0]["reason"] == "CATASTROPHIC_STOP"
    assert ledger and ledger[0]["exit_method"] == "SLTP_CATASTROPHIC_STOP"
    assert float(ledger[0]["sltp_pnl_bps"]) <= -110.0
    assert not positions, "la position doit etre retiree du book"


def test_catastrophic_stop_ignores_the_minimum_hold_delay(monkeypatch):
    """Un delai minimum de detention ne doit JAMAIS retenir une perte catastrophique."""
    monkeypatch.setenv("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", "110")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "45000")
    cfg = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=315.0)
    positions = _position(entry=100.0, size=5.0)
    ledger: list[dict] = []
    # position agee de 1 seconde seulement (bien sous le delai de 45 s)
    closed = apply_sltp_exits(positions, ledger, {"ARB": 103.0}, now_ms=1_000, config=cfg)
    assert closed and closed[0]["reason"] == "CATASTROPHIC_STOP"


def test_a_normal_loss_is_not_closed_by_the_catastrophic_stop(monkeypatch):
    """Le CATA est un filet de securite, pas un stop ordinaire : il ne doit pas se declencher tot."""
    monkeypatch.setenv("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", "110")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    cfg = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=315.0)
    positions = _position(entry=100.0, size=5.0)
    ledger: list[dict] = []
    closed = apply_sltp_exits(positions, ledger, {"ARB": 100.5}, now_ms=1_000, config=cfg)  # -50 bps
    assert not closed and positions, "une perte de 50 bps ne doit pas declencher le filet a 110 bps"


def test_take_profit_still_works(monkeypatch):
    """Non-regression : la sortie en gain doit continuer de fonctionner normalement."""
    monkeypatch.setenv("HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS", "110")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    cfg = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0)
    positions = _position(entry=100.0, size=5.0)
    ledger: list[dict] = []
    closed = apply_sltp_exits(positions, ledger, {"ARB": 98.8}, now_ms=1_000, config=cfg)  # SHORT +120 bps
    assert closed and closed[0]["reason"] == "TAKE_PROFIT"
    assert ledger and float(ledger[0]["sltp_pnl_bps"]) >= 110.0


def test_evaluate_sl_tp_is_untouched():
    """Le moteur pur de decision ne doit pas avoir bouge (le CATA vit dans le runtime)."""
    cfg = SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0)
    d = evaluate_sl_tp(side="SHORT", entry_price=100.0, current_price=98.8, config=cfg)  # +120 bps
    assert d.exit and d.reason == "TAKE_PROFIT"


# ======================================================================================
#  COUTS MANQUANTS (2e vague d'autopsie, 2026-07-11)
# ======================================================================================

def test_a_position_cannot_stay_open_forever(monkeypatch):
    """INCOHERENCE : le bot DECIDE sur quelques minutes et TENAIT ses positions jusqu'a 8,4 h.

    L'edge du signal de copie est mesure NUL des 5 minutes. Au-dela, ce n'est plus une position
    de copie : c'est une exposition nue au marche. Rejeu des 20 trades reels : sans timeout
    -39 $, avec un timeout de 30 min -23 $. (cela ne CREE pas d'edge : cela cesse d'exposer le
    capital a un actif qui n'en a pas.)
    """
    monkeypatch.setenv("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000")   # 30 min
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    t0 = 1_000_000_000
    positions = {
        "0xw|SOL|LONG": {"coin": "SOL", "direction": "LONG", "side": "LONG", "size": 5.0,
                         "avg_price": 100.0, "entry_costs": 0.0,
                         "fee_already_embedded_in_entry_price": False,
                         "opened_at_ms": t0, "wallet_address": "0xw"}
    }
    ledger: list[dict] = []
    # 8,4 h plus tard, prix INCHANGE : ni TP ni SL ne se declenchent -> avant, la position dormait
    apply_sltp_exits(positions, ledger, {"SOL": 100.0}, now_ms=t0 + int(8.4 * 3600 * 1000),
                     config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0))
    assert ledger and ledger[0]["exit_method"] == "SLTP_TIMEOUT", (
        "une position a prix inchange reste ouverte indefiniment : le bot n'a aucun timeout"
    )
    assert not positions


def test_a_short_position_is_not_closed_before_the_timeout(monkeypatch):
    """Le timeout ne doit pas fermer prematurement (sinon il devient un stop deguise)."""
    monkeypatch.setenv("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    t0 = 1_000_000_000
    positions = {
        "0xw|SOL|LONG": {"coin": "SOL", "direction": "LONG", "side": "LONG", "size": 5.0,
                         "avg_price": 100.0, "opened_at_ms": t0, "wallet_address": "0xw"}
    }
    ledger: list[dict] = []
    apply_sltp_exits(positions, ledger, {"SOL": 100.0}, now_ms=t0 + 60_000,   # 1 minute
                     config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0))
    assert not ledger and positions, "le timeout a ferme apres 1 minute alors qu'il est regle a 30"


def test_funding_is_charged_to_long_positions(monkeypatch):
    """LE FUNDING N'ETAIT JAMAIS FACTURE : 42,6 h de positions cumulees, zero centime deduit.

    Sur Hyperliquid le financement se paie CHAQUE HEURE. Un LONG paie quand le taux est positif.
    """
    from hl_observer.funding.funding_runtime_cache import clear, push

    monkeypatch.setenv("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    clear()
    push("SOL", 0.0001)                       # +1 bps par heure
    t0 = 1_000_000_000
    positions = {
        "0xw|SOL|LONG": {"coin": "SOL", "direction": "LONG", "side": "LONG", "size": 5.0,
                         "avg_price": 100.0, "entry_costs": 0.0,
                         "fee_already_embedded_in_entry_price": False,
                         "opened_at_ms": t0, "wallet_address": "0xw"}
    }
    ledger: list[dict] = []
    apply_sltp_exits(positions, ledger, {"SOL": 100.0}, now_ms=t0 + int(8.4 * 3600 * 1000),
                     config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0))
    e = ledger[0]
    assert e["funding_cost_usdc"] is not None, "le funding n'est pas facture"
    assert e["funding_cost_usdc"] > 0, "un LONG doit PAYER un funding positif"
    assert e["funding_hours"] == pytest.approx(8.4, abs=0.01)
    # prix inchange : le PnL net doit etre exactement -(frais + funding)
    attendu = -(float(e["fee_cost_usdc"]) + float(e["funding_cost_usdc"]))
    assert float(e["estimated_net_pnl_usdc"]) == pytest.approx(attendu, abs=1e-6)
    clear()


def test_funding_is_received_by_short_positions(monkeypatch):
    """Symetrie : un SHORT RECOIT le funding quand le taux est positif."""
    from hl_observer.funding.funding_runtime_cache import clear, push

    monkeypatch.setenv("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    clear()
    push("SOL", 0.0001)
    t0 = 1_000_000_000
    positions = {
        "0xw|SOL|SHORT": {"coin": "SOL", "direction": "SHORT", "side": "SHORT", "size": -5.0,
                          "avg_price": 100.0, "opened_at_ms": t0, "wallet_address": "0xw"}
    }
    ledger: list[dict] = []
    apply_sltp_exits(positions, ledger, {"SOL": 100.0}, now_ms=t0 + int(4 * 3600 * 1000),
                     config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0))
    assert ledger[0]["funding_cost_usdc"] < 0, "un SHORT doit RECEVOIR un funding positif"
    clear()


def test_no_funding_data_means_no_invented_number(monkeypatch):
    """Sans donnee de funding : on ne facture RIEN et on le DIT. Jamais de chiffre invente."""
    from hl_observer.funding.funding_runtime_cache import clear

    monkeypatch.setenv("HYPERSMART_SLTP_POSITION_TIMEOUT_MS", "1800000")
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_MIN_HOLD_MS", "0")
    clear()                                   # AUCUNE donnee de funding
    t0 = 1_000_000_000
    positions = {
        "0xw|ZZZ|LONG": {"coin": "ZZZ", "direction": "LONG", "side": "LONG", "size": 5.0,
                         "avg_price": 100.0, "opened_at_ms": t0, "wallet_address": "0xw"}
    }
    ledger: list[dict] = []
    apply_sltp_exits(positions, ledger, {"ZZZ": 100.0}, now_ms=t0 + int(4 * 3600 * 1000),
                     config=SLTPConfig(take_profit_bps=110.0, stop_loss_bps=60.0))
    assert ledger[0]["funding_cost_usdc"] is None, (
        "sans donnee de funding, le champ doit valoir None -- pas 0.0, qui serait une affirmation"
    )
