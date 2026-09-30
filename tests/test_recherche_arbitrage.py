"""RECHERCHE ARBITRAGE — la VRAIE grille (fade de dislocation × horizon), au COÛT EXÉCUTABLE (22/07).

Même bug que le carry : les filtres COPY vidaient la population arbitrage (0 % des champs). Ici le
mécanisme réel est un FADE directionnel du décalage HL, simulé par le simulateur VALIDÉ au coût
exécutable (~19,5 bps, pas le mid), avec plafond anti-aberrant.
"""
from __future__ import annotations

from hl_observer.backtesting.ab_flag_replay import marks_by_coin


def _marks_revert(coin, entry, t0, n=20, pas=0.0005):
    """Un chemin de marks qui REVIENT vers le bas depuis l'entrée (favorise un fade SHORT)."""
    return [{"coin": coin, "ts": t0 + i * 60.0, "mid": entry * (1.0 - pas * i)} for i in range(1, n + 1)]


def test_evaluer_arb_le_fade_PAIE_quand_la_dislocation_reverse():
    from hl_observer.backtesting.recherche_arbitrage import evaluer_arb
    t0 = 1000.0
    marks = marks_by_coin(_marks_revert("X", 100.0, t0))
    cands = [{"coin": "X", "direction": "SHORT", "current_mid": 100.0, "recorded_at": t0, "ecart_prix_bps": 60.0}]
    r = evaluer_arb(cands, marks, {"ecart_min_bps": 40.0, "horizon_min": 120.0})
    assert r["n_trades"] == 1 and r["net_moyen_usd"] > 0     # convergence − coût exécutable > 0


def test_evaluer_arb_exclut_sous_le_seuil_et_les_aberrants():
    from hl_observer.backtesting.recherche_arbitrage import evaluer_arb
    t0 = 1000.0
    marks = marks_by_coin(_marks_revert("X", 100.0, t0))
    base = {"coin": "X", "direction": "SHORT", "current_mid": 100.0, "recorded_at": t0}
    cands = [dict(base, ecart_prix_bps=30.0),      # < seuil 40 -> exclu
             dict(base, ecart_prix_bps=1000.0)]    # > 500 -> aberrant, écarté (jamais un edge)
    r = evaluer_arb(cands, marks, {"ecart_min_bps": 40.0, "horizon_min": 120.0})
    assert r["n_trades"] == 0 and r["ecartes_aberrants"] == 1


def test_chercher_arbitrage_INSUFFISANT_sans_donnees(tmp_path):
    from hl_observer.backtesting.recherche_arbitrage import chercher_arbitrage
    assert chercher_arbitrage(tmp_path)["statut"] == "INSUFFISANT"


def test_la_grille_arb_est_ECART_x_HORIZON_pas_copy():
    from hl_observer.backtesting.recherche_arbitrage import grille_arb
    cfgs = list(grille_arb())
    assert len(cfgs) >= 20
    for c in cfgs[:3] + cfgs[-3:]:
        assert set(c) == {"ecart_min_bps", "horizon_min"}
        assert "sl" not in c and "filtres" not in c


def test_chercher_module_aiguille_arbitrage_vers_sa_VRAIE_grille(tmp_path, monkeypatch):
    from hl_observer.backtesting import recherche_scenario as rs
    appels = {"n": 0}
    def _spy(root, **k):
        appels["n"] += 1
        return {"statut": "INSUFFISANT", "strategie": "arbitrage", "essais": []}
    monkeypatch.setattr(rs, "chercher_arbitrage", _spy)
    rs.chercher_module(tmp_path, "arbitrage")
    assert appels["n"] == 1
