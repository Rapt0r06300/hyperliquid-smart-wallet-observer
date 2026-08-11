"""LOT14 — CORRECTIONS P0→P11 : tests d'INTÉGRATION (pas des helpers isolés).

Chaque test fait tourner le VRAI chemin : adaptateur réel (données fabriquées mais lues comme en prod) →
Signal → admettre → ouvrir → sauver → REDUCE/CLOSE → resume → réconciliation. On PROUVE que la base
économique ne bloque plus les vrais signaux ET reste honnête (idempotence, coûts, fraîcheur, deux jambes).
0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.lead_lag_evidence import REQUIRED_CRITERIA, SCHEMA_VERSION
from hl_observer.experimental import execution_paper as EP
from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental import reconciliation_paper as REC
from hl_observer.experimental import runner as R
from hl_observer.experimental import signaux as S

NOW = 1_000_000_000.0


def _data(root: Path) -> Path:
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ecrire(p: Path, lignes: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")


# ─────────── fabrique de données pour les 3 VRAIS adaptateurs ───────────
def _fixture_lead_lag(root: Path, *, trade_ms: float = NOW - 500, edge_h_bps: float = 66.0) -> None:
    d = _data(root)
    (d / "lead_lag_config_gele.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "strategy": "lead_lag_shadow",
        "promotion_status": "PROMOTED",
        "dataset_hash": "sha256:" + "1" * 64,
        "pipeline_hash": "sha256:" + "2" * 64,
        "freeze_ts": "2026-07-29T00:00:00+00:00",
        "freeze_ts_ms": 1,
        "coins": ["SOL"],
        "control_coins": [],
        "requested_horizons_ms": [1000.0],
        "observable_horizons_ms": [1000.0],
        "minimum_events": 30,
        "seuil_choc_bps": 8.0,
        "edge_net_par_horizon_bps": {"1000": edge_h_bps},
        "sample_n_by_horizon": {"1000": 30},
        "costs": {"round_trip_bps": 6.0, "executable": True},
        "latency_budget": {
            "alpha_half_life_p95_ms": 2000.0,
            "end_to_end_latency_p95_ms": 100.0,
            "safety_margin_ms": 25.0,
        },
        "frequency": {"events_per_day": 5.0},
        "criteria": {name: True for name in REQUIRED_CRITERIA},
        "global_trials": {"count": 1},
    }))
    _ecrire(d / "bbo_tape.jsonl", [
        {"coin": "SOL", "venue": "HL", "bid": 100.0, "ask": 100.03,
         "recu_ns": 10, "ts_wall_ms": trade_ms - 100},
        {"coin": "SOL", "venue": "BIN_TRADE", "px": 100.6, "side": "buy",
         "recu_ns": 20, "ts_wall_ms": trade_ms}])


def _fixture_vaults(root: Path, *, snap2_ms: float = NOW - 1000) -> None:
    d = _data(root)
    _ecrire(d / "vault_snapshots.jsonl", [
        {"vault": "0xabc", "ts_ms": int(NOW - 20000), "nav_usd": 100000.0,
         "positions": [{"coin": "SOL", "szi": 0.0, "entryPx": 100.0}]},
        {"vault": "0xabc", "ts_ms": int(snap2_ms), "nav_usd": 100000.0,
         "positions": [{"coin": "SOL", "szi": 100.0, "entryPx": 100.0}]}])
    (d / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xabc"]}))


def _lecteur_l2(coin):
    return {"hl_bid": 100.0, "hl_ask": 100.05, "depth_usd": 5000.0, "age_ms": 100.0}


def _edge_par_coin():
    return {"SOL": {"edge_brut_bps": 80.0, "horizon_ms": 3_600_000, "freq_evenements_par_jour": 3.0}}


def _fixture_cross_venue(root: Path) -> None:
    _ecrire(_data(root) / "bbo_synchro.jsonl", [
        {"coin": "DOT", "hl_bid": 99.9, "hl_ask": 100.0, "bin_bid": 101.0, "bin_ask": 101.1,
         "age_hl_ms": 100, "age_bin_ms": 120, "desync_ms": 40, "taille_top_usd": 5000.0,
         "recv_wall_hl_ms": NOW - 120, "recv_wall_bin_ms": NOW - 100,
         "write_wall_ts_ms": NOW - 90, "ts_ms": NOW - 90}])


# ══════════════ P0 — la gate ROI ne bloque plus les VRAIS signaux ══════════════
def test_P0_lead_lag_signal_reel_admis(tmp_path):
    _fixture_lead_lag(tmp_path)
    sigs, _ = S.signaux_lead_lag(tmp_path, now_ms=NOW)
    assert sigs, "l'adaptateur lead_lag doit produire un vrai signal"
    sig = sigs[0]
    assert sig.roi_annuel_pct is not None and sig.roi_annuel_pct > 0, "ROI MESURÉ (freq fournie), pas 0.0"
    ok, motif = MP.admettre(sig, MP.charger_store(tmp_path), now_ms=NOW)
    assert ok is True and motif is None, "un candidat valide n'est PAS rejeté (roi ne bloque plus)"


def test_P0_vaults_signal_reel_admis(tmp_path):
    _fixture_vaults(tmp_path)
    sigs, _ = S.signaux_vaults(tmp_path, now_ms=NOW, lecteur_l2=_lecteur_l2, edge_par_coin=_edge_par_coin())
    assert sigs, "l'adaptateur copy_vault doit produire un vrai signal"
    sig = sigs[0]
    assert sig.roi_annuel_pct is not None and sig.roi_annuel_pct > 0
    ok, motif = MP.admettre(sig, MP.charger_store(tmp_path), now_ms=NOW)
    assert ok is True and motif is None


def test_P0_cross_venue_signal_reel_admis(tmp_path):
    _fixture_cross_venue(tmp_path)
    sigs, _ = S.signaux_cross_venue(tmp_path, now_ms=NOW)
    assert sigs, "l'adaptateur cross_venue doit produire un vrai signal"
    sig = sigs[0]
    # cross-venue ne mesure pas de fréquence -> roi None : experimental ADMET (collecte forward), pas ROI=0 bloquant
    assert sig.roi_annuel_pct is None
    ok, motif = MP.admettre(sig, MP.charger_store(tmp_path), now_ms=NOW)
    assert ok is True and motif is None
    assert MP.admettre(sig, MP.charger_store(tmp_path), now_ms=NOW, mode="strict")[1] == "ROI_NON_MESURABLE"


# ══════════════ P1 — REDUCE idempotent : même snapshot 2 fois ══════════════
def _pos_copy(root: Path, *, entry_szi: float = 10.0, notional: float = 100.0, snap_id=None) -> dict:
    store = MP.charger_store(root)
    sig = MP.Signal(moteur="copy_vault", coin="SOL", sens=1, type_pnl="directional", notional_usd=notional,
                    prix_entree=100.0, cout_entree_bps=4.0, edge_estime_bps=40.0, ts_signal_ms=NOW - 1000,
                    roi_annuel_pct=50.0, pnl_attendu_usd=1.0, hold_h=1.0, frais_bps=2.0, slippage_bps=1.0,
                    meta={"vault": "0xabc", "szi_apres": entry_szi})
    pos = MP.ouvrir(sig, store, root, now_ms=NOW - 10_000)
    MP.sauver_store(root, store)
    return store


def _snap(root: Path, szi: float, *, ts=None, nav=100000.0, complet=True, snap_id=None):
    ts = int(NOW if ts is None else ts)
    pos = [{"coin": "SOL", "szi": szi, "entryPx": 100.0}] if szi != 0 else []
    d = {"vault": "0xabc", "ts_ms": ts, "positions": pos}
    if nav:
        d["nav_usd"] = nav
    if not complet:
        d.pop("positions", None); d.pop("nav_usd", None)
    if snap_id:
        d["snapshot_id"] = snap_id
    return d


def _bidask_sol(root: Path):
    _ecrire(_data(root) / "bbo_tape.jsonl",
            [{"coin": "SOL", "venue": "HL", "bid": 100.0, "ask": 100.02, "ts_wall_ms": NOW}])


def test_P1_meme_snapshot_deux_fois_ne_reduit_qu_une_fois(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0, notional=100.0)
    _bidask_sol(tmp_path)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 4.0, snap_id="snapA")])  # cible = 100*4/10 = 40
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert abs(store["ouvertes"]["copy_vault:SOL"]["notional_usd"] - 40.0) < 1e-6, "1er tick : 100 -> 40"
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 1000)                                          # MÊME snapshot
    assert abs(store["ouvertes"]["copy_vault:SOL"]["notional_usd"] - 40.0) < 1e-6, "2e tick : reste 40, JAMAIS 16"


# ══════════════ P2 — toutes les réductions + flips (taille signée) ══════════════
def test_P2_reductions_successives_puis_flip(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0, notional=100.0)
    _bidask_sol(tmp_path)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 6.0, snap_id="s6")])   # 40% -> cible 60
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert abs(store["ouvertes"]["copy_vault:SOL"]["notional_usd"] - 60.0) < 1e-6
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 3.0, ts=NOW + 1, snap_id="s3")])  # cible 30
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 1000)
    assert abs(store["ouvertes"]["copy_vault:SOL"]["notional_usd"] - 30.0) < 1e-6, "réduction successive depuis l'INITIAL"
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, -5.0, ts=NOW + 2, snap_id="sflip")])  # FLIP
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 2000)
    assert "copy_vault:SOL" not in store["ouvertes"], "un FLIP de signe FERME la position (jamais 'aucun changement')"


def test_P2_classifie_signe_add_reduce_close_flip():
    c = EP.classifier_changement_leader
    assert c(entry_szi=10, current_szi=8, last_applied_szi=10) == "REDUCE"       # −20 %
    assert c(entry_szi=10, current_szi=12, last_applied_szi=10) == "ADD"
    assert c(entry_szi=10, current_szi=0, last_applied_szi=10) == "CLOSE"
    assert c(entry_szi=10, current_szi=-3, last_applied_szi=8) == "FLIP_LONG_SHORT"
    assert c(entry_szi=-10, current_szi=4, last_applied_szi=-8) == "FLIP_SHORT_LONG"


# ══════════════ P3 — snapshot_complet_ok branché dans le runtime ══════════════
def test_P3_snapshot_incomplet_ou_perime_ne_cloture_pas(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0)
    _bidask_sol(tmp_path)
    # incomplet + coin absent -> AUCUNE clôture
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, complet=False, snap_id="i1")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert "copy_vault:SOL" in store["ouvertes"], "snapshot incomplet -> on NE ferme PAS"
    # périmé (trop vieux) -> AUCUNE clôture
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, ts=NOW - 10 * 3.6e6, snap_id="old")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert "copy_vault:SOL" in store["ouvertes"], "snapshot périmé -> on NE ferme PAS"
    # antérieur à l'entrée -> AUCUNE clôture
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, ts=NOW - 50_000, snap_id="ant")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert "copy_vault:SOL" in store["ouvertes"], "snapshot antérieur à l'entrée -> on NE ferme PAS"


def test_P3_snapshot_frais_complet_coin_absent_ferme(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0)
    _bidask_sol(tmp_path)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, snap_id="flat")])   # complet + coin absent = flat
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    assert "copy_vault:SOL" not in store["ouvertes"], "snapshot frais+complet, leader flat -> CLOSE autorisé"


# ══════════════ P4 — coût d'entrée réparti sur les REDUCE ══════════════
def test_P4_reduce_impute_le_cout_entree_de_la_tranche(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0, notional=100.0)
    pos = store["ouvertes"]["copy_vault:SOL"]
    entry_cost0 = pos["entry_cost_remaining_usd"]
    assert entry_cost0 > 0
    _bidask_sol(tmp_path)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 6.0, snap_id="r6")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    pos = store["ouvertes"]["copy_vault:SOL"]
    # 40 % fermé -> ~40 % du coût d'entrée alloué ; le résidu du coût d'entrée baisse ; le cumul l'enregistre
    assert pos["cumulative_entry_cost_allocated_usd"] > 0
    assert pos["entry_cost_remaining_usd"] < entry_cost0
    ligne = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines() if '"REDUCE"' in x][0]
    assert ligne["entry_cost_allocated_usd"] > 0 and ligne["exit_cost_usd"] > 0


# ══════════════ P5 — resume() = CLOSE + REDUCE, réconcilié ══════════════
def test_P5_resume_compte_reduce_et_close_et_reconcilie(tmp_path):
    store = _pos_copy(tmp_path, entry_szi=10.0, notional=100.0)
    _bidask_sol(tmp_path)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 5.0, snap_id="r5")])       # REDUCE
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    MP.sauver_store(tmp_path, store)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, ts=NOW + 1, snap_id="c0")])  # CLOSE
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 1000)
    MP.sauver_store(tmp_path, store)
    res = MP.resume(tmp_path)                                                   # VRAI resume
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    kinds = [x.get("kind") for x in lignes]
    assert "REDUCE" in kinds and "CLOSE" in kinds
    audit = REC.auditer(lignes, realise_store_usd=res["realise_total_usd"], realise_statut_usd=res["realise_total_usd"])
    assert audit["coherent"] is True, "ledger == resume == réconciliation"


# ══════════════ P6 — DATA_MISSING ne fabrique pas de convergence ══════════════
def test_P6_data_missing_sans_jambes_reste_non_liquidable(tmp_path):
    store = MP.charger_store(tmp_path)
    sig = MP.Signal(moteur="cross_venue", coin="DOT", sens=1, type_pnl="dislocation", notional_usd=100.0,
                    prix_entree=100.0, cout_entree_bps=8.0, edge_estime_bps=40.0, ts_signal_ms=NOW - 1000,
                    roi_annuel_pct=None, pnl_attendu_usd=0.4, hold_h=0.5, base_entree_bps=40.0,
                    meta={"gap_entree_bps": 40.0})
    pos = MP.ouvrir(sig, store, tmp_path, now_ms=NOW - 300_000)   # ouvert il y a 5 min -> au-delà de la grâce
    pos["ts_derniere_donnee_ms"] = NOW - 300_000
    MP.sauver_store(tmp_path, store)
    # AUCUN carnet écrit -> donnée manquante
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    # Sans les deux jambes d'entrée réconciliables, on ne publie AUCUN realized.
    # La position reste ouverte et explicitement non-liquidatable plutôt que de
    # fabriquer un close agrégé/mono-jambe.
    assert not [x for x in lignes if x.get("kind") == "CLOSE"]
    assert pos["position_id"] in store["ouvertes"]
    assert pos["liquidation_status"] == "UNLIQUIDATABLE_DATA_MISSING"
    assert "ENTRY_LEGS_UNAVAILABLE" in pos["liquidation_reason"]


# ══════════════ P7 — deux jambes réellement câblées au runner ══════════════
def test_P7_dislocation_ferme_en_deux_jambes(tmp_path):
    store = MP.charger_store(tmp_path)
    jambes_meta = {"hl": {"prix_exec": 100.0, "frais_bps": 2.0, "slippage_bps": 1.0},
                   "bin": {"prix_exec": 101.0, "frais_bps": 2.0, "slippage_bps": 1.0}}
    sig = MP.Signal(moteur="cross_venue", coin="DOT", sens=1, type_pnl="dislocation", notional_usd=100.0,
                    prix_entree=100.0, cout_entree_bps=8.0, edge_estime_bps=40.0, ts_signal_ms=NOW - 1000,
                    roi_annuel_pct=None, pnl_attendu_usd=0.4, hold_h=0.5, base_entree_bps=40.0,
                    meta={"gap_entree_bps": 40.0, "jambes": jambes_meta})
    MP.ouvrir(sig, store, tmp_path, now_ms=NOW - 60_000)
    MP.sauver_store(tmp_path, store)
    # carnet convergé (l'écart s'est refermé) -> CONVERGENCE_CAPTUREE -> fermeture DEUX JAMBES
    _ecrire(_data(tmp_path) / "carnet_venues.jsonl", [
        {"coin": "DOT", "hl_bid": 100.4, "hl_ask": 100.5, "bin_bid": 100.5, "bin_ask": 100.6,
         "taille_min_usd": 5000.0, "collecte_ts": NOW / 1000.0}])
    R._gerer_sorties(store, tmp_path, now_ms=NOW)
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    close = [x for x in lignes if x.get("kind") == "CLOSE"][0]
    assert close.get("n_jambes") == 2 and len(close.get("jambes") or []) == 2, "le ledger porte les DEUX jambes"
    total = round(sum(j["realized_usd"] for j in close["jambes"]), 6)
    assert close["realized_net_pnl_usdc"] == total, "realized total = somme EXACTE des deux jambes"


# ══════════════ P8 — fraîcheur des prix et des signaux ══════════════
def test_P8_trade_vieux_est_stale(tmp_path):
    _fixture_lead_lag(tmp_path, trade_ms=NOW - 60_000)                          # trade vieux de 60 s
    sigs, refus = S.signaux_lead_lag(tmp_path, now_ms=NOW)
    assert not sigs and any(r.get("motif") == "STALE_SIGNAL" for r in refus)


def test_P8_trade_futur_est_clock_skew(tmp_path):
    _fixture_lead_lag(tmp_path, trade_ms=NOW + 10_000)                          # trade dans le futur
    sigs, refus = S.signaux_lead_lag(tmp_path, now_ms=NOW)
    assert not sigs and any(r.get("motif") == "CLOCK_SKEW_FUTURE_DATA" for r in refus)


def test_P8_snapshot_vault_vieux_est_stale(tmp_path):
    # les DEUX snapshots sont vieux (le plus récent daté à −60 s) -> le signal serait tardif -> STALE_SIGNAL
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [
        {"vault": "0xabc", "ts_ms": int(NOW - 90_000), "nav_usd": 100000.0,
         "positions": [{"coin": "SOL", "szi": 0.0, "entryPx": 100.0}]},
        {"vault": "0xabc", "ts_ms": int(NOW - 60_000), "nav_usd": 100000.0,
         "positions": [{"coin": "SOL", "szi": 100.0, "entryPx": 100.0}]}])
    (_data(tmp_path) / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xabc"]}))
    sigs, refus = S.signaux_vaults(tmp_path, now_ms=NOW, lecteur_l2=_lecteur_l2, edge_par_coin=_edge_par_coin())
    assert not sigs and any(r.get("motif") == "STALE_SIGNAL" for r in refus)


def test_P8_admettre_refuse_horodatage_futur():
    sig = MP.Signal(moteur="lead_lag", coin="SOL", sens=1, type_pnl="directional", notional_usd=50.0,
                    prix_entree=100.0, cout_entree_bps=4.0, edge_estime_bps=20.0, ts_signal_ms=NOW + 10_000,
                    roi_annuel_pct=50.0, pnl_attendu_usd=0.5, hold_h=1.0)
    assert MP.admettre(sig, {"ouvertes": {}}, now_ms=NOW)[1] == "CLOCK_SKEW_FUTURE_DATA"


# ══════════════ P9 — réconciliation par position_id (épisodes séparés) ══════════════
def test_P9_deux_episodes_meme_coin_sont_separes(tmp_path):
    store = MP.charger_store(tmp_path)
    for i in range(2):                                                          # deux épisodes successifs sur SOL
        sig = MP.Signal(moteur="lead_lag", coin="SOL", sens=1, type_pnl="directional", notional_usd=50.0,
                        prix_entree=100.0, cout_entree_bps=4.0, edge_estime_bps=20.0, ts_signal_ms=NOW,
                        roi_annuel_pct=50.0, pnl_attendu_usd=0.5, hold_h=1.0)
        pos = MP.ouvrir(sig, store, tmp_path, now_ms=NOW + i)
        MP.sortir(pos, store, tmp_path, prix_sortie=101.0, cout_sortie_bps=4.0, raison="TEST", now_ms=NOW + i + 1)
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    par = REC.realized_par_position(lignes)
    assert len(par) == 2, "deux épisodes du même moteur:coin -> DEUX clés position_id distinctes"
    pids = {x.get("position_id") for x in lignes if x.get("kind") == "OPEN"}
    assert len(pids) == 2 and None not in pids


# ══════════════ P11 — bout-en-bout déterministe ══════════════
def test_P11_bout_en_bout_reduce_puis_close(tmp_path):
    _fixture_vaults(tmp_path)
    sigs, _ = S.signaux_vaults(tmp_path, now_ms=NOW, lecteur_l2=_lecteur_l2, edge_par_coin=_edge_par_coin())
    assert sigs
    store = MP.charger_store(tmp_path)
    ok, motif = MP.admettre(sigs[0], store, now_ms=NOW)
    assert ok, motif
    pos = MP.ouvrir(sigs[0], store, tmp_path, now_ms=NOW)
    assert pos["roi_annuel_pct"] is not None, "ROI ne reste PAS à zéro par défaut"
    MP.sauver_store(tmp_path, store)
    _bidask_sol(tmp_path)
    # le leader réduit de moitié -> REDUCE (idempotent), puis clôt -> CLOSE
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 50.0, ts=NOW + 1, snap_id="e1")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 1000)
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 2000)                        # MÊME snapshot -> pas de double REDUCE
    n_reduce = sum(1 for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines() if '"REDUCE"' in x)
    assert n_reduce == 1, "le même snapshot ne réduit qu'une fois"
    MP.sauver_store(tmp_path, store)
    _ecrire(_data(tmp_path) / "vault_snapshots.jsonl", [_snap(tmp_path, 0.0, ts=NOW + 3, snap_id="e2")])
    R._gerer_sorties(store, tmp_path, now_ms=NOW + 3000)
    MP.sauver_store(tmp_path, store)                                            # persister l'état après le CLOSE
    res = MP.resume(tmp_path)
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    audit = REC.auditer(lignes, realise_store_usd=res["realise_total_usd"], realise_statut_usd=res["realise_total_usd"])
    assert audit["coherent"] and res["positions_ouvertes"] == 0
    assert res["real_execution"] is False


# ══════════════ P10 — registre branché à DSR/PBO (tous les essais, KILL compris) ══════════════
def test_P10_registre_preregistration_resultat_et_dsr_pbo(tmp_path):
    from hl_observer.experimental import campagne_registre as CR
    from hl_observer.experimental import registre_essais as REG
    fam = "OFI"
    variantes = {"top1": "KILL", "top5": "KILL", "microprix": "KILL"}
    for v, verdict in variantes.items():
        CR.preenregistrer(tmp_path, family=fam, variant=v, params={"v": v}, data_cutoff="2026-07-20")
    # exécution simulée -> résultat SÉPARÉ par variante (append-only), TOUS KILL ici
    sharpes = {"top1": -0.3, "top5": 0.1, "microprix": -0.2}
    for v, verdict in variantes.items():
        CR.enregistrer_resultat(tmp_path, family=fam, variant=v, params={"v": v},
                                sharpe=sharpes[v], result=verdict, pass_kill=verdict)
    # ré-enregistrer un résultat -> NOUVELLE ligne (jamais d'écrasement)
    CR.enregistrer_resultat(tmp_path, family=fam, variant="top1", params={"v": "top1"},
                            sharpe=-0.35, result="KILL", pass_kill="KILL")
    essais = REG.charger(tmp_path)
    preregs = [e for e in essais if e.get("phase") == "preregistration"]
    resultats = [e for e in essais if e.get("phase") == "resultat"]
    assert len(preregs) == 3 and len(resultats) == 4, "préreg intactes + résultats append-only (aucun écrasement)"
    sh = REG.sharpes_tous_essais(resultats, family=fam)
    assert len(sh) == 4 and -0.35 in sh, "le DSR reçoit TOUS les résultats (KILL compris)"
    # jugement : DSR déflaté par tous les Sharpe + PBO CSCV sur les variantes
    import random
    rng = random.Random(1)
    perf = {v: [rng.gauss(0, 1) for _ in range(16)] for v in variantes}         # bruit -> ne survit pas OOS
    rap = CR.juger_famille(tmp_path, family=fam, nets_gagnante=[rng.gauss(0, 1) for _ in range(20)], perf_par_variante=perf)
    assert rap["n_preregistrations"] == 3 and rap["n_resultats"] == 4 and rap["n_sharpes_dsr"] == 4
    assert rap["pbo"] is not None and rap["dsr"].get("n_essais") == 4
    assert rap["verdict"] in ("ARM", "SHADOW_OU_KILL")


def test_P11_securite_zero_execution_reelle(tmp_path):
    _fixture_vaults(tmp_path)
    sigs, _ = S.signaux_vaults(tmp_path, now_ms=NOW, lecteur_l2=_lecteur_l2, edge_par_coin=_edge_par_coin())
    store = MP.charger_store(tmp_path)
    MP.ouvrir(sigs[0], store, tmp_path, now_ms=NOW)
    lignes = [json.loads(x) for x in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    assert all(x["mode"] == "EXPERIMENTAL_PAPER" and x["real_execution"] is False for x in lignes)
