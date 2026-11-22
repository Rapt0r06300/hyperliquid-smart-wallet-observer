"""Retraits par LEDGER (rectif Flo 23/07) : userNonFundingLedgerUpdates identifie les retraits ; les
REDUCE proches d'un retrait RÉEL sont marqués source='ledger' ; l'heuristique pro-rata ne sert qu'en
SECOURS. Aucun réseau (ledger injecté)."""
from __future__ import annotations

from hl_observer.collection import vault_ledger as VL
from hl_observer.collection import vault_fills_backfill as VB


def test_parser_ledger_detecte_les_retraits():
    rep = [{"time": 100, "delta": {"type": "deposit", "usdc": "1000"}},
           {"time": 200, "delta": {"type": "withdraw", "usdc": "-500"}},
           {"time": 300, "delta": {"type": "vaultWithdraw", "amount": "-200"}},
           {"bad": 1}]
    led = VL.parser_ledger(rep, vault="0xA")
    assert len(led) == 3
    assert [m["est_retrait"] for m in led] == [False, True, True]
    assert VL.horaires_retraits(led) == {"0xA": [200, 300]}


def test_marquer_retraits_ledger_prioritaire_sur_heuristique():
    # une position réduite JUSTE au moment d'un retrait ledger -> marquée source='ledger'
    fills = VB.parser_fills([
        {"time": 1, "coin": "SOL", "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"},
        {"time": 500_000, "coin": "SOL", "px": "100", "sz": "5", "side": "A", "dir": "Close Long", "startPosition": "10"},
    ], vault="0xA")
    events = VB.reconstruire_episodes(fills)
    ledger = VL.parser_ledger([{"time": 500_000, "delta": {"type": "withdraw", "usdc": "-1000"}}], vault="0xA")
    VL.marquer_retraits_ledger(events, ledger, fenetre_ms=60_000, heuristique_secours=VB.marquer_retraits)
    red = [e for e in events if e["action"] == "REDUCE"][0]
    assert red["retrait_probable"] is True and red["retrait_source"] == "ledger"


def test_heuristique_en_secours_si_pas_de_ledger():
    # 3 coins réduits pro-rata sans ledger -> l'heuristique de secours les attrape (source='heuristique')
    fills = VB.parser_fills([
        {"time": 1, "coin": c, "px": "100", "sz": "10", "side": "B", "dir": "Open Long", "startPosition": "0"}
        for c in ("BTC", "ETH", "SOL")
    ] + [
        {"time": 100000 + i, "coin": c, "px": "100", "sz": "2", "side": "A", "dir": "Close Long", "startPosition": "10"}
        for i, c in enumerate(("BTC", "ETH", "SOL"))
    ], vault="0xA")
    events = VB.reconstruire_episodes(fills)
    VL.marquer_retraits_ledger(events, [], heuristique_secours=VB.marquer_retraits)   # ledger vide
    red = [e for e in events if e["action"] == "REDUCE"]
    assert red and all(e["retrait_probable"] and e["retrait_source"] == "heuristique" for e in red)


# --------------------------- lecture du montant (defaut mesure le 21/11/2026)
def test_une_seconde_clef_valide_n_est_plus_ignoree():
    """DEFAUT : le `break` se declenchait sur la premiere clef PRESENTE, meme illisible.

    Un delta `{"usdc": "n/a", "amount": "-250"}` rendait `delta_usd=None` et
    `est_retrait=False` : du capital SORTANT devenait invisible, et une absence prenait
    la valeur d'un zero favorable.
    """
    ligne = VL.parser_ledger([{"time": 1_700_000_000_000, "hash": "0xb",
                            "delta": {"type": "transfer", "usdc": "n/a",
                                      "amount": "-250"}}], vault="0xaa")[0]
    assert ligne["delta_usd"] == -250.0
    assert ligne["delta_clef"] == "amount"
    assert ligne["est_retrait"] is True, "un montant negatif est une sortie de capital"
    assert ligne["delta_illisible"] is False


def test_un_montant_illisible_se_DIT_au_lieu_de_valoir_zero():
    ligne = VL.parser_ledger([{"time": 1_700_000_000_000, "hash": "0xc",
                            "delta": {"type": "transfer", "usdc": "n/a"}}], vault="0xaa")[0]
    assert ligne["delta_usd"] is None
    assert ligne["delta_illisible"] is True
    assert ligne["delta_clef"] is None


def test_un_delta_sans_aucune_clef_de_montant_n_est_pas_dit_illisible():
    """`illisible` doit vouloir dire << des clefs existaient et aucune n'etait lisible >>."""
    ligne = VL.parser_ledger([{"time": 1_700_000_000_000, "hash": "0xd",
                            "delta": {"type": "deposit"}}], vault="0xaa")[0]
    assert ligne["delta_usd"] is None
    assert ligne["delta_illisible"] is False


def test_la_contrepartie_d_un_mouvement_est_conservee():
    """Sans elle, un transfert interne et un retrait vers l'exterieur se ressemblent."""
    ligne = VL.parser_ledger([{"time": 1_700_000_000_000, "hash": "0xe",
                            "delta": {"type": "internalTransfer", "usdc": "100",
                                      "destination": "0xdead"}}], vault="0xaa")[0]
    assert ligne["contrepartie"] == "0xdead"


def test_un_montant_non_fini_est_refuse_et_non_propage():
    """`inf` dans une comptabilite contamine toute somme qui le touche."""
    ligne = VL.parser_ledger([{"time": 1_700_000_000_000, "hash": "0xf",
                            "delta": {"type": "deposit", "usdc": "inf",
                                      "amount": "42"}}], vault="0xaa")[0]
    assert ligne["delta_usd"] == 42.0
    assert ligne["delta_clef"] == "amount"
