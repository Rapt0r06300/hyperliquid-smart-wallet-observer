"""LE REFACTOR DE eval_trades NE DOIT RIEN CHANGER (2026-07-12).

CONTEXTE
--------
`eval_trades()` rendait une liste de PnL -- SANS le coin. Impossible de savoir si une
config etait portee par UN SEUL marche chanceux (le biais de selection, cf. H-181).

On a extrait le coeur dans `_eval_pairs()` qui rend (coin, pnl), et ajoute
`eval_trades_by_coin()` qui groupe. UN SEUL chemin de code -> les deux ne peuvent
pas diverger.

CE QUE CE TEST DEFEND
---------------------
L'INVARIANT : `eval_trades(...)` == tous les pnl de `eval_trades_by_coin(...)`, aplatis.
Si un jour quelqu'un modifie un filtre dans l'un sans l'autre, ce test tombe.

C'est le test le plus important du refactor : il prouve qu'on n'a RIEN casse.
Aucun reseau, aucun ordre : donnees synthetiques.
"""
from __future__ import annotations

from hl_observer.backtesting.scenario_search import eval_trades, eval_trades_by_coin


class _Sc:
    """Scenario minimal : les champs que eval_trades lit reellement."""

    name = "test"
    source = "test"
    sl_bps = 100.0
    tp_bps = 200.0
    trailing_stop_bps = 0.0
    trailing_activation_bps = 0.0
    breakeven_bps = 0.0
    horizon_min = 60.0
    cost_bps = 6.0
    min_edge_bps = 0.0
    side_mode = "both"


def _candidats():
    """3 coins, 6 candidats. Assez pour que le groupement par coin ait un sens."""
    out = []
    for i, coin in enumerate(["BTC", "BTC", "ETH", "ETH", "SOL", "SOL"]):
        out.append({
            "coin": coin,
            "direction": "LONG" if i % 2 == 0 else "SHORT",
            "current_mid": 100.0,
            "recorded_at": 1000.0 + i,
            "edge_remaining_bps": 50.0,
            "copy_degradation_bps": 0.0,
        })
    return out


def _marks():
    """Chemins de prix : BTC monte, ETH descend, SOL stagne.

    FORMAT CRITIQUE (bug commis le 2026-07-12, attrape par ce test) :
    `simulate_exit_on_path(path=...)` attend `list[tuple[float, float]]` -- des TUPLES
    (ts, mid), PAS des dicts. C'est ce que rend `marks_by_coin()`.

    Avec des dicts, `for (t, m) in path` deplie les CLES : t = "ts" (une chaine) ->
    `TypeError: '>' not supported between instances of 'str' and 'float'`.
    Un fixture au mauvais format ne teste rien : il fabrique une panne et l'attribue
    au code. Le format du fixture EST une hypothese, et il faut la verifier.
    """
    def chemin(depart, pas):
        return [(1000.0 + t, depart + pas * t) for t in range(0, 400, 10)]
    return {
        "BTC": chemin(100.0, 0.05),    # monte
        "ETH": chemin(100.0, -0.05),   # descend
        "SOL": chemin(100.0, 0.0),     # plat
    }


def test_les_deux_chemins_donnent_EXACTEMENT_les_memes_trades() -> None:
    """L'INVARIANT. Si ce test tombe, le refactor a change le comportement."""
    sc, cands, marks = _Sc(), _candidats(), _marks()

    plat = eval_trades(sc, cands, marks)
    par_coin = eval_trades_by_coin(sc, cands, marks)
    aplati = [pnl for pnls in par_coin.values() for pnl in pnls]

    assert sorted(plat) == sorted(aplati), (
        "REGRESSION : eval_trades() et eval_trades_by_coin() divergent. Ils partagent "
        "pourtant _eval_pairs() -- donc quelqu'un a duplique un filtre au lieu de le "
        "partager. Un seul chemin de code, ou ils finiront par mentir l'un sur l'autre."
    )
    assert len(plat) == len(aplati)


def test_le_groupement_par_coin_separe_bien_les_marches() -> None:
    """Le point de tout l'exercice : savoir QUEL marche a produit QUEL PnL."""
    par_coin = eval_trades_by_coin(_Sc(), _candidats(), _marks())

    assert set(par_coin) <= {"BTC", "ETH", "SOL"}
    assert par_coin, "au moins un coin doit avoir produit des trades"
    for coin, pnls in par_coin.items():
        assert all(isinstance(p, float) for p in pnls), f"{coin} doit rendre des floats"


def test_un_filtre_actif_s_applique_IDENTIQUEMENT_aux_deux_chemins() -> None:
    """Les 7 filtres d'entree ne doivent exister qu'a UN endroit."""

    class _ScFiltre(_Sc):
        min_edge_bps = 999.0  # aucun candidat n'a un edge de 999 bps -> tout doit etre refuse

    sc, cands, marks = _ScFiltre(), _candidats(), _marks()
    plat = eval_trades(sc, cands, marks)
    par_coin = eval_trades_by_coin(sc, cands, marks)

    assert plat == [], "le filtre d'edge doit tout refuser"
    assert par_coin == {}, (
        "le filtre d'edge doit AUSSI tout refuser dans le chemin par-coin. "
        "S'il ne le fait pas, les deux chemins ont des filtres differents -- "
        "et le minimax serait calcule sur des trades que eval_trades() aurait refuses."
    )
