"""Cohorte EXPLORATORY_PAPER (décision Flo 23/07) : ouvre sur un VRAI mouvement live d'un vault retenu
avec edge PRÉLIMINAIRE positif, L2<1s, VWAP, coûts, sortie définie. Isolée : budget $300, max 3,
pertes plafonnées. Aucun signal synthétique, aucun trade forcé, aucune exécution réelle."""
from __future__ import annotations

import json

from hl_observer.experimental import exploratoire as EX
from hl_observer.experimental import moteur_paper as MP


def _setup(root, *, move_szi=200.0, prelim=True, retenu="0xAAA", now=1_000_000_000_000.0):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "frais_venues.json").write_text(json.dumps({"hl_taker_bps": 3.5, "bin_taker_bps": 4.5}))
    (root / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": [retenu],
        "classement": [{"vault": retenu, "retenu": True,
                        "facteurs": {"anciennete_j": 300, "drawdown_pct": 10, "copyabilite": 1.0}}]}))
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text("\n".join(json.dumps(s) for s in [
        {"vault": "0xAAA", "ts_ms": now - 300_000, "nav_usd": 100_000, "positions": [{"coin": "HYPE", "szi": 0.0, "entryPx": 20.0}]},
        {"vault": "0xAAA", "ts_ms": now - 5_000, "nav_usd": 100_000, "positions": [{"coin": "HYPE", "szi": move_szi, "entryPx": 20.0}]},
    ]))
    (root / "runtime" / "data" / "carnet_venues.jsonl").write_text(json.dumps(
        {"coin": "HYPE", "hl_bid": 19.99, "hl_ask": 20.01, "taille_min_usd": 5000.0, "collecte_ts": now / 1000.0}))
    if prelim:
        (root / "runtime" / "data" / "copy_prelim_edge.json").write_text(json.dumps(
            {"table": {"HYPE": {"edge_brut_bps": 35.0, "horizon_ms": 900_000.0, "net_bps": 23.0}}}))


def test_construire_table_prelim_garde_positifs_seulement():
    from hl_observer.experimental.copy_edge_oos import construire_table_prelim
    ev = [{"ts_ms": i, "coin": "WIN", "direction": 1, "move_frac": 0.1} for i in range(30)] \
        + [{"ts_ms": i, "coin": "LOSE", "direction": 1, "move_frac": 0.1} for i in range(30)]
    tape = {"WIN": [(i, 100.0 + i) for i in range(200)],            # monte -> net positif
            "LOSE": [(i, 100.0 - 0.001 * i) for i in range(200)]}   # descend -> net négatif
    t = construire_table_prelim(ev, tape, horizons_ms=(5.0,), frais_bps=1.0, min_events=10)
    assert "WIN" in t and "LOSE" not in t and t["WIN"]["net_bps"] > 0


def test_exploratoire_ouvre_sur_move_live_et_edge_prelim(tmp_path):
    now = 1_000_000_000_000.0
    _setup(tmp_path)
    r = EX.tick(tmp_path, now_ms=now)
    assert len(r["ouvertures"]) == 1
    st = r["statut"]
    assert st["positions_ouvertes"] == 1 and st["real_execution"] is False and st["mode"] == "EXPLORATORY_PAPER"
    pos = st["positions"][0]
    assert pos["coin"] == "HYPE" and pos["vault"] == "0xAAA" and pos["prix_entree"] == 20.01   # ask L2 réel
    assert st["cash"] < EX.BUDGET_TOTAL_USD                          # budget isolé décrémenté
    # ledger ISOLÉ + estampillé EXPLORATORY, jamais réel
    lignes = [json.loads(l) for l in (tmp_path / EX.LEDGER_RELPATH).read_text().splitlines()]
    assert lignes and all(x["mode"] == "EXPLORATORY_PAPER" and x["real_execution"] is False for x in lignes)


def test_sans_edge_prelim_positif_aucune_ouverture(tmp_path):
    now = 1_000_000_000_000.0
    _setup(tmp_path, prelim=False)                                   # pas de table prélim -> deny
    r = EX.tick(tmp_path, now_ms=now)
    assert not r["ouvertures"] and r["refus_par_motif"].get("EDGE_PRELIM_ABSENT", 0) >= 1


def test_limite_3_positions(tmp_path):
    now = 1_000_000_000_000.0
    _setup(tmp_path)
    store = EX.charger_store(tmp_path)
    for c in ("A", "B", "C"):                                        # 3 positions déjà ouvertes
        store["ouvertes"][c] = {"coin": c, "notional_usd": 60.0}
    sig = MP.Signal(moteur="copy_vault", coin="HYPE", sens=1, type_pnl="directional", notional_usd=60.0,
                    prix_entree=20.0, cout_entree_bps=5.0, edge_estime_bps=20.0, ts_signal_ms=now)
    assert EX.admettre(sig, store) == (False, "LIMITE_3_POSITIONS")


def test_tiers_core_et_challengers(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xCORE1", "0xCORE2"],
        "classement": [
            {"vault": "0xCORE1", "retenu": True, "facteurs": {}},
            {"vault": "0xCORE2", "retenu": True, "facteurs": {}},
            {"vault": "0xCHAL", "retenu": False, "facteurs": {"anciennete_j": 200, "drawdown_pct": 20, "copyabilite": 0.8}},
            {"vault": "0xJEUNE", "retenu": False, "facteurs": {"anciennete_j": 5, "drawdown_pct": 20, "copyabilite": 0.8}}]}))
    core, chal = EX.tiers(tmp_path)
    assert core == {"0xCORE1", "0xCORE2"} and chal == {"0xCHAL"}     # 0xJEUNE recalé (trop jeune)


def test_take_profit_declenche_sortie(tmp_path):
    now = 1_000_000_000_000.0
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    pos = {"coin": "HYPE", "moteur": "copy_vault_explo", "sens": 1, "type_pnl": "directional",
           "notional_usd": 60.0, "prix_entree": 20.0, "ts_ouverture_ms": now, "hold_h": 1.0,
           "spread_bps": 1.0, "frais_bps": 3.5, "slippage_bps": 1.0, "meta": {"stop_bps": 20.0, "take_profit_bps": 15.0}}
    # +0,3 % = +30 bps >= TP 15 -> TAKE_PROFIT
    raison, _ = EX._raison_sortie(pos, tmp_path, now_ms=now + 1000, mark=20.0 * 1.003)
    assert raison == "TAKE_PROFIT"


def test_stop_perte_declenche_sortie(tmp_path):
    now = 1_000_000_000_000.0
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    pos = {"coin": "HYPE", "moteur": "copy_vault_explo", "sens": 1, "type_pnl": "directional",
           "notional_usd": 60.0, "prix_entree": 20.0, "ts_ouverture_ms": now, "hold_h": 1.0,
           "spread_bps": 1.0, "frais_bps": 3.5, "slippage_bps": 1.0, "meta": {}}
    # prix chute 4 % -> PnL ~ -2,4$ < -STOP_PERTE_USD (0,90) -> STOP_PERTE
    raison, cout = EX._raison_sortie(pos, tmp_path, now_ms=now + 1000, mark=20.0 * 0.96)
    assert raison == "STOP_PERTE" and cout > 0
