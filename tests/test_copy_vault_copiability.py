"""Tests à vérité connue de l'étude de copiabilité Copy-Vault (PAPER / READ-ONLY)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from hl_observer.backtesting import copy_vault_copiability as cop

T0 = 1_794_000_000_000  # instant de référence (ms)


def _fill(vault, coin, t_s, side, px, sz, start, direction, *, lag_s=60.0, crossed=True, tid=None, **extra):
    time = T0 + int(t_s * 1000)
    row = {
        "vault": vault, "coin": coin, "time": time, "observed_at_ms": time + int(lag_s * 1000),
        "side": side, "px": px, "sz": sz, "startPosition": str(start), "dir": direction,
        "closedPnl": "0", "crossed": crossed, "fee": "0.01", "tid": tid if tid is not None else time % 10**9,
        "oid": 1, "isSnapshot": False,
    }
    row.update(extra)
    return row


def _prepared(rows):
    frame, unreadable = cop.fills_frame_from_rows(rows)
    fills, rejects = cop.prepare_fills(frame)
    return fills, {**unreadable, **rejects}


def _panel(prices_by_second, coin="BTC", step_s=1):
    snapshots = [(T0 + int(s * 1000), {coin: p}) for s, p in prices_by_second]
    return cop.build_mid_panel(snapshots, stale_ms=10_000)


def test_prepare_fills_rejette_et_compte_sans_perte_silencieuse():
    rows = [
        _fill("0xA", "BTC", 10, "B", 100.0, 1.0, 0, "Open Long", tid=1),
        _fill("0xA", "BTC", 10, "B", 100.0, 1.0, 0, "Open Long", tid=1, lag_s=5.0),  # doublon, vu plus tôt
        _fill("0xA", "BTC", 20, "B", 100.0, 1.0, 0, "Open Long", tid=2, isSnapshot=True),
        _fill("0xA", "BTC", 30, "B", 100.0, 1.0, 0, "Buy", tid=3),  # spot : hors périmètre
        _fill("0xA", "BTC", 40, "B", 100.0, 1.0, 0, "Open Long", tid=4, lag_s=-30.0),  # vu avant d'exister
        _fill("0xA", "BTC", 50, "X", 100.0, 1.0, 0, "Open Long", tid=5),
        _fill("0xA", "BTC", 60, "B", 0.0, 1.0, 0, "Open Long", tid=6),
        {"vault": "0xA", "coin": "BTC", "time": "pas-un-entier", "observed_at_ms": 1},
    ]
    fills, rejects = _prepared(rows)
    assert len(fills) == 1
    assert int(fills["obs"].iloc[0] - fills["time"].iloc[0]) == 5_000  # première observation conservée
    assert rejects == {
        "horodatage_invalide": 1, "snapshot_non_causal": 1, "direction_non_directionnelle": 1,
        "observation_avant_evenement": 1, "sens_inconnu": 1, "prix_ou_taille_invalide": 1,
        "doublon_identite": 1,
    }
    assert sum(rejects.values()) + len(fills) == len(rows)


def test_panel_ne_lit_jamais_le_futur_et_refuse_un_prix_perime():
    panel = _panel([(0, 100.0), (5, 101.0), (60, 150.0)])
    col = panel.column("BTC")
    got = panel.at(np.array([T0 - 1, T0, T0 + 4_999, T0 + 5_000, T0 + 15_001, T0 + 59_999]), col)
    assert math.isnan(got[0])                     # rien de connu avant le premier prix
    assert got[1] == 100.0 and got[2] == 100.0    # le prix de t=5 s est invisible à t=4,999 s
    assert got[3] == 101.0
    assert math.isnan(got[4]) and math.isnan(got[5])  # périmé : inconnu, jamais reporté ni mis à 0


def test_decroissance_information_consommee_avant_observation():
    """Le prix saute de +10 bps 5 s après chaque achat taker ; observé 60 s plus tard il ne reste rien."""
    rows, prices = [], []
    price = 100.0
    for i in range(300):
        base = i * 200
        for s in range(200):
            prices.append((base + s, price * (1.001 if s >= 5 else 1.0)))
        rows.append(_fill("0xA", "BTC", base, "B", price, 1.0, 0, "Open Long", tid=2 * i + 1))
        rows.append(_fill("0xA", "BTC", base + 100, "A", price * 1.001, 1.0, 1.0, "Close Long", tid=2 * i + 2, crossed=False))
        price *= 1.001
    fills, _ = _prepared(rows)
    cfg = cop.CopiabilityConfig(min_fills_per_unit=50, horizons_s=(15, 60))
    decay = cop.decay_curves(fills, _panel(prices), {}, cfg)
    taker = decay["segments"]["TAKER_OPEN"]["metrics"]
    assert taker["from_fill_15s"]["mean"] == pytest.approx(10.0, abs=0.01)
    assert taker["pre_observation_bps"]["mean"] == pytest.approx(10.0, abs=0.01)
    assert taker["from_observation_15s"]["mean"] == pytest.approx(0.0, abs=0.01)
    assert taker["from_observation_60s"]["mean"] == pytest.approx(0.0, abs=0.01)


def test_episodes_ouverture_ajout_inversion_et_entree_inconnue():
    rows = [
        # 0xA : position préexistante (entrée jamais vue) -> ces fills ne forment aucun épisode
        _fill("0xA", "ETH", 1, "A", 10.0, 2.0, 5.0, "Close Long", tid=1),
        _fill("0xA", "ETH", 2, "A", 10.0, 3.0, 3.0, "Close Long", tid=2),
        # puis ouverture, ajout, clôture
        _fill("0xA", "ETH", 10, "B", 10.0, 1.0, 0.0, "Open Long", tid=3),
        _fill("0xA", "ETH", 20, "B", 10.0, 1.0, 1.0, "Open Long", tid=4),
        _fill("0xA", "ETH", 30, "A", 11.0, 2.0, 2.0, "Close Long", tid=5),
        # inversion : long 1 -> short 1, puis toujours ouvert en fin de données
        _fill("0xA", "ETH", 40, "B", 10.0, 1.0, 0.0, "Open Long", tid=6),
        _fill("0xA", "ETH", 50, "A", 12.0, 2.0, 1.0, "Long > Short", tid=7),
    ]
    fills, _ = _prepared(rows)
    episodes = cop.reconstruct_episodes(fills)
    assert len(episodes) == 3
    first, second, third = (episodes.iloc[i] for i in range(3))
    assert (first["direction"], first["fills"], bool(first["closed"])) == (1, 3, True)
    assert first["open_time"] == T0 + 10_000 and first["close_time"] == T0 + 30_000
    assert (second["direction"], bool(second["closed"])) == (1, True)
    assert second["close_time"] == T0 + 50_000          # clos par le fill d'inversion
    assert (third["direction"], bool(third["closed"])) == (-1, False)


def test_episode_fill_orphelin_apres_rupture_de_continuite_est_exclu():
    rows = [
        _fill("0xA", "ETH", 10, "B", 10.0, 1.0, 0.0, "Open Long", tid=1),
        _fill("0xA", "ETH", 20, "A", 10.0, 1.0, 1.0, "Close Long", tid=2),
        # ouverture manquée par la collecte : la position repart de 4 sans fill d'ouverture
        _fill("0xA", "ETH", 90, "A", 10.0, 4.0, 4.0, "Close Long", tid=3),
    ]
    fills, _ = _prepared(rows)
    episodes = cop.reconstruct_episodes(fills)
    assert len(episodes) == 1
    assert episodes.iloc[0]["close_time"] == T0 + 20_000 and episodes.iloc[0]["fills"] == 2


def test_copie_miroir_couts_abstention_et_inconnus_jamais_a_zero():
    prices = [(s, 100.0) for s in range(0, 100)] + [(s, 101.0) for s in range(100, 400)]
    rows = [
        # épisode copiable : ouvert à 10 s (vu à 70 s), fermé à 200 s (vu à 260 s) ; +100 bps bruts
        _fill("0xA", "BTC", 10, "B", 100.0, 1.0, 0.0, "Open Long", tid=1),
        _fill("0xA", "BTC", 200, "A", 101.0, 1.0, 1.0, "Close Long", tid=2),
        # épisode de 5 s vu dans le MÊME relevé (ouverture et clôture observées à 360 s) :
        # le leader est déjà sorti quand l'ouverture devient observable -> abstention
        _fill("0xA", "BTC", 300, "B", 101.0, 1.0, 0.0, "Open Long", tid=3),
        _fill("0xA", "BTC", 305, "A", 101.0, 1.0, 1.0, "Close Long", tid=4, lag_s=55.0),
        # coin sans spread mesuré : coût inconnu
        _fill("0xA", "DOGE", 10, "B", 1.0, 1.0, 0.0, "Open Long", tid=5),
        _fill("0xA", "DOGE", 200, "A", 1.0, 1.0, 1.0, "Close Long", tid=6),
        # position encore ouverte en fin de données : aucun PnL réalisé
        _fill("0xB", "BTC", 250, "B", 101.0, 1.0, 0.0, "Open Long", tid=7),
    ]
    fills, _ = _prepared(rows)
    snapshots = [(T0 + s * 1000, {"BTC": p, "DOGE": 1.0}) for s, p in prices]
    panel = cop.build_mid_panel(snapshots)
    cfg = cop.CopiabilityConfig(taker_fee_bps=4.5, reaction_delay_ms=2_000)
    episodes, summary = cop.mirror_copy_episodes(cop.reconstruct_episodes(fills), panel, {"BTC": 1.0}, {}, cfg)
    by_status = {row["status"]: row for _, row in episodes.iterrows()}
    copied = by_status["COPIED"]
    assert copied["gross_bps"] == pytest.approx(100.0, abs=1e-6)
    assert copied["cost_bps"] == pytest.approx(2 * 4.5 + 2 * 1.0)
    assert copied["net_bps"] == pytest.approx(89.0, abs=1e-6)
    assert set(by_status) == {"COPIED", "ALREADY_CLOSED_AT_OBSERVATION", "UNMEASURABLE_COST", "OPEN_AT_END"}
    for status in ("ALREADY_CLOSED_AT_OBSERVATION", "UNMEASURABLE_COST", "OPEN_AT_END"):
        assert math.isnan(by_status[status]["net_bps"])  # inconnu ou non réalisé : jamais 0
    assert summary["copied"]["episodes"] == 1
    assert summary["closed_before_observation_share"] == pytest.approx(1 / 3)


def test_attribution_sans_avance_le_copieur_ne_porte_rien_avant_d_observer():
    """Le leader détient 10 BTC dès le départ ; le prix monte AVANT notre première observation."""
    prices = [(s, 100.0 + (s >= 50) * 5.0) for s in range(0, 400)]  # +5 USD à t=50 s
    rows = [_fill("0xA", "BTC", 100, "A", 105.0, 1.0, 10.0, "Close Long", tid=1, lag_s=60.0)]  # vu à 160 s
    fills, _ = _prepared(rows)
    cfg = cop.CopiabilityConfig(rebalance_minutes=(1,), reaction_delay_ms=0)
    report = cop.attribute_pnl(fills, _panel(prices), {"BTC": 1.0}, {}, cfg)
    leader = report["leaders"][0]
    assert leader["inventory_true_usd"] == pytest.approx(50.0)   # 10 BTC x 5 USD, information parfaite
    assert leader["inventory_k1_usd"] == pytest.approx(0.0)      # le copieur ignorait cette position
    # à l'observation le copieur passe de 0 à 9 BTC : rotation 9 x 105 USD, coût (4,5 + 1) bps
    assert leader["turnover_k1_usd"] == pytest.approx(9 * 105.0)
    assert leader["cost_k1_usd"] == pytest.approx(9 * 105.0 * 5.5e-4)
    assert leader["net_k1_usd"] == pytest.approx(-9 * 105.0 * 5.5e-4)


def test_attribution_execution_separee_de_l_inventaire_et_cout_inconnu_exclu():
    prices = [(s, 100.0) for s in range(0, 200)]
    rows = [
        _fill("0xM", "BTC", 10, "B", 99.9, 1.0, 0.0, "Open Long", tid=1, crossed=False),   # achète sous le mid
        _fill("0xM", "BTC", 20, "A", 100.1, 1.0, 1.0, "Close Long", tid=2, crossed=False),  # vend au-dessus
    ]
    fills, _ = _prepared(rows)
    cfg = cop.CopiabilityConfig(rebalance_minutes=(1,))
    known = cop.attribute_pnl(fills, _panel(prices), {"BTC": 1.0}, {}, cfg)["leaders"][0]
    assert known["execution_usd"] == pytest.approx(0.2)         # capture de spread : non copiable
    assert known["inventory_true_usd"] == pytest.approx(0.0)    # prix plat : aucun PnL d'inventaire
    unknown = cop.attribute_pnl(fills, _panel(prices), {}, {}, cfg)["leaders"][0]
    assert unknown["cost_k1_usd"] == 0.0
    assert unknown["unmeasured_turnover_k1_usd"] == unknown["turnover_k1_usd"]  # tracé, pas supposé gratuit


def test_resultats_passes_insensibles_aux_prix_futurs():
    """Garde anti-fuite : modifier les prix après le dernier instant utilisé ne change rien."""
    rows = [
        _fill("0xA", "BTC", 10, "B", 100.0, 1.0, 0.0, "Open Long", tid=1, lag_s=5),
        _fill("0xA", "BTC", 60, "A", 100.5, 1.0, 1.0, "Close Long", tid=2, lag_s=5),
    ]
    fills, _ = _prepared(rows)
    base = [(s, 100.0 + 0.01 * s) for s in range(0, 120)]
    future_a = base + [(s, 500.0) for s in range(120, 200)]
    future_b = base + [(s, 1.0) for s in range(120, 200)]
    cfg = cop.CopiabilityConfig(horizons_s=(5, 15))
    out = []
    for prices in (future_a, future_b):
        panel = _panel(prices)
        episodes, _ = cop.mirror_copy_episodes(cop.reconstruct_episodes(fills), panel, {"BTC": 1.0}, {}, cfg)
        out.append(float(episodes["net_bps"].iloc[0]))
    assert out[0] == out[1]


def test_grappes_sybil_fusionnent_les_clones_pas_les_independants():
    rows = []
    rng = np.random.default_rng(7)
    minutes = rng.choice(5_000, size=600, replace=False)
    for n, m in enumerate(minutes):
        for clone in ("0xC1", "0xC2"):
            rows.append(_fill(clone, "BTC", int(m) * 60 + (clone == "0xC2"), "B", 100.0, 1.0, 0.0, "Open Long", tid=n))
    for n, m in enumerate(rng.choice(np.arange(5_000, 10_000), size=600, replace=False)):
        rows.append(_fill("0xIND", "BTC", int(m) * 60, "B", 100.0, 1.0, 0.0, "Open Long", tid=10_000 + n))
    fills, _ = _prepared(rows)
    units = cop.detect_sybil_clusters(fills)
    assert units["0xc1"] == units["0xc2"] == "0xc1"
    assert units["0xind"] == "0xind"


def _attribution(net_by_unit_day, exposure=10_000.0):
    net = np.asarray(net_by_unit_day, dtype=float)
    n_units, n_days = net.shape
    zeros = np.zeros_like(net)
    return {
        "status": "MEASURED", "market_hours": 24.0 * n_days, "days": list(range(n_days)),
        "day_hours": [24.0] * n_days, "unit_names": [f"u{i}" for i in range(n_units)],
        "daily": {
            "inventory_k60_usd": net, "cost_k60_usd": zeros, "turnover_k60_usd": zeros + 1.0,
            "unmeasured_turnover_k60_usd": zeros, "exposure_usd_hours": zeros + exposure * 24.0,
        },
    }


def test_persistance_refuse_de_conclure_sans_jours_independants():
    report = cop.slow_replication_persistence(_attribution(np.ones((12, 3)) * 5.0), 60)
    assert report["status"] == "MORE_DATA" and report["usable_days"] == 3
    assert "jour" in report["reason"]


def test_persistance_distingue_competence_persistante_et_absence_d_avantage():
    days = 40
    rng = np.random.default_rng(3)
    noise = rng.normal(0.0, 1.0, size=(12, days))
    skilled = np.vstack([np.full((6, days), 8.0), np.full((6, days), -8.0)]) + noise
    assert cop.slow_replication_persistence(_attribution(skilled), 60)["status"] == "PROMISING"
    # gagnants d'hier perdants demain : la sélection sur le passé ne vaut rien
    sign = np.where(np.arange(days) % 2 == 0, 1.0, -1.0)
    reverting = np.vstack([np.tile(8.0 * sign, (6, 1)), np.tile(-8.0 * sign, (6, 1))])
    assert cop.slow_replication_persistence(_attribution(reverting), 60)["status"] != "PROMISING"


def test_verdict_suivi_rapide_rejete_si_la_derive_reste_sous_les_frais():
    cfg = cop.CopiabilityConfig(horizons_s=(15, 60), taker_fee_bps=4.5)

    def decay(high):
        metric = {"units": 30, "mean": 0.5, "median": 0.4, "ci95": [-1.0, high], "share_positive": 0.5}
        metrics = {f"from_observation_{h}s": metric for h in cfg.horizons_s}
        metrics["pre_observation_bps"] = {**metric, "mean": 6.0}
        return {"segments": {"TAKER_OPEN": {"units": 30, "metrics": metrics}}}

    rejected = cop.fast_follow_verdict(decay(2.0), cfg)
    assert rejected["status"] == "REJECTED" and rejected["break_even_bps"] == 9.0
    assert rejected["drift_lost_before_observation_bps"] == 6.0
    assert cop.fast_follow_verdict(decay(12.0), cfg)["status"] == "MORE_DATA"
    assert cop.fast_follow_verdict({"segments": {}}, cfg)["status"] == "MORE_DATA"


def test_etude_complete_deterministe_serialisable_et_strictement_paper():
    rows, prices = [], [(s, 100.0 + 0.001 * s) for s in range(0, 4_000)]
    for i in range(60):
        rows.append(_fill("0xA", "BTC", 20 + i * 60, "B", 100.0, 1.0, 0.0, "Open Long", tid=2 * i + 1, lag_s=3))
        rows.append(_fill("0xA", "BTC", 50 + i * 60, "A", 100.0, 1.0, 1.0, "Close Long", tid=2 * i + 2, lag_s=3))
    fills, _ = _prepared(rows)
    panel = _panel(prices)
    cfg = cop.CopiabilityConfig(min_fills_per_unit=10, min_episodes_per_unit=5, horizons_s=(5, 15))
    first = cop.run_copiability_study(fills, panel, {"BTC": 1.0}, cfg)
    second = cop.run_copiability_study(fills, panel, {"BTC": 1.0}, cfg)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)
    assert first["paper_read_only"] is True and first["real_execution"] is False
    assert first["economically_proven"] is False
    assert {v["hypothesis"] for v in first["verdicts"]} == {
        cop.H_NAIVE_MIRROR, cop.H_FAST_FOLLOW, cop.H_SLOW_REPLICATION,
    }
    assert all(v["status"] in {"PROVEN", "PROMISING", "MORE_DATA", "UNMEASURABLE", "REJECTED"} for v in first["verdicts"])
    assert any(need["need"] == "PROFONDEUR_HISTORIQUE" for need in first["collection_needs"])


def test_module_sans_reseau_ni_chemin_d_execution():
    import ast

    facade = Path(cop.__file__)
    modules = [facade, facade.with_name("copy_vault_copiability_entrees.py"),
               facade.with_name("copy_vault_copiability_mesures.py")]
    for module in modules:                                  # la façade et ses deux modules voisins
        source = module.read_text(encoding="utf-8")
        imported: set[str] = set()
        internes: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
                if node.module.startswith("hl_observer"):
                    internes.add(node.module)
        # calcul pur : aucune bibliothèque réseau, de signature ou d'accès exchange
        assert imported <= {"__future__", "math", "collections", "dataclasses", "typing", "numpy", "pandas", "scipy",
                            "hl_observer"}, module.name
        # du projet, seuls le barème de frais et les modules voisins du moteur sont importés
        assert internes <= {"hl_observer.fees.hyperliquid_fees",
                            "hl_observer.backtesting.copy_vault_copiability_entrees",
                            "hl_observer.backtesting.copy_vault_copiability_mesures"}, module.name
        for forbidden in ("/exchange", "private_key", "mnemonic", "wallet.sign", "eth_account"):
            assert forbidden not in source
        assert len(source.splitlines()) <= 800, module.name   # invariant d'architecture du projet


def test_alias_des_anciens_rubans_en_majuscules_sans_ambiguite():
    snapshots = [(T0, {"KPEPE": 1.0, "BTC": 2.0, "KBONK": 3.0, "ETH": 4.0})]
    panel = cop.build_mid_panel(snapshots)
    fixed, aliases = cop.alias_legacy_symbols(panel, ["kPEPE", "BTC", "kBONK", "KBONK", "eth", "Eth"])
    assert aliases == {"KPEPE": "kPEPE"}        # KBONK existe tel quel ; ETH est ambigu (eth / Eth)
    assert fixed.column("kPEPE") == panel.column("KPEPE") and fixed.column("KPEPE") is None
    assert fixed.column("KBONK") is not None and fixed.column("ETH") is not None
    same, none = cop.alias_legacy_symbols(panel, ["KPEPE", "BTC"])
    assert same is panel and none == {}


def test_outil_d_etude_hors_ligne_registre_chaine_et_plan_de_collecte(tmp_path):
    """L'outil n'importe aucune bibliothèque réseau ; son registre détecte toute réécriture."""
    import ast

    import tools.etude_copiabilite as outil

    imported: set[str] = set()
    for node in ast.walk(ast.parse(Path(outil.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"requests", "httpx", "urllib", "socket", "websocket", "websockets", "aiohttp", "ccxt"}

    registre = tmp_path / "EXPERIENCES.jsonl"
    assert outil.verify_ledger(registre) == {"status": "EMPTY", "records": 0}
    premier = outil.append_ledger(registre, {"run_id": "a", "verdicts": [{"status": "REJECTED"}]})
    second = outil.append_ledger(registre, {"run_id": "b", "verdicts": [{"status": "MORE_DATA"}]})
    assert outil.verify_ledger(registre) == {"status": "VERIFIED", "records": 2, "head": second}
    lignes = registre.read_text(encoding="utf-8").splitlines()
    assert json.loads(lignes[1])["previous_record_sha256"] == premier
    registre.write_text(lignes[0].replace("REJECTED", "PROMISING") + "\n" + lignes[1] + "\n", encoding="utf-8")
    assert outil.verify_ledger(registre)["status"] == "BROKEN"       # un résultat négatif ne se maquille pas

    plan = outil.collection_plan(
        {"sybil_units": {"0xa": "0xa", "0xb": "0xa", "0xc": "0xc"}, "collection_needs": [],
         "classification": [
             {"unit": "0xa", "archetype": "HFT", "turnover_per_exposure_per_day": 40.0, "mean_exposure_usd": 5e4},
             {"unit": "0xc", "archetype": "DIRECTIONAL_SLOW", "turnover_per_exposure_per_day": 1.0, "mean_exposure_usd": 9e5},
         ]},
        {"experiment_id": "exp", "corpus_sha256": "0" * 64},
    )
    assert [(row["unit"], row["addresses"], row["cadence"]) for row in plan["leaders"]] == [
        ("0xa", ["0xa", "0xb"], "ARCHIVE"), ("0xc", ["0xc"], "PRIORITAIRE")]
    assert plan["evidence_tier"] == cop.EVIDENCE_TIER_LOCAL and plan["real_execution"] is False


def test_shard_du_coffre_modifie_apres_scellage_est_ecarte(tmp_path):
    """Intégrité du corpus : un shard dont le SHA-256 ne correspond plus à l'index n'est pas lu."""
    import gzip
    import hashlib

    import tools.etude_copiabilite as outil

    shards = tmp_path / "runtime" / "coffre_certifie" / "local" / "shards" / "fills_forward"
    shards.mkdir(parents=True)
    entries = []
    for name in ("a__vault_fills_poll.jsonl.gz", "b__vault_fills_poll.jsonl.gz", "c__liquidations.jsonl.gz"):
        path = shards / name
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(_fill("0xA", "BTC", 1, "B", 100.0, 1.0, 0, "Open Long")) + "\n")
        entries.append({"famille": "fills_forward", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "shard": f"runtime/coffre_certifie/local/shards/fills_forward/{name}"})
    entries.append({"famille": "fills_forward", "sha256": "0" * 64,
                    "shard": "runtime/coffre_certifie/local/shards/fills_forward/absent__vault_fills_poll.jsonl.gz"})
    (tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text(json.dumps({"shards": entries}), encoding="utf-8")
    with gzip.open(shards / "b__vault_fills_poll.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write("{}\n")                                           # altération après scellage
    selected, excluded = outil.select_shards(tmp_path)
    assert [Path(item["path"]).name for item in selected["fills_forward"]] == ["a__vault_fills_poll.jsonl.gz"]
    assert sorted(item["reason"] for item in excluded) == ["fichier_absent", "sha256_different_de_l_index"]


# ─────────────── bougies, étude rétrospective, portefeuilles observés ───────────────

def test_bougie_la_cloture_n_est_lisible_qu_a_la_fin_de_la_bougie():
    panel = cop.build_candle_panel([("BTC", T0, 100.0), ("BTC", T0 + 300_000, 110.0), ("ETH", T0, 5.0)], interval_ms=300_000)
    col = panel.column("BTC")
    got = panel.at(np.array([T0 + 299_999, T0 + 300_000, T0 + 599_999, T0 + 600_000, T0 + 1_000_000]), col)
    assert math.isnan(got[0])                       # la clôture de la 1re bougie n'existe pas encore
    assert got[1] == 100.0 and got[2] == 100.0      # la 2e bougie n'est pas lue avant sa fin
    assert got[3] == 110.0
    assert math.isnan(got[4])                       # bougie manquante ensuite : inconnu, pas reporté
    assert panel.provenance == "HYPERLIQUID_CANDLE_CLOSE_RETROSPECTIVE"
    assert math.isnan(panel.at(np.array([T0 + 600_000]), panel.column("ETH"))[0])   # ETH sans 2e bougie


def test_retard_suppose_reserve_aux_fills_sans_observation_et_jamais_substitue_a_une_vraie():
    backfill = {"vault": "0xA", "coin": "BTC", "ts_ms": T0, "px": 1.0, "sz": 1.0, "side_raw": "B",
                "dir": "Open Long", "pos_avant": 0.0, "tid": 1, "oid": 1, "observed_at_ms": None}
    assert cop.parse_fill_row(backfill) == (None, "horodatage_invalide")          # sans hypothèse : rejet
    row, _ = cop.parse_fill_row(backfill, assumed_lag_ms=120_000)
    assert row[2] == T0 and row[3] == T0 + 120_000 and row[6] == 1 and row[8] == 0.0
    observe = {**backfill, "observed_at_ms": T0 + 7}
    assert cop.parse_fill_row(observe, assumed_lag_ms=120_000)[0][3] == T0 + 7   # la vraie observation prime
    casse = {**backfill, "observed_at_ms": "bientot"}
    assert cop.parse_fill_row(casse, assumed_lag_ms=120_000) == (None, "horodatage_invalide")


def _snapshot(vault, t_s, **positions):
    return {"vault": vault, "ts_ms": T0 + int(t_s * 1000),
            "positions": [{"coin": c, "szi": v} for c, v in positions.items()]}


def test_instantanes_un_coin_absent_vaut_position_nulle_et_rien_n_est_connu_avant():
    events, seen, rejects = cop.position_events_from_snapshots([
        _snapshot("0xV", 0, BTC=2.0, ETH=-5.0),
        _snapshot("0xV", 300, BTC=2.0),                       # ETH a disparu : position soldée
        _snapshot("0xV", 600, BTC=3.0),
        _snapshot("0xV", 600, BTC=9.0),                       # même instant : doublon écarté
        {"vault": "0xV", "ts_ms": T0 + 900_000, "positions": [{"coin": "BTC", "szi": "nan"}]},
        {"vault": "", "ts_ms": T0, "positions": []},
    ])
    assert rejects == {"doublon_instant": 1, "position_illisible": 1, "instantane_invalide": 1}
    lignes = [(r.coin, int(r.time - T0) // 1000, r.start_pos, r.after) for r in events.itertuples()]
    assert lignes == [("BTC", 0, 0.0, 2.0), ("ETH", 0, 0.0, -5.0), ("ETH", 300, -5.0, 0.0), ("BTC", 600, 2.0, 3.0)]
    assert list(seen["0xv"] - T0) == [0, 300_000, 600_000]


def test_position_perimee_est_inconnue_pas_prolongee_et_l_exposition_se_mesure_sur_les_heures_connues():
    """Un vault observé 1 h, puis collecte arrêtée 10 h pendant que le prix s'effondre :
    la perte de la période non observée n'est pas imputée, et l'exposition n'est pas diluée."""
    minutes = range(0, 12 * 60)
    prix = [(m * 60, 100.0 if m <= 120 else 50.0) for m in minutes]      # chute à 121 min : bien après le dernier instantané (60 min) + 15 min de fraîcheur
    panel = cop.build_mid_panel([(T0 + s * 1000, {"BTC": p}) for s, p in prix], stale_ms=60_000)
    snaps = [_snapshot("0xV", m * 60, BTC=10.0) for m in range(0, 61, 5)]   # instantanés pendant 1 h
    events, seen, _ = cop.position_events_from_snapshots(snaps)
    cfg = cop.CopiabilityConfig(rebalance_minutes=(60,), reaction_delay_ms=0, min_day_coverage_hours=0.5)
    sans_limite = cop.attribute_pnl(events, panel, {"BTC": 1.0}, {}, cfg, measure_execution=False)
    assert sans_limite["leaders"][0]["inventory_k60_usd"] == pytest.approx(-500.0)   # position prolongée à tort
    borne = cop.attribute_pnl(events, panel, {"BTC": 1.0}, {}, cfg, observation_times=seen,
                              max_staleness_ms=900_000, measure_execution=False)
    leader = borne["leaders"][0]
    assert leader["inventory_k60_usd"] == pytest.approx(0.0)             # chute non observée : non mesurée
    assert leader["known_hours"] == pytest.approx(1.25, abs=0.05)        # 1 h + 15 min de fraîcheur
    assert leader["mean_exposure_usd"] == pytest.approx(1000.0, rel=0.05)  # 10 BTC x 100, pas divisé par 12 h
    assert leader["execution_usd"] == 0.0                                # un instantané n'a pas de prix d'exécution


def test_test_par_operateur_bonferroni_durcit_le_seuil_avec_le_nombre_de_candidats():
    days = 40
    rng = np.random.default_rng(11)
    bruit = rng.normal(0.0, 30.0, size=(20, days))
    bruit[0] += 40.0                                                     # un seul opérateur réellement bon
    tests = cop.unit_time_series_tests(_attribution(bruit), 60)
    assert tests["units_tested"] == 20 and tests["units"][0]["unit"] == "u0"
    assert tests["units"][0]["significant_after_bonferroni"] is True
    assert tests["units_significant_after_bonferroni"] == 1              # aucun faux gagnant parmi 19 bruits
    seul = cop.unit_time_series_tests(_attribution(bruit[1:2]), 60)["units"][0]["critical_t_bonferroni"]
    assert tests["units"][0]["critical_t_bonferroni"] > seul            # chercher parmi 20 coûte plus cher
    assert cop.unit_time_series_tests(_attribution(bruit[:, :5]), 60)["status"] == "MORE_DATA"   # trop peu de jours


def test_etude_sur_portefeuilles_observes_reste_exploratoire_et_serialisable():
    minutes = range(0, 26 * 60)
    panel = cop.build_mid_panel([(T0 + m * 60_000, {"BTC": 100.0 + 0.01 * m}) for m in minutes], stale_ms=60_000)
    snaps = [_snapshot("0xV", m * 60, BTC=10.0 + (m // 240)) for m in range(0, 26 * 60, 5)]
    events, seen, _ = cop.position_events_from_snapshots(snaps)
    cfg = cop.CopiabilityConfig(rebalance_minutes=(60, 240))
    report = cop.run_position_replication_study(events, seen, panel, {"BTC": 1.0}, cfg)
    assert report["economically_proven"] is False and report["real_execution"] is False
    assert report["verdicts"][0]["status"] == "MORE_DATA" and report["verdicts"][0]["evidence"] == "OBSERVED_POSITIONS"
    assert report["universe_attribution"]["inventory_k240_usd"] > 0
    assert report["economic_scale"]["usd_per_day_per_10_bps"] == pytest.approx(0.35)


def test_fill_websocket_sens_lu_dans_signe_et_segment_d_observation_rapide():
    """Un fill WS n'a pas de champ ``side`` mais un ``signe`` ; observé en 0,2 s il alimente le
    segment « observation rapide », distinct des fills vus tard par relevé REST."""
    ws = {"vault": "0xW", "coin": "BTC", "px": 100.0, "sz": 1.0, "signe": -1, "ts_ms": T0 + 10_000,
          "received_at_ms": T0 + 10_200, "dir": "Open Short", "start_position": 0.0, "tid": 5, "oid": 5}
    row, raison = cop.parse_fill_row(ws)
    assert raison is None and row[6] == -1 and row[3] - row[2] == 200
    assert cop.parse_fill_row({**ws, "signe": 0}) [0][6] == 0          # sens réellement inconnu : rejeté ensuite

    rows, prices = [], [(s, 100.0) for s in range(0, 70_000)]
    for i in range(120):                                               # 60 ouvertures WS + 60 ouvertures REST
        rapide = i % 2 == 0
        rows.append(_fill("0xW" if rapide else "0xP", "BTC", 100 + i * 500, "B", 100.0, 1.0, 0.0, "Open Long",
                          tid=10 + i, lag_s=0.2 if rapide else 90.0))
    fills, _ = _prepared(rows)
    cfg = cop.CopiabilityConfig(min_fills_per_unit=20, horizons_s=(15, 60))
    segments = cop.decay_curves(fills, _panel(prices[::5]), {}, cfg)["segments"]
    assert (segments["OPEN_OBS_RAPIDE"]["fills"], segments["OPEN_OBS_LENTE"]["fills"]) == (60, 60)
    assert segments["OPEN_OBS_RAPIDE"]["units"] == 1 and segments["CLOSE_OBS_RAPIDE"]["fills"] == 0


def test_funding_compte_dans_le_net_la_ou_il_est_connu_et_trace_ailleurs():
    """Long 10 BTC à 100 USD pendant 4 h, prix plat, taux +0,01 %/h connu sur les 2 premières
    heures seulement : le copieur PAIE 2 h de funding ; les 2 h restantes sont tracées inconnues."""
    minutes = range(0, 4 * 60 + 1)
    panel = cop.build_mid_panel([(T0 + m * 60_000, {"BTC": 100.0}) for m in minutes], stale_ms=60_000)
    rows = [_fill("0xL", "BTC", 0, "B", 100.0, 10.0, 0.0, "Open Long", tid=1, lag_s=0.0)]
    fills, _ = _prepared(rows)
    obs = [("BTC", T0 + m * 60_000, 1e-4) for m in range(0, 121, 10)] + [("ETH", T0, 5e-4), ("BTC", T0, "nan")]
    cfg = cop.CopiabilityConfig(rebalance_minutes=(1,), reaction_delay_ms=0)
    rates = cop.build_funding_rates(obs, panel, stale_ms=600_000)
    assert set(rates) == {"BTC"}                                   # ETH absent du panel ; taux illisible ignoré
    assert rates["BTC"][0] == 1e-4 and math.isnan(rates["BTC"][-1])  # au-delà de 2 h + 10 min : inconnu
    leader = cop.attribute_pnl(fills, panel, {"BTC": 1.0}, {}, cfg, funding_rates=rates)["leaders"][0]
    connu_h = 130.0 / 60.0                                         # 120 min observées + 10 min de fraîcheur
    assert leader["funding_k1_usd"] == pytest.approx(-10 * 100.0 * 1e-4 * connu_h, rel=0.02)
    assert leader["funding_unmeasured_k1_usd_hours"] == pytest.approx(1000.0 * (4.0 - connu_h), rel=0.02)
    assert leader["net_k1_usd"] == pytest.approx(leader["inventory_k1_usd"] - leader["cost_k1_usd"] + leader["funding_k1_usd"])
    sans = cop.attribute_pnl(fills, panel, {"BTC": 1.0}, {}, cfg)["leaders"][0]
    assert sans["funding_k1_usd"] == 0.0                           # non mesuré...
    assert sans["funding_unmeasured_k1_usd_hours"] == pytest.approx(1000.0 * 4.0, rel=0.02)   # ...et tracé comme tel
    short = [_fill("0xS", "BTC", 0, "A", 100.0, 10.0, 0.0, "Open Short", tid=2, lag_s=0.0)]
    recu = cop.attribute_pnl(_prepared(short)[0], panel, {"BTC": 1.0}, {}, cfg, funding_rates=rates)["leaders"][0]
    assert recu["funding_k1_usd"] == pytest.approx(-leader["funding_k1_usd"])   # un short REÇOIT un taux positif
