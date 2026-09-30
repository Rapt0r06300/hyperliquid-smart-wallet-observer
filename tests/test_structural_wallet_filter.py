"""G5 — exclure les wallets structurels (infra/vault, PnL structurel) de la sélection de leaders."""
from __future__ import annotations

from hl_observer.copy_wallet.structural_wallet_filter import est_structurel, filtrer_leaders


def _w(adr, winrate, pnl, n):
    return {"adresse": adr, "winrate": winrate, "pnl_total_usd": pnl, "n_trades": n}


def test_wallet_dans_exclusions():
    assert est_structurel(_w("0xVAULT", 0.6, 5000.0, 100), exclusions={"0xVAULT"}) is True


def test_winrate_parfait_pnl_nul_est_structurel():
    # 100% winrate mais 20$ sur 200 trades = 0.1$/trade -> structurel (NegRisk-like)
    assert est_structurel(_w("0xINFRA", 1.0, 20.0, 200)) is True


def test_vrai_trader_est_garde():
    assert est_structurel(_w("0xPRO", 0.58, 50_000.0, 300)) is False   # winrate normal, vrai PnL


def test_filtrer_garde_les_vrais():
    stats = [_w("0xPRO", 0.58, 50_000.0, 300), _w("0xINFRA", 1.0, 10.0, 500),
             _w("0xVAULT", 0.5, 0.0, 100)]
    gardes = filtrer_leaders(stats, exclusions={"0xVAULT"})
    assert gardes == ["0xPRO"]


def test_zero_trades_pas_juge_structurel():
    assert est_structurel(_w("0xNEW", 1.0, 0.0, 0)) is False   # pas d'historique -> pas d'affirmation
