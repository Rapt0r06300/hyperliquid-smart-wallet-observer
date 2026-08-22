"""Filtre anti-perte du flux WS userFills (rectif Flo 23/07) : snapshot initial ignoré + curseur posé ;
après reconnexion, seuls les fills inconnus plus récents que le curseur sont rejoués. Poster injecté."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from pathlib import Path

from hl_observer.backtesting.copy_vault_executable import cluster_metaorders

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _mod("collecter_userfills_vaults")


def _f(ts, snap=False):
    return {"coin": "SOL", "ts_ms": ts, "isSnapshot": snap, "hash": "h%d" % ts}


def test_snapshot_initial_ignore_et_curseur_pose():
    cur = {}
    a = C.fills_a_traiter("0xV", [_f(100, snap=True), _f(200, snap=True)], cur)
    assert a == [] and cur["0xV"] == 200                            # rien tradé, curseur = dernier ts


def test_reconnexion_rejoue_les_inconnus_recents():
    cur = {"0xV": 200}
    # snapshot de reconnexion : fills 150 (déjà vu) et 300 (survenu pendant la coupure)
    a = C.fills_a_traiter("0xV", [_f(150, snap=True), _f(300, snap=True)], cur)
    assert [f["ts_ms"] for f in a] == [300] and cur["0xV"] == 300   # catch-up : seulement le récent


def test_live_filtre_sur_curseur():
    cur = {"0xV": 300}
    a = C.fills_a_traiter("0xV", [_f(300), _f(400), _f(500)], cur)  # 300 = curseur (pas strictement >)
    assert [f["ts_ms"] for f in a] == [400, 500] and cur["0xV"] == 500


def test_fill_persiste_avec_horodatage_de_reception_causale(tmp_path, monkeypatch):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    monkeypatch.setattr(C, "_TAPE_FILLS", None)
    monkeypatch.setattr(C.CO, "COHORTES", {})
    fill = {
        "vault": "0xV", "coin": "SOL", "ts_ms": 1000, "source": "LIVE_WS",
        "isSnapshot": False, "hash": "0xfill",
    }

    C._traiter_un(tmp_path, fill, set(), 1.0)

    saved = json.loads((tmp_path / C.FILLS_LIVE).read_text(encoding="utf-8"))
    assert saved["received_at_ms"] >= saved["ts_ms"]
    assert "received_at_ms" not in fill


def test_tape_copy_vault_persiste_un_l2_causal_et_echantillonne(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_COPY_VAULT_LAST_SAMPLE_MS", {})
    resume = {
        "bid": 99.0,
        "ask": 101.0,
        "book_exchange_time": 1_000,
        "bids5": [[99.0, 2.0, 1], [98.0, 1.0, 1]],
        "asks5": [[101.0, 3.0, 1], [102.0, 1.0, 1]],
    }

    assert C._append_copy_vault_book(
        tmp_path, "btc", resume, received_at_ms=1_010,
    ) is True
    assert C._append_copy_vault_book(
        tmp_path, "btc", resume, received_at_ms=1_500,
    ) is False
    assert C._append_copy_vault_book(
        tmp_path, "btc", resume, received_at_ms=2_010,
    ) is True

    rows = [
        json.loads(line)
        for line in (tmp_path / C.COPY_VAULT_L2_TAPE).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["source"] == "HYPERLIQUID_L2_WS"
    assert rows[0]["causal_observation"] is True
    assert rows[0]["capacity_usd"] == min(99 * 2 + 98, 101 * 3 + 102)


def test_copy_vault_prewarm_restreint_aux_wallets_suivis_et_aux_coins_recents(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    rows = [
        {"vault": "0xFOLLOW", "coin": "BTC", "ts_ms": 100},
        {"vault": "0xOTHER", "coin": "DOGE", "ts_ms": 999},
        {"vault": "0xFOLLOW", "coin": "ETH", "ts_ms": 300},
        {"vault": "0xFOLLOW", "coin": "SOL", "ts_ms": 200},
    ]
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    selected = C._copy_vault_prewarm_coins(
        tmp_path, ["0xfollow"], max_coins=2, now_ms=400
    )

    assert selected == ["ETH", "SOL"]
    assert "DOGE" not in selected


def test_copy_vault_prewarm_est_borne_par_le_plafond_dur(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    rows = [
        {"vault": "0xFOLLOW", "coin": f"C{index}", "ts_ms": index + 1}
        for index in range(C.TAPE_PREWARM_MAX_COINS + 5)
    ]
    (data / "vault_fills.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    selected = C._copy_vault_prewarm_coins(
        tmp_path,
        ["0xFOLLOW"],
        max_coins=10_000,
        now_ms=C.TAPE_PREWARM_MAX_COINS + 10,
    )

    assert len(selected) == C.TAPE_PREWARM_MAX_COINS
    assert selected[0] == f"C{C.TAPE_PREWARM_MAX_COINS + 4}"


def test_copy_vault_prewarm_exclut_activite_perimee_et_future(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    now_ms = 10_000_000
    rows = [
        {"vault": "0xFOLLOW", "coin": "FRESH", "ts_ms": now_ms - 1_000},
        {
            "vault": "0xFOLLOW",
            "coin": "STALE",
            "ts_ms": now_ms - C.TAPE_PREWARM_RECENT_WINDOW_MS - 1,
        },
        {"vault": "0xFOLLOW", "coin": "FUTURE", "ts_ms": now_ms + 60_001},
    ]
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    selected = C._copy_vault_prewarm_coins(
        tmp_path, ["0xfollow"], now_ms=now_ms
    )

    assert selected == ["FRESH"]


def test_copy_vault_prewarm_ne_lit_quun_tail_borne(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    path = data / "vault_fills_live.jsonl"
    path.write_bytes(
        (json.dumps({"vault": "0xFOLLOW", "coin": "OLD", "ts_ms": 999}) + "\n").encode()
        + b"x" * 300
        + b"\n"
        + (json.dumps({"vault": "0xFOLLOW", "coin": "NEW", "ts_ms": 1000}) + "\n").encode()
    )

    selected = C._copy_vault_prewarm_coins(
        tmp_path,
        ["0xfollow"],
        now_ms=1000,
        max_tail_bytes=120,
    )

    assert selected == ["NEW"]


def test_copy_vault_prewarm_rotation_remplace_lancien_et_nettoie_actifs(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    now_ms = 20_000_000
    (data / "vault_fills_live.jsonl").write_text(
        json.dumps({"vault": "0xFOLLOW", "coin": "NEW", "ts_ms": now_ms}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "_TAPE_PREWARM_COINS", {"OLD"})
    monkeypatch.setattr(
        C,
        "_TAPE_COINS_ACTIFS",
        {
            "ACTIVE": now_ms - 1_000,
            "EXPIRED": now_ms - C.TAPE_COIN_TTL_MS - 1,
        },
    )

    result = C._refresh_copy_vault_prewarm_once(
        tmp_path, ["0xfollow"], now_ms=now_ms
    )

    assert C._TAPE_PREWARM_COINS == {"NEW"}
    assert C._TAPE_COINS_ACTIFS == {"ACTIVE": now_ms - 1_000}
    assert result["added"] == ["NEW"]
    assert result["removed"] == ["OLD"]
    assert result["expired_active"] == ["EXPIRED"]


def test_univers_l2_preserve_la_casse_canonique_allmids(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    cache = data / "hl_allmids.json"
    cache.write_text(
        json.dumps({"mids": {"KBONK": "1"}}),
        encoding="utf-8",
    )
    calls = []

    symbols = C._active_l2_symbols(
        tmp_path,
        now_ms=cache.stat().st_mtime * 1_000 + 1_000,
        post_allmids=lambda: calls.append(True) or {
            "BTC": "60000",
            "kBONK": "0.003",
            "BAD": "nan",
        },
    )

    assert symbols == {"BTC": "BTC", "KBONK": "kBONK"}
    assert calls == [True]


def test_univers_l2_echec_info_est_fail_closed(tmp_path):
    symbols = C._active_l2_symbols(
        tmp_path,
        post_allmids=lambda: (_ for _ in ()).throw(OSError("offline")),
    )

    assert symbols == {}


def test_prewarm_l2_exclut_un_symbole_historique_retire(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    now_ms = 30_000_000
    (data / "vault_fills_live.jsonl").write_text(
        "\n".join(
            json.dumps({"vault": "0xFOLLOW", "coin": coin, "ts_ms": now_ms})
            for coin in ("BTC", "KBONK")
        ) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "_TAPE_PREWARM_COINS", set())
    monkeypatch.setattr(C, "_TAPE_COINS_ACTIFS", {})
    monkeypatch.setattr(C, "_TAPE_ACTIVE_L2_SYMBOLS", set())
    monkeypatch.setattr(C, "_TAPE_L2_CANONICAL", {})

    result = C._refresh_copy_vault_prewarm_once(
        tmp_path,
        ["0xfollow"],
        now_ms=now_ms,
        active_symbols={"BTC", "SOL"},
    )

    assert C._TAPE_PREWARM_COINS == {"BTC"}
    assert result["filtered_inactive"] == ["KBONK"]


def test_cibles_l2_intersectent_toujours_lunivers_actif(monkeypatch):
    now_ms = 40_000_000
    monkeypatch.setattr(C, "_TAPE_PREWARM_COINS", {"BTC", "KBONK", "DELISTED"})
    monkeypatch.setattr(C, "_TAPE_COINS_ACTIFS", {"SOL": now_ms - 1_000})
    monkeypatch.setattr(C, "_TAPE_ACTIVE_L2_SYMBOLS", {"BTC", "SOL", "KBONK"})
    monkeypatch.setattr(
        C,
        "_TAPE_L2_CANONICAL",
        {"BTC": "BTC", "SOL": "SOL", "KBONK": "kBONK"},
    )

    assert C._tape_l2_targets(now_ms) == {"BTC", "SOL", "kBONK"}


def test_collecteur_lance_le_refresh_periodique_du_prewarm():
    source = (RACINE / "tools" / "collecter_userfills_vaults.py").read_text(encoding="utf-8")
    gather = source.split("await asyncio.gather(", 1)[1]
    assert "_refresh_copy_vault_prewarm_periodically(root, vaults)" in gather


def test_copy_vault_ttl_couvre_episode_executable_le_plus_court():
    assert C.TAPE_COIN_TTL_MS == (
        C.COPY_VAULT_DELAY_MS
        + min(C.COPY_VAULT_HORIZONS_MS)
        + C.COPY_VAULT_MAX_TARGET_LAG_MS
    )
    assert C.TAPE_COIN_TTL_MS > 360_000


def test_checkpoints_nouveau_metaordre_et_sorties_sont_deterministes():
    checkpoints = C._new_metaorder_checkpoints(
        {"coin": "btc", "received_at_ms": 10_000},
        recv_mono_ms=20_000.0,
        metaorder_id="mo-1",
    )

    assert [row["stage"] for row in checkpoints] == ["REFERENCE", "ENTRY"]
    assert checkpoints[1]["target_wall_ms"] == 10_000 + C.COPY_VAULT_DELAY_MS
    captured_entry = {
        **checkpoints[1],
        "captured_mono_ms": 80_250.0,
        "captured_wall_ms": 70_250,
    }
    exits = C._exit_metaorder_checkpoints(captured_entry)
    assert [row["target_wall_ms"] for row in exits] == [
        70_250 + horizon for horizon in C.COPY_VAULT_HORIZONS_MS
    ]
    assert len({row["checkpoint_id"] for row in exits}) == len(C.COPY_VAULT_HORIZONS_MS)


def test_checkpoint_prefere_un_book_ws_reel_sans_appel_rest(tmp_path, monkeypatch):
    now_mono = time.monotonic() * 1_000
    now_wall = int(time.time() * 1_000)
    resume = {
        "bid": 99.0, "ask": 101.0, "book_exchange_time": now_wall,
        "bids5": [[99.0, 2.0, 1]], "asks5": [[101.0, 2.0, 1]],
    }
    monkeypatch.setattr(C, "_TAPE_BUFFER", {
        "BTC": [{
            "recv_mono": now_mono,
            "recv_wall_ms": now_wall,
            "resume": resume,
        }]
    })
    monkeypatch.setattr(
        C,
        "_lecteur_l2_ondemand",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("REST interdit")),
    )
    result = asyncio.run(C._capture_copy_vault_checkpoint(tmp_path, {
        "coin": "BTC", "metaorder_id": "mo-ws", "stage": "REFERENCE",
        "checkpoint_id": "mo-ws:REFERENCE",
        "target_mono_ms": now_mono - 10,
        "target_wall_ms": now_wall - 10,
        "attempts": 0,
    }))

    assert result["status"] == "CAPTURED_WS"
    row = json.loads((tmp_path / C.COPY_VAULT_L2_TAPE).read_text(encoding="utf-8"))
    assert row["source"] == "HYPERLIQUID_L2_WS"
    assert row["checkpoint_id"] == "mo-ws:REFERENCE"
    assert row["metaorder_id"] == "mo-ws"
    assert row["collector_protocol"] == C.CHECKPOINT_COLLECTOR_PROTOCOL


def test_checkpoint_ws_refuse_retombe_sur_info_public(tmp_path, monkeypatch):
    now_mono = time.monotonic() * 1_000
    now_wall = int(time.time() * 1_000)
    monkeypatch.setattr(C, "_TAPE_BUFFER", {
        "BTC": [{
            "recv_mono": now_mono,
            "recv_wall_ms": now_wall,
            "resume": {
                "bid": 99.0, "ask": 101.0, "book_exchange_time": now_wall,
                "bids5": [[99.0, 0.0, 1]], "asks5": [[101.0, 0.0, 1]],
            },
        }]
    })
    monkeypatch.setattr(C, "_COPY_VAULT_LAST_SAMPLE_MS", {})
    monkeypatch.setattr(C, "_lecteur_l2_ondemand", lambda *_args, **_kwargs: {
        "hl_bid": 99.5, "hl_ask": 100.5,
        "received_ts_ms": now_wall, "exchange_ts_ms": now_wall - 5,
        "bids": [(99.5, 2.0)], "asks": [(100.5, 3.0)],
    })

    result = asyncio.run(C._capture_copy_vault_checkpoint(tmp_path, {
        "coin": "BTC", "metaorder_id": "mo-fallback", "stage": "ENTRY",
        "checkpoint_id": "mo-fallback:ENTRY",
        "target_mono_ms": now_mono - 100,
        "target_wall_ms": now_wall - 100,
        "attempts": 0,
    }))

    assert result["status"] == "CAPTURED_INFO"
    row = json.loads((tmp_path / C.COPY_VAULT_L2_TAPE).read_text(encoding="utf-8"))
    assert row["source"] == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT"
    assert row["metaorder_id"] == "mo-fallback"
    assert row["collector_protocol"] == C.CHECKPOINT_COLLECTOR_PROTOCOL


def test_checkpoint_info_public_persiste_provenance_causale(tmp_path, monkeypatch):
    now_mono = time.monotonic() * 1_000
    now_wall = int(time.time() * 1_000)
    monkeypatch.setattr(C, "_TAPE_BUFFER", {})
    monkeypatch.setattr(C, "_COPY_VAULT_LAST_SAMPLE_MS", {})
    monkeypatch.setattr(C, "_lecteur_l2_ondemand", lambda *_args, **_kwargs: {
        "hl_bid": 99.0, "hl_ask": 101.0,
        "received_ts_ms": now_wall, "exchange_ts_ms": now_wall - 5,
        "bids": [(99.0, 2.0)], "asks": [(101.0, 3.0)],
    })
    result = asyncio.run(C._capture_copy_vault_checkpoint(tmp_path, {
        "coin": "BTC", "metaorder_id": "mo-info", "stage": "ENTRY",
        "checkpoint_id": "mo-info:ENTRY",
        "target_mono_ms": now_mono - 100,
        "target_wall_ms": now_wall - 100,
        "attempts": 0,
    }))

    row = json.loads((tmp_path / C.COPY_VAULT_L2_TAPE).read_text(encoding="utf-8"))
    assert result["status"] == "CAPTURED_INFO"
    assert row["source"] == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT"
    assert row["checkpoint_stage"] == "ENTRY"
    assert row["checkpoint_target_ms"] == now_wall - 100
    assert row["metaorder_id"] == "mo-info"
    assert row["collector_protocol"] == C.CHECKPOINT_COLLECTOR_PROTOCOL
    assert row["data_origin"] == "REAL_OBSERVED"


def _live_open_fill(*, received_at_ms: int, ts_ms: int, start_position: float) -> dict:
    return {
        "vault": "0xabc",
        "coin": "btc",
        "px": 100.0,
        "sz": 1.5,
        "signe": 1,
        "dir": "Open Long",
        "start_position": start_position,
        "ts_ms": ts_ms,
        "received_at_ms": received_at_ms,
        "hash": f"hash-{ts_ms}",
        "tid": ts_ms,
        "oid": ts_ms + 1,
    }


def test_identite_checkpoint_live_identique_au_replay_causal() -> None:
    live_fill = _live_open_fill(
        received_at_ms=10_100,
        ts_ms=10_000,
        start_position=0.0,
    )
    live_id, stage = C._copy_vault_checkpoint_metaorder({}, live_fill)
    event_id = C.canonical_fill_id(live_fill)
    replay_metaorder = cluster_metaorders([{
        **live_fill,
        "event_id": event_id,
        "direction": 1,
        "action": "OPEN",
        "observed_at_ms": 10_100,
        "source": "LIVE_WS",
        "is_snapshot": False,
    }])[0][0]

    assert stage == "FIRST_SLICE"
    assert live_id == replay_metaorder["metaorder_id"]


def test_checkpoint_add_continue_et_open_explicite_redemarre() -> None:
    state: dict = {}
    first_id, first_stage = C._copy_vault_checkpoint_metaorder(
        state,
        _live_open_fill(received_at_ms=10_100, ts_ms=10_000, start_position=0.0),
    )
    add_id, add_stage = C._copy_vault_checkpoint_metaorder(
        state,
        _live_open_fill(received_at_ms=20_100, ts_ms=20_000, start_position=1.5),
    )
    reopened_id, reopened_stage = C._copy_vault_checkpoint_metaorder(
        state,
        _live_open_fill(received_at_ms=30_100, ts_ms=30_000, start_position=0.0),
    )

    assert first_stage == "FIRST_SLICE"
    assert add_stage == "CONTINUATION" and add_id == first_id
    assert reopened_stage == "FIRST_SLICE" and reopened_id != first_id


def test_collecteur_branche_checkpoints_causaux_dans_consommateur():
    source = (RACINE / "tools" / "collecter_userfills_vaults.py").read_text(encoding="utf-8")
    consumer = source.split("async def _tape_consumer", 1)[1].split("def _git_commit", 1)[0]
    assert "_new_metaorder_checkpoints(" in consumer
    assert "await _capture_copy_vault_checkpoint(root, checkpoint)" in consumer
    assert "_exit_metaorder_checkpoints(result)" in consumer
    assert "checkpointed_metaorders.pop(metaorder_id, None)" in consumer


def test_vaults_et_roles(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "retenus": ["0xC1", "0xC2"],
        "classement": [
            {"vault": "0xC1", "retenu": True, "facteurs": {}},
            {"vault": "0xC2", "retenu": True, "facteurs": {}},
            {"vault": "0xSAFE", "retenu": False, "facteurs": {"anciennete_j": 200, "drawdown_pct": 20, "copyabilite": 0.8}},
            {"vault": "0xOBS", "retenu": False, "facteurs": {"anciennete_j": 5, "drawdown_pct": 20, "copyabilite": 0.8}}]}))
    roles = C.vaults_et_roles(tmp_path)
    d = {v: r for v, r, _w in roles}
    assert d["0xC1"] == "CORE" and d["0xC2"] == "CORE"             # retenus stricts = CORE (tradent)
    assert d["0xSAFE"] == "CANDIDAT_TRADABLE"                       # passe la sécurité mini -> PROBE l'ouvre
    assert d["0xOBS"] == "CANDIDAT_OBSERVE"                         # trop jeune -> observé seulement


def test_depth_executable_somme_5_niveaux_cote_le_plus_mince():
    """Profondeur = somme des 5 premiers niveaux du côté le plus MINCE × mid (plus honnête que le top
    tick seul). Ici bids plus minces que asks -> c'est la somme bids qui décide."""
    rep = {"levels": [
        [{"px": "0.999", "sz": "100"}, {"px": "0.998", "sz": "100"}, {"px": "0.997", "sz": "100"}],   # bids : 300 unités
        [{"px": "1.001", "sz": "500"}, {"px": "1.002", "sz": "500"}]]}                                 # asks : 1000 unités
    d = C._depth_executable(rep, mid=1.0)
    assert abs(d - 300.0) < 1e-6                                    # min(300, 1000) × mid(1.0) = 300 $


def test_depth_executable_carnet_illisible_rend_zero():
    assert C._depth_executable({}, mid=1.0) == 0.0                 # pas de 'levels' -> 0 (jamais inventé)


def test_rotation_10_places_2_core_8_candidats_par_activite(tmp_path):
    """10 places WS : 2 CORE + 8 candidats, ROTATION par activité live. À copyabilité égale, le candidat
    le PLUS ACTIF passe devant, et on plafonne à 8 candidats (12 en lice)."""
    import time
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    now = time.time() * 1000
    cl = [{"vault": "0xC1", "retenu": True, "facteurs": {}}, {"vault": "0xC2", "retenu": True, "facteurs": {}}]
    for i in range(3, 15):                                          # 12 candidats non-core
        cl.append({"vault": "0x%02d" % i, "retenu": False,
                   "facteurs": {"anciennete_j": 5, "drawdown_pct": 20, "copyabilite": 0.8}})
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({"retenus": ["0xC1", "0xC2"], "classement": cl}))
    fills = [{"vault": "0x14", "coin": "WLD", "ts_ms": now - 1000} for _ in range(20)]     # très actif
    fills += [{"vault": "0x03", "coin": "WLD", "ts_ms": now - 1000}]                        # peu actif
    (tmp_path / "runtime" / "data" / "vault_fills_live.jsonl").write_text("\n".join(json.dumps(x) for x in fills))
    vaults = [v for v, _r, _w in C.vaults_et_roles(tmp_path)]
    assert vaults[:2] == ["0xC1", "0xC2"] and len(vaults) == 10     # 2 CORE + 8 candidats (10 places)
    cand = vaults[2:]
    assert "0x14" in cand and cand.index("0x14") < cand.index("0x03")   # le plus actif passe devant


def test_parse_l2_ws_rend_bid_ask_depth():
    d = {"coin": "WLD", "levels": [
        [{"px": "0.385", "sz": "1000"}, {"px": "0.384", "sz": "1000"}],   # bids
        [{"px": "0.386", "sz": "1000"}, {"px": "0.387", "sz": "1000"}]]}   # asks
    b = C._parse_l2_ws(d)
    assert b and abs(b[0] - 0.385) < 1e-9 and abs(b[1] - 0.386) < 1e-9 and b[2] > 0   # (bid, ask, depth>0)
    assert C._parse_l2_ws({"coin": "X"}) is None                          # illisible -> None (jamais inventé)


def test_book_ws_frais_prefere_au_marquage(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(C, "_ROOT_LIVE", tmp_path)
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / C.RAW_L2_LIVE).write_text(json.dumps(
        {"WLD": {"hl_bid": 0.385, "hl_ask": 0.386, "depth_usd": 3000.0, "collecte_ts": time.time()}}))
    b = C._book_ws_frais("WLD")
    assert b and b["hl_bid"] == 0.385 and b["hl_ask"] == 0.386             # book WS frais servi
    assert C._lecteur_l2_marquage("WLD")["hl_bid"] == 0.385               # marquage préfère le book WS (pas de REST)
    (tmp_path / C.RAW_L2_LIVE).write_text(json.dumps(
        {"WLD": {"hl_bid": 0.385, "hl_ask": 0.386, "depth_usd": 3000.0, "collecte_ts": time.time() - 10}}))
    assert C._book_ws_frais("WLD") is None                                # périmé -> None (pas de fraîcheur inventée)


def test_vault_du_message_demux_multiplex():
    """Multiplex userFills : on démux par data.user, mappé sur la forme canonique abonnée (casse insensible)."""
    connus = {v.lower(): v for v in ["0xAbCdEf01", "0x12345678"]}
    m = {"channel": "userFills", "data": {"user": "0xabcdef01", "fills": []}}
    assert C._vault_du_message(m, connus) == "0xAbCdEf01"                 # casse insensible -> canonique abonné
    assert C._vault_du_message({"data": {"user": "0xZZZZ"}}, connus) is None   # user inconnu -> None
    assert C._vault_du_message({"data": {}}, connus) is None              # pas de user -> None
    assert C._vault_du_message({"channel": "x"}, connus) is None          # message sans data -> None


def test_shards_userfills_disjoints_de_5():
    """Sharding DÉTERMINISTE en groupes de 5 (HL cape ~5/connexion) : 2 sockets A/B disjoints couvrant tout."""
    vaults = ["0xv%02d" % i for i in range(10)]
    shards = C._shards_userfills(vaults, taille=5)
    assert [s for s, _ in shards] == ["A", "B"] and len(shards) == 2   # 2 sockets
    a, b = shards[0][1], shards[1][1]
    assert a == vaults[:5] and b == vaults[5:]                        # déterministe, 5 chacun
    assert set(a).isdisjoint(set(b)) and set(a) | set(b) == set(vaults)   # DISJOINTS + couvrent tout (pas de doublon)
    # 8 vaults -> A(5) + B(3)
    assert [len(g) for _, g in C._shards_userfills(vaults[:8], taille=5)] == [5, 3]
