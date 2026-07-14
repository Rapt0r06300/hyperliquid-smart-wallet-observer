"""LE BIAIS DE SELECTION NE DOIT PAS REVENIR (2026-07-12).

LE BUG TROUVE DANS LE CODE
--------------------------
    scored.sort(key=net_total_usd sur TRAIN, reverse=True)
    for sc in scored[:top_k]:          # <-- SEULS les 40 champions du train vont au TEST
        ... evaluer sur TEST ...

Sur des millions de scenarios, les 40 meilleurs sur train SONT les 40 qui sur-ajustent le plus.
On les teste, ils echouent, et on conclut "data-limited".
Une config MEDIOCRE sur train mais ROBUSTE n'atteint JAMAIS le test.

CE QUE CES TESTS DEFENDENT
--------------------------
1. Le net du PIRE MARCHE rejette la config portee par UN SEUL coin chanceux.
2. Le test set recoit AUSSI des configs qui ne sont pas les champions du train.
3. Le controle stratifie existe -- sans lui, on ne peut pas savoir si le tri par train
   selectionne quoi que ce soit d'utile.

Aucun reseau, aucun ordre : donnees synthetiques.
"""
from __future__ import annotations

from hl_observer.backtesting.robust_selection import (
    coin_breakdown,
    select_for_test,
    worst_coin_net,
)


class _Sc:
    """Scenario factice : seule son identite compte pour la selection."""

    def __init__(self, nom: str) -> None:
        self.name = nom


def test_le_pire_marche_rejette_la_config_portee_par_un_seul_coin_chanceux() -> None:
    """LE test du bug. Somme excellente, pire marche desastreux."""
    by_coin = {
        "MEMECOIN": [100.0] * 10,   # +1000 $ : le coup de chance
        "BTC": [-2.0] * 10,         # -20 $
        "ETH": [-3.0] * 10,         # -30 $
        "SOL": [-1.0] * 10,         # -10 $
    }
    somme = sum(sum(v) for v in by_coin.values())
    assert somme > 900.0, "la SOMME est magnifique -- c'est exactement le piege"

    pire = worst_coin_net(by_coin)
    assert pire is not None
    assert pire == -30.0, (
        "Le MINIMAX doit rendre le net du PIRE marche (-30 sur ETH), PAS la somme (+940). "
        "Une config qui ne marche que sur 1 marche sur 4 n'est pas une strategie : "
        "c'est une coincidence -- et une coincidence, on ne peut pas la rejouer."
    )


def test_un_coin_sans_assez_de_trades_ne_compte_pas_comme_une_preuve() -> None:
    """3 trades sur un coin, ce n'est pas un resultat : c'est du bruit. Il ne doit pas decider."""
    by_coin = {
        "BTC": [1.0] * 20,          # 20 trades -> retenu
        "OBSCUR": [-500.0] * 3,     # 3 trades  -> IGNORE (pas assez de preuve)
    }
    detail = coin_breakdown(by_coin)
    assert "BTC" in detail["nets"]
    assert "OBSCUR" not in detail["nets"], "un coin sous le plancher de trades ne doit PAS etre note"
    assert detail["coins_ignores"]["OBSCUR"] == 3

    assert worst_coin_net(by_coin) == 20.0, (
        "Le pire marche doit ignorer OBSCUR (3 trades). Sinon un seul coin bruite, "
        "avec 3 trades malchanceux, condamnerait une config saine."
    )


def test_aucun_coin_credible_rend_NONE_et_pas_ZERO() -> None:
    """None = 'on ne sait pas'. Zero = 'c'est nul'. Ce n'est PAS la meme chose (deny-by-default)."""
    assert worst_coin_net({"X": [1.0, 2.0]}) is None, (
        "Sans assez de trades par coin, le minimax doit rendre None -- pas 0. "
        "Rendre 0 ferait passer un scenario SANS PREUVE devant un scenario legerement negatif "
        "mais PROUVE."
    )
    assert worst_coin_net({}) is None


def test_le_test_set_ne_recoit_plus_QUE_les_champions_du_train() -> None:
    """LE test du biais de selection."""
    # 100 scenarios, deja tries par net train decroissant (comme dans search()).
    scored = [(_Sc(f"s{i}"), {"net_total_usd": 1000.0 - i}) for i in range(100)]

    # Le scenario #90 est MEDIOCRE sur train (net = 910, il est 91e)... mais son PIRE
    # marche est le meilleur de tous. Avec l'ancien code (top_k=10), il n'aurait JAMAIS
    # ete teste.
    worst = {id(sc): -50.0 for sc, _ in scored}
    worst[id(scored[90][0])] = +5.0

    sel = select_for_test(scored, top_k=10, worst_by_scenario=worst, controle_k=5)
    noms = [sc.name for sc in sel["a_tester"]]

    assert "s90" in noms, (
        "REGRESSION : le scenario le plus ROBUSTE (meilleur pire-marche) n'a pas ete envoye "
        "au test parce qu'il n'etait pas dans le top-10 du train. C'EST LE BUG : on teste les "
        "configs qui sur-ajustent le plus, puis on s'etonne que rien ne survive."
    )
    assert "s0" in noms, "l'ancien comportement (top_net) doit rester, pour pouvoir COMPARER"
    assert sel["n_top_worst"] >= 1
    assert sel["n_controle"] >= 1


def test_le_controle_stratifie_couvre_toute_la_distribution_pas_seulement_le_sommet() -> None:
    """Sans controle, impossible de savoir si le tri par train selectionne quoi que ce soit."""
    scored = [(_Sc(f"s{i}"), {"net_total_usd": float(1000 - i)}) for i in range(100)]
    sel = select_for_test(scored, top_k=5, worst_by_scenario=None, controle_k=10)

    positions = [int(sc.name[1:]) for sc in sel["a_tester"]]
    assert max(positions) >= 80, (
        "Le controle doit atteindre le BAS de la distribution train. Si des configs mediocres "
        "sur train survivent au test AUSSI BIEN que les champions, alors le classement par "
        "train ne selectionne RIEN d'utile -- et c'est un resultat en soi, pas un detail."
    )
    assert sel["n_controle"] >= 5


def test_la_selection_est_deterministe() -> None:
    """Rejouable a l'identique : pas de random. Comme tout le replay."""
    scored = [(_Sc(f"s{i}"), {"net_total_usd": float(100 - i)}) for i in range(30)]
    a = select_for_test(scored, top_k=3, controle_k=5)
    b = select_for_test(scored, top_k=3, controle_k=5)
    assert [s.name for s in a["a_tester"]] == [s.name for s in b["a_tester"]]
