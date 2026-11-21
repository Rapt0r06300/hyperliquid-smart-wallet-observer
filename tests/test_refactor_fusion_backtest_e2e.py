from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.backtesting.execution_delay_model import apply_execution_delay
from hl_observer.backtesting.wallet_following_simulator import simulate_wallet_following


def test_backtest_e2e_uses_delay_costs_fees_slippage_and_equity_curve() -> None:
    delayed = apply_execution_delay("e1", 1_000, delay_seconds=60)
    result = simulate_wallet_following(
        [
            {
                "event_id": delayed.event_id,
                "coin": "HYPE",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 101.2,
                "notional_usdt": 75.0,
            }
        ],
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    assert delayed.effective_ts_ms == 61_000
    assert len(result.trades) == 1
    assert result.trades[0].fee_usdt > 0
    assert len(result.equity_curve) == 2
    # Le capital n'est PAS ecrit ici. Le contrat est passe de 200 a 350 puis a 100 USD
    # (commit 2f0dab05b5d9 : « capital paper a 100 USD, d'une seule source ») et ce
    # fichier avait ete OUBLIE dans cette migration -- il epinglait encore 350.0, donc
    # il contredisait le contrat au lieu de le verifier. On compare desormais a la
    # constante unique, comme le fait deja tests/test_copy_vault_paper_profile.py.
    assert result.equity_curve[0] == PAPER_EQUITY_USD
    assert abs(result.net_pnl_usdt - (result.equity_curve[-1] - result.equity_curve[0])) < 1e-9


def test_backtest_e2e_can_report_negative_result_without_hiding_it() -> None:
    result = simulate_wallet_following(
        [
            {
                "event_id": "e2",
                "coin": "HYPE",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 99.0,
                "notional_usdt": 75.0,
            }
        ],
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    assert result.net_pnl_usdt < 0
    # MEME PIEGE, SENS INVERSE (21/11/2026). Ce test veut prouver qu une PERTE est
    # montree et non cachee : l equite finale doit passer SOUS le capital de depart.
    # Avec `< 350.0` fige alors que le contrat vaut 100 USD, l assertion etait VRAIE
    # quoi qu il arrive -- elle aurait laisse passer un gain. Un cas negatif change de
    # SENS quand la constante bouge : il faut comparer au capital, pas a un nombre.
    assert result.equity_curve[-1] < PAPER_EQUITY_USD
