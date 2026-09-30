"""C14 — consensus de wallets indépendants : une baleine ne suffit pas ; les corrélés comptent pour un."""
from __future__ import annotations

from hl_observer.copy_wallet.wallet_consensus import consensus


def _s(adr, side):
    return {"adresse": adr, "side": side}


def test_trois_wallets_independants_font_consensus():
    r = consensus([_s("a", "BUY"), _s("b", "BUY"), _s("c", "BUY")], min_wallets=3)
    assert r == {"direction": "LONG", "n_independants": 3, "n_oppose": 0}


def test_une_seule_baleine_ne_suffit_pas():
    assert consensus([_s("whale", "BUY")], min_wallets=3) is None


def test_wallets_correles_comptent_pour_un():
    # 3 adresses mais toutes du même groupe -> 1 seul indépendant -> pas de quorum
    groupes = [frozenset({"a", "b", "c"})]
    assert consensus([_s("a", "BUY"), _s("b", "BUY"), _s("c", "BUY")],
                     min_wallets=3, groupes_correles=groupes) is None


def test_doit_dominer_le_cote_oppose():
    # 3 long vs 3 short -> egalite -> pas de consensus
    sig = [_s("a", "BUY"), _s("b", "BUY"), _s("c", "BUY"),
           _s("d", "SELL"), _s("e", "SELL"), _s("f", "SELL")]
    assert consensus(sig, min_wallets=3) is None


def test_majorite_nette_passe():
    sig = [_s("a", "BUY"), _s("b", "BUY"), _s("c", "BUY"), _s("d", "BUY"), _s("e", "SELL")]
    r = consensus(sig, min_wallets=3)
    assert r["direction"] == "LONG" and r["n_independants"] == 4 and r["n_oppose"] == 1


def test_doublon_d_adresse_compte_une_fois():
    assert consensus([_s("a", "BUY"), _s("a", "BUY"), _s("b", "BUY")], min_wallets=3) is None


def test_ignore_un_signal_non_mapping_fail_closed():
    assert consensus([None, _s("a", "BUY")], min_wallets=2) is None
