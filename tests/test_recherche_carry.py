"""RECHERCHE CARRY — la VRAIE grille (funding × durée), FIDÈLE au mécanisme (22/07).

Le bug trouvé : filtres COPY qui vidaient la population carry + SL/TP directionnel sur du
delta-neutre → faux « aucun calibrage ». Et mon 1ᵉʳ évaluateur comptait chaque snapshot comme une
position (faux +251 419 bps). L'évaluateur fidèle : une position PAR COIN, funding INTÉGRÉ sur la
vraie fenêtre (sans extrapolation), coût payé une fois, métrique = net MOYEN par position.
"""
from __future__ import annotations

import json

H = 3_600_000.0        # 1 heure en ms


def test_evaluer_carry_integre_le_funding_entre_scans_moins_le_cout():
    """Net = funding INTÉGRÉ sur la fenêtre − coût. 2 scans du même coin à 100 h : 0.5 bps/h × 100 h
    − 30 = 20 bps sur 1 position. Pas de comptage de snapshots, pas d'extrapolation."""
    from hl_observer.backtesting.recherche_carry import evaluer_carry
    t0 = 1000.0 * H                                   # horodatage réaliste (> 0 ; ts=0 = manquant)
    scans = [{"coin": "X", "ts_ms": t0, "funding_bps_h": 0.5, "cout_entree_bps": 30.0, "liquidite_spot_usd": 1e5},
             {"coin": "X", "ts_ms": t0 + 100 * H, "funding_bps_h": 0.5, "cout_entree_bps": 30.0, "liquidite_spot_usd": 1e5}]
    r = evaluer_carry(scans, {"funding_min_bps_h": 0.3, "hold_h": 200.0, "liq_min_usd": 0})
    assert r["n_positions"] == 1
    assert abs(r["net_total_bps"] - 20.0) < 1e-6 and abs(r["net_moyen_bps"] - 20.0) < 1e-6


def test_evaluer_carry_exclut_la_liquidite_trop_faible():
    from hl_observer.backtesting.recherche_carry import evaluer_carry
    scans = [{"coin": "X", "ts_ms": 0.0, "funding_bps_h": 0.5, "cout_entree_bps": 10.0, "liquidite_spot_usd": 1_000},
             {"coin": "X", "ts_ms": 50 * H, "funding_bps_h": 0.5, "cout_entree_bps": 10.0, "liquidite_spot_usd": 1_000}]
    r = evaluer_carry(scans, {"funding_min_bps_h": 0.1, "hold_h": 100.0, "liq_min_usd": 50_000})
    assert r["n_positions"] == 0                      # liquidité 1k < seuil 50k -> exclu


def _ecrire_scans(tmp_path, funding, cout, n_coins=40, gap_h=50.0):
    d = tmp_path / "runtime" / "replay"
    d.mkdir(parents=True, exist_ok=True)
    lignes = []
    t0 = 1000.0 * H                                   # horodatage réaliste (> 0)
    for k in range(n_coins):                          # n_coins positions distinctes (1 par coin)
        for t in (t0, t0 + gap_h * H):
            lignes.append(json.dumps({"coin": "C%d" % k, "ts_ms": t, "funding_bps_h": funding,
                                      "cout_entree_bps": cout, "liquidite_spot_usd": 1e5}))
    (d / "carry_scan.jsonl").write_text("\n".join(lignes), encoding="utf-8")


def test_chercher_carry_TROUVE_un_seuil_quand_il_existe(tmp_path):
    """40 coins, funding 0.5 sur 50 h, coût 10 → net moyen = 0.5×50 − 10 = 15 bps > 0 (pour un hold
    qui couvre les 50 h). Un vrai calibrage carry positif DOIT ressortir."""
    _ecrire_scans(tmp_path, funding=0.5, cout=10.0)
    from hl_observer.backtesting.recherche_carry import chercher_carry
    r = chercher_carry(tmp_path)
    assert r["statut"] == "PROMU" and r["gagnant"] is not None and r["promus"]
    assert max(p["nets"]["stress"] for p in r["promus"]) > 0


def test_chercher_carry_reste_HONNETE_au_plancher_de_funding(tmp_path):
    """Funding au plancher (0.125) + coût élevé (80) → net moyen toujours < 0 → ESPACE_EPUISE.
    PAS un faux positif, et surtout pas le faux 0.0 d'un filtre qui vide la population."""
    _ecrire_scans(tmp_path, funding=0.125, cout=80.0)
    from hl_observer.backtesting.recherche_carry import chercher_carry
    r = chercher_carry(tmp_path)
    assert r["statut"] == "ESPACE_EPUISE" and not r["promus"]


def test_chercher_carry_INSUFFISANT_sans_donnees(tmp_path):
    from hl_observer.backtesting.recherche_carry import chercher_carry
    assert chercher_carry(tmp_path)["statut"] == "INSUFFISANT"


def test_chercher_module_aiguille_carry_vers_sa_VRAIE_grille(tmp_path, monkeypatch):
    from hl_observer.backtesting import recherche_scenario as rs
    appels = {"n": 0}
    def _spy(root, **k):
        appels["n"] += 1
        return {"statut": "INSUFFISANT", "strategie": "carry", "essais": []}
    monkeypatch.setattr(rs, "chercher_carry", _spy)
    rs.chercher_module(tmp_path, "carry")
    assert appels["n"] == 1


def test_la_grille_carry_n_a_RIEN_de_directionnel():
    from hl_observer.backtesting.recherche_carry import grille_carry
    cfgs = list(grille_carry())
    assert len(cfgs) > 100
    for c in cfgs[:5] + cfgs[-5:]:
        assert set(c) == {"funding_min_bps_h", "hold_h", "liq_min_usd"}
        assert "sl" not in c and "tp" not in c
