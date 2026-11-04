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


def _strict_s(adr, side, ts_ms, *, entity):
    return {
        "adresse": adr,
        "side": side,
        "coin": "BTC",
        "ts_ms": ts_ms,
        "size": 10.0,
        "public_entity_id": entity,
    }


def test_strict_consensus_refuse_les_votes_sans_preuve_point_in_time() -> None:
    assert consensus(
        [_s("a", "BUY"), _s("b", "BUY"), _s("c", "BUY")],
        min_wallets=3,
        exiger_independance_mesuree=True,
        as_of_ms=2_000,
    ) is None


def test_strict_consensus_replie_les_wallets_de_la_meme_entite() -> None:
    signals = [
        _strict_s("a", "BUY", 1_000, entity="desk-one"),
        _strict_s("b", "BUY", 1_100, entity="desk-one"),
        _strict_s("c", "BUY", 1_200, entity="desk-two"),
    ]

    assert consensus(
        signals,
        min_wallets=3,
        exiger_independance_mesuree=True,
        as_of_ms=2_000,
    ) is None


def test_strict_consensus_compte_les_entites_distinctes_et_ignore_le_futur() -> None:
    signals = [
        _strict_s("a", "BUY", 1_000, entity="desk-one"),
        _strict_s("b", "BUY", 1_100, entity="desk-two"),
        _strict_s("c", "BUY", 1_200, entity="desk-three"),
        _strict_s("d", "SELL", 9_000, entity="future-shared"),
    ]

    result = consensus(
        signals,
        min_wallets=3,
        exiger_independance_mesuree=True,
        as_of_ms=2_000,
    )

    assert result == {"direction": "LONG", "n_independants": 3, "n_oppose": 0}
