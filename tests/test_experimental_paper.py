"""Voie EXPERIMENTAL_PAPER (décision Flo 23/07). On prouve : admission SANS prouve_oos mais AVEC
fraîcheur + exécutable + edge > 0 + limites ; ledger/budget ISOLÉS du live ; entrées/sorties aux
bid/ask avec coûts ; PnL directionnel ET funding_carry ; aucune exécution réelle."""
from __future__ import annotations

import json

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.runner import tick, STATUS_RELPATH


def _sig(**kw):
    d = dict(moteur="lead_lag", coin="ETH", sens=1, type_pnl="directional", notional_usd=100.0,
             prix_entree=3000.0, cout_entree_bps=4.0, edge_estime_bps=12.0, ts_signal_ms=10_000.0)
    d.update(kw)
    return MP.Signal(**d)


def test_admission_sans_oos_mais_fraicheur_executable_edge(tmp_path):
    store = MP.charger_store(tmp_path)
    now = 20_000.0
    assert MP.admettre(_sig(), store, now_ms=now) == (True, None)                 # frais + exécutable + edge>0
    assert MP.admettre(_sig(ts_signal_ms=0.0), store, now_ms=now)[1] == "SIGNAL_PERIME"
    assert MP.admettre(_sig(prix_entree=0.0), store, now_ms=now)[1] == "PRIX_NON_EXECUTABLE"
    assert MP.admettre(_sig(edge_estime_bps=-1.0), store, now_ms=now)[1] == "EDGE_NEGATIF_APRES_COUTS"
    assert MP.admettre(_sig(cout_entree_bps=-1.0), store, now_ms=now)[1] == "COUT_INCONNU"


def test_limites_par_moteur_et_un_marche_une_position(tmp_path):
    store = MP.charger_store(tmp_path)
    MP.ouvrir(_sig(coin="ETH"), store, tmp_path, now_ms=1000)
    assert MP.admettre(_sig(coin="ETH"), store, now_ms=1000)[1] == "DEJA_OUVERT"
    # remplir la limite de positions du moteur lead_lag (max 4)
    for c in ("SOL", "BTC", "AVAX"):
        MP.ouvrir(_sig(coin=c), store, tmp_path, now_ms=1000)
    assert MP.admettre(_sig(coin="LINK"), store, now_ms=1000)[1] == "LIMITE_POSITIONS_MOTEUR"


def test_pnl_directionnel_et_funding_carry(tmp_path):
    store = MP.charger_store(tmp_path)
    pos = MP.ouvrir(_sig(coin="ETH", sens=1, prix_entree=3000.0, cout_entree_bps=4.0), store, tmp_path, now_ms=0)
    # +1 % de prix sur 100$ notional − coût d'entrée 4 bps = 1.0 − 0.04
    assert MP.pnl_courant_usd(pos, mark=3030.0) == 0.96
    carry = MP.ouvrir(_sig(moteur="cross_venue", coin="DOT", type_pnl="funding_carry", d_bps_h=0.5,
                           cout_entree_bps=6.0), store, tmp_path, now_ms=0)
    # 0.5 bps/h × 10 h = 5 bps de funding sur 100$ = 0.05 − coût 6 bps = 0.06 -> -0.01
    assert MP.pnl_courant_usd(carry, now_ms=10 * 3_600_000) == -0.01


def test_sortie_au_bidask_avec_cout_et_ledger_ISOLE(tmp_path):
    store = MP.charger_store(tmp_path)
    pos = MP.ouvrir(_sig(coin="ETH", sens=1, prix_entree=3000.0, cout_entree_bps=4.0), store, tmp_path, now_ms=0)
    r = MP.sortir(pos, store, tmp_path, prix_sortie=3030.0, cout_sortie_bps=4.0, raison="TEST", now_ms=1000)
    assert r["realized_usd"] == 0.92                                             # 0.96 − 0.04 de sortie
    assert MP.charger_store(tmp_path)["ouvertes"] == {}
    # le ledger est SÉPARÉ (experimental) et JAMAIS le ledger carry live
    lignes = [json.loads(l) for l in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    assert all(x["mode"] == "EXPERIMENTAL_PAPER" and x["real_execution"] is False for x in lignes)
    assert not (tmp_path / "runtime" / "data" / "carry_paper_ledger.jsonl").exists()


def test_runner_ouvre_une_position_sur_signal_admis(tmp_path, monkeypatch):
    """Le runner collecte -> admet -> OUVRE réellement, et écrit un statut lisible."""
    from hl_observer.experimental import runner as R
    monkeypatch.setattr(R, "COLLECTEURS", {"lead_lag": lambda root, now_ms=None: ([_sig(coin="ETH", ts_signal_ms=now_ms)], [])})
    st = tick(tmp_path, now_ms=50_000.0, moteurs=("lead_lag",))
    assert len(st["ouvertures"]) == 1 and st["premier_signal"]["coin"] == "ETH"
    assert st["resume"]["positions_ouvertes"] == 1 and st["resume"]["real_execution"] is False
    assert (tmp_path / STATUS_RELPATH).exists()


def test_runner_refuse_et_motive(tmp_path, monkeypatch):
    from hl_observer.experimental import runner as R
    monkeypatch.setattr(R, "COLLECTEURS",
                        {"lead_lag": lambda root, now_ms=None: ([_sig(edge_estime_bps=-5.0, ts_signal_ms=now_ms)], [])})
    st = tick(tmp_path, now_ms=50_000.0, moteurs=("lead_lag",))
    assert st["ouvertures"] == [] and st["refus_par_motif"].get("EDGE_NEGATIF_APRES_COUTS") == 1
