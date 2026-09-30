"""Edge-decay : la grille d'horizons, et le gate de résolution qui empêche d'inventer un markout.

Le test le plus important est `test_un_horizon_sous_la_cadence_est_refuse` : si les cotations arrivent
toutes les 16 s, un « markout à 100 ms » n'existe pas dans les données. Le calculer reviendrait à mesurer
la cotation suivante et à l'appeler autrement.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import edge_decay as ED  # noqa: E402

T0 = 1_700_000_000_000


def _index(pas_ms=1_000, n=2_000, coin="BTC", pente=0.01):
    ts = [T0 + i * pas_ms for i in range(n)]
    mid = [100.0 + i * pente for i in range(n)]
    return {coin: {"ts": ts, "mid": mid}}


def _episodes(n=60, coin="BTC", action="OPEN", sens=1, pas_ms=10_000):
    return [{"coin": coin, "ts_ms": T0 + i * pas_ms, "sens": sens, "action": action,
             "notional_usd": 100.0} for i in range(n)]


# ═══════════════ cadence et horizons mesurables ═══════════════
def test_la_cadence_mediane_est_mesuree():
    assert ED.cadence_par_coin(_index(pas_ms=250))["BTC"] == 250.0


def test_une_serie_trop_courte_na_pas_de_cadence():
    assert ED.cadence_par_coin({"BTC": {"ts": [1, 2], "mid": [1.0, 1.0]}})["BTC"] is None


def test_un_horizon_sous_la_cadence_est_refuse():
    """Cadence 16,7 s : tout horizon inferieur n'existe pas dans les donnees."""
    ouverts = ED.horizons_mesurables(16_701.0)
    assert 100 not in ouverts and 5_000 not in ouverts and 10_000 not in ouverts
    assert ouverts == [30_000, 60_000, 120_000, 300_000]


def test_une_cadence_fine_ouvre_toute_la_grille():
    assert ED.horizons_mesurables(50.0) == list(ED.HORIZONS_MS)


def test_cadence_inconnue_nouvre_aucun_horizon():
    assert ED.horizons_mesurables(None) == [] and ED.horizons_mesurables(0) == []


# ═══════════════ la grille ═══════════════
def test_la_grille_refuse_les_horizons_non_mesurables_et_les_compte():
    r = ED.grille({"w": _episodes(40)}, _index(pas_ms=20_000, n=500), min_episodes=5)
    assert r["non_mesurables"]["HORIZON_SOUS_LA_CADENCE"] > 0
    for h in ("100", "1000", "10000"):
        assert r["courbe_globale"][h]["n"] == 0


def test_un_markout_positif_apparait_quand_le_prix_monte():
    r = ED.grille({"w": _episodes(60, sens=1)}, _index(pas_ms=1_000, n=3_000),
                  cout_ar_bps=0.0, min_episodes=5)
    c = r["courbe_globale"]["1000"]
    assert c["statut"] == "MESURE" and c["gross_bps"] > 0 and c["net_bps"] == c["gross_bps"]


def test_les_couts_deplacent_le_net_pas_le_brut():
    args = ({"w": _episodes(60)}, _index(pas_ms=1_000, n=3_000))
    sans = ED.grille(*args, cout_ar_bps=0.0, min_episodes=5)["courbe_globale"]["1000"]
    avec = ED.grille(*args, cout_ar_bps=9.0, min_episodes=5)["courbe_globale"]["1000"]
    assert avec["gross_bps"] == sans["gross_bps"]
    assert round(sans["net_bps"] - avec["net_bps"], 6) == 9.0


def test_un_short_inverse_le_signe_du_markout():
    hausse = ED.grille({"w": _episodes(60, sens=1)}, _index(pas_ms=1_000, n=3_000),
                       cout_ar_bps=0.0, min_episodes=5)["courbe_globale"]["1000"]
    baisse = ED.grille({"w": _episodes(60, sens=-1)}, _index(pas_ms=1_000, n=3_000),
                       cout_ar_bps=0.0, min_episodes=5)["courbe_globale"]["1000"]
    assert hausse["gross_bps"] > 0 > baisse["gross_bps"]


def test_une_cellule_sous_le_minimum_ne_publie_aucune_moyenne():
    r = ED.grille({"w": _episodes(5)}, _index(pas_ms=1_000, n=3_000), min_episodes=20)
    c = r["courbe_globale"]["1000"]
    assert c["statut"] == "N_INSUFFISANT" and c["gross_bps"] is None and c["net_bps"] is None


# ═══════════════ segmentations ═══════════════
def test_la_segmentation_par_action_est_produite():
    episodes = _episodes(30, action="OPEN") + _episodes(30, action="REDUCE", pas_ms=11_000)
    r = ED.grille({"w": episodes}, _index(pas_ms=1_000, n=3_000), min_episodes=5)
    assert set(r["par_action"]["1000"]) == {"OPEN", "REDUCE"}


def test_premier_de_sequence_vs_fills_suivants():
    episodes = _episodes(30, action="OPEN") + _episodes(30, action="ADD", pas_ms=11_000)
    r = ED.grille({"w": episodes}, _index(pas_ms=1_000, n=3_000), min_episodes=5)
    bloc = r["premier_vs_suite"]["1000"]
    assert set(bloc) == {"premier_de_sequence", "fills_suivants"}
    assert bloc["premier_de_sequence"]["n"] == 30 and bloc["fills_suivants"]["n"] == 30


def test_le_flip_compte_comme_premier_de_sequence():
    r = ED.grille({"w": _episodes(30, action="FLIP")}, _index(pas_ms=1_000, n=3_000), min_episodes=5)
    assert r["premier_vs_suite"]["1000"]["premier_de_sequence"]["n"] == 30


# ═══════════════ verdict ═══════════════
def test_aucun_horizon_positif_donne_un_verdict_explicite():
    r = ED.grille({"w": _episodes(60)}, _index(pas_ms=1_000, n=3_000), cout_ar_bps=10_000.0,
                  min_episodes=5)
    assert r["verdict"] == "AUCUN_HORIZON_NET_POSITIF" and r["horizons_nets_positifs"] == []


def test_un_horizon_positif_reste_a_investiguer_jamais_promu():
    r = ED.grille({"w": _episodes(60)}, _index(pas_ms=1_000, n=3_000), cout_ar_bps=0.0,
                  min_episodes=5)
    assert r["verdict"] == "HORIZONS_A_INVESTIGUER"
    assert r["promotion_possible"] is False and r["real_execution"] is False
    assert "placebo" in r["note"] and "forward" in r["note"]


def test_la_grille_dhorizons_est_preenregistree():
    assert ED.HORIZONS_MS == (100, 250, 500, 1_000, 2_000, 5_000, 10_000, 30_000, 60_000,
                              120_000, 300_000)


# ═══════════════ P4 — markout EXÉCUTABLE (ask→bid), pas au mid ═══════════════
def _bbo(pas_ms=250, n=2_000, coin="BTC", spread=0.10, pente=0.0, venue=None):
    ts = [T0 + i * pas_ms for i in range(n)]
    bid = [100.0 + i * pente for i in range(n)]
    ask = [b + spread for b in bid]
    idx = {coin: {"ts": ts, "bid": bid, "ask": ask}}
    return idx


def _ecrire_bbo(tmp_path, lignes, nom="bbo.jsonl"):
    import json as _j
    p = tmp_path / nom
    p.write_text("\n".join(_j.dumps(x) for x in lignes) + "\n", encoding="utf-8")
    return p


def test_le_schema_bbo_synchro_est_lu(tmp_path):
    p = _ecrire_bbo(tmp_path, [{"coin": "BTC", "ts_ms": T0, "hl_bid": 100.0, "hl_ask": 100.1}])
    idx = ED.charger_bbo(p)
    assert idx["BTC"]["bid"] == [100.0] and idx["BTC"]["ask"] == [100.1]


def test_seules_les_lignes_hyperliquid_sont_retenues(tmp_path):
    p = _ecrire_bbo(tmp_path, [
        {"venue": "HL", "coin": "BTC", "ts_wall_ms": T0, "bid": 100.0, "ask": 100.1},
        {"venue": "BIN", "coin": "BTC", "ts_wall_ms": T0 + 1, "bid": 200.0, "ask": 200.1}])
    idx = ED.charger_bbo(p)
    assert len(idx["BTC"]["ts"]) == 1 and idx["BTC"]["bid"] == [100.0]


def test_un_carnet_croise_est_rejete(tmp_path):
    p = _ecrire_bbo(tmp_path, [{"coin": "BTC", "ts_ms": T0, "hl_bid": 101.0, "hl_ask": 100.0}])
    assert ED.charger_bbo(p) == {}


def test_le_markout_executable_inclut_le_spread():
    """Prix plat : un aller-retour ask->bid coûte exactement le spread, jamais 0."""
    idx = _bbo(spread=0.10, pente=0.0)          # spread 10 bps sur 100
    m = ED.markout_executable_bps(idx, coin="BTC", ts_ms=T0, sens=1, horizon_ms=1_000)
    assert m is not None and round(m, 1) == -10.0
    assert m < 0, "franchir le spread ne peut pas etre gratuit"


def test_le_markout_executable_est_plus_severe_que_le_mid():
    from hl_observer.ops.global_observer_pipeline import markout_bps as mid_markout
    exe = _bbo(spread=0.10, pente=0.01)
    mid = {"BTC": {"ts": exe["BTC"]["ts"],
                   "mid": [(b + a) / 2 for b, a in zip(exe["BTC"]["bid"], exe["BTC"]["ask"])]}}
    m_exe = ED.markout_executable_bps(exe, coin="BTC", ts_ms=T0, sens=1, horizon_ms=1_000)
    m_mid = mid_markout(mid, coin="BTC", ts_ms=T0, sens=1, horizon_ms=1_000)
    assert m_exe < m_mid, "le mid flatte toujours par rapport au prix executable"


def test_le_short_execute_au_bid_et_rachete_a_lask():
    idx = _bbo(spread=0.10, pente=0.0)
    m = ED.markout_executable_bps(idx, coin="BTC", ts_ms=T0, sens=-1, horizon_ms=1_000)
    assert round(m, 1) == -10.0                 # symetrique : le spread se paie dans les deux sens


def test_sans_cote_a_lhorizon_aucun_markout_executable():
    idx = _bbo(n=3, pas_ms=250)
    assert ED.markout_executable_bps(idx, coin="BTC", ts_ms=T0, sens=1, horizon_ms=300_000) is None
    assert ED.markout_executable_bps(idx, coin="DOGE", ts_ms=T0, sens=1, horizon_ms=1_000) is None


def test_le_mode_executable_est_signale_et_promouvable():
    episodes = {"w": _episodes(60, pas_ms=1_000)}
    mid = ED.grille(episodes, _index(pas_ms=250, n=5_000), min_episodes=5)
    exe = ED.grille(episodes, {}, index_bbo=_bbo(pas_ms=250, n=5_000, pente=0.01),
                    cout_ar_bps=4.5, min_episodes=5)
    assert mid["mode"] == "MID_SCREENING_SEULEMENT" and mid["promouvable"] is False
    assert exe["mode"] == "EXECUTABLE_ASK_BID" and exe["promouvable"] is True
    assert exe["spread_inclus_dans_le_prix"] is True


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "edge_decay.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans edge_decay: %s" % interdit
