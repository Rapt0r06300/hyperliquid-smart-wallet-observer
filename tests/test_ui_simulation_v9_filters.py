from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.simulation_log_export import LOGS_TO_SEND_DIRNAME
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def _client(tmp_path: Path) -> tuple[TestClient, object, UiState]:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_v9_filters.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 3_600_000
    client = TestClient(create_ui_app(settings, state))
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    return client, factory, state


def test_simulation_overview_uses_snapshot_when_runtime_db_is_huge(tmp_path: Path, monkeypatch):
    settings = load_settings()
    db_path = tmp_path / "data" / "huge_runtime.sqlite3"
    settings.database_url = f"sqlite:///{db_path}"
    settings.logs_dir = str(tmp_path / "logs")
    init_db(settings.database_url)
    # The production incident is a multi-GB runtime DB. This test inflates the
    # temp DB just enough to trigger the same fast snapshot path without reading
    # the corrupt/inflated file again.
    with db_path.open("ab") as handle:
        handle.write(b"0" * (2 * 1024 * 1024))
    logs_to_send = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
    logs_to_send.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA",
        "bot_simulation": {
            "current_equity_usdt": 1001.25,
            "estimated_net_pnl_usdc": 1.25,
            "open_positions": [{"coin": "BTC"}, {"coin": "ETH"}],
            "events": [{"coin": "BTC"}, {"coin": "ETH"}, {"coin": "SOL"}],
        },
        "leaders": [{"wallet_address": "0x" + "1" * 40}, {"wallet_address": "0x" + "2" * 40}],
    }
    (logs_to_send / "simulation_snapshot_latest.json").write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_DB_THRESHOLD_MB", "1")

    client = TestClient(create_ui_app(settings, UiState()))
    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["overview_fast_snapshot"] is True
    assert payload["bot_simulation"]["current_equity_usdt"] == 1001.25
    assert len(payload["bot_simulation"]["events"]) == 1
    assert len(payload["leaders"]) == 1


def test_simulation_overview_huge_db_uses_live_state_when_snapshot_is_stale_or_empty(tmp_path: Path, monkeypatch):
    settings = load_settings()
    db_path = tmp_path / "data" / "huge_runtime_live_state.sqlite3"
    settings.database_url = f"sqlite:///{db_path}"
    settings.logs_dir = str(tmp_path / "logs")
    init_db(settings.database_url)
    with db_path.open("ab") as handle:
        handle.write(b"0" * (2 * 1024 * 1024))
    logs_to_send = Path(settings.logs_dir) / LOGS_TO_SEND_DIRNAME
    logs_to_send.mkdir(parents=True, exist_ok=True)
    stale_snapshot = logs_to_send / "simulation_snapshot_latest.json"
    stale_snapshot.write_text(json.dumps({"mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA"}), encoding="utf-8")
    os.utime(stale_snapshot, (1, 1))
    state = UiState()
    state.simulation_starting_equity_usdt = 1000.0
    state.simulation_realized_pnl_usdc = 2.5
    state.simulation_virtual_positions = {
        "paper-pos-1": {
            "coin": "HYPE",
            "side": "LONG",
            "entry_price": 40.0,
            "size": 1.0,
            "unrealized_pnl_usdc": 0.5,
        }
    }
    state.simulation_equity_history = [
        {
            "timestamp_ms": 1_800_000_000_000,
            "current_equity_usdt": 1003.0,
            "current_pnl_usdc": 3.0,
            "realized_pnl_usdc": 2.5,
            "unrealized_pnl_usdc": 0.5,
            "open_exposure_usdt": 40.0,
        }
    ]
    state.simulation_ledger_events = [
        {
            "delta_key": "paper-close-1",
            "observed_at_ms": 1_800_000_000_000,
            "coin": "HYPE",
            "paper_action_type": "CLOSE",
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "estimated_net_pnl_usdc": 2.5,
            "paper_position_instance_id": "paper-pos-closed-1",
        }
    ]
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_SNAPSHOT", "1")
    monkeypatch.setenv("HYPERSMART_OVERVIEW_FAST_DB_THRESHOLD_MB", "1")

    client = TestClient(create_ui_app(settings, state))
    payload = client.get("/api/simulation/overview?limit=5").json()

    assert payload["overview_fast_state"] is True
    assert payload["overview_fast_snapshot"] is False
    assert payload["equity"]["current_equity_usdt"] == 1003.0
    assert payload["bot_simulation"]["current_equity_usdt"] == 1003.0
    assert payload["paper_ledger"]["closed_trade_stats"]["winning_trades"] == 1
    assert payload["bot_simulation"]["closed_trades"] == 1
    exported = json.loads(stale_snapshot.read_text(encoding="utf-8"))
    assert exported["bot_simulation"]["current_equity_usdt"] == 1003.0
    assert exported["paper_ledger"]["closed_trade_stats"]["winning_trades"] == 1


def _leader(wallet: str, *, rank: int = 1, ts: int = 1) -> TopWallet:
    return TopWallet(
        wallet_address=wallet,
        rank=rank,
        source="public_trades_ws",
        score=95.0,
        selected_at_ms=ts,
        status="selected",
    )


def _open_delta(wallet: str, *, coin: str = "ETH", ts: int, raw: dict | None = None, source: str = "hyperliquid_ws:userFills") -> PositionDeltaModel:
    return PositionDeltaModel(
        wallet_address=wallet,
        coin=coin,
        previous_side="FLAT",
        new_side="LONG",
        previous_size=0.0,
        current_size=2.0,
        new_size=2.0,
        delta_size=2.0,
        delta_notional_usdc=6_000.0,
        action="OPEN",
        exchange_ts=ts,
        detected_at_ms=ts,
        source=source,
        side="B",
        price=3_000.0,
        fill_size=2.0,
        delta_type="open_long",
        confidence="high",
        confidence_score=0.95,
        is_paper_eligible=True,
        raw_json=raw or {"coin": coin, "dir": "Open Long"},
    )


def test_simulation_skips_exotic_markets_without_no_trade_noise(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "1" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"XYZ:TSLA": "3000"}))
        session.add(_open_delta(wallet, coin="XYZ:TSLA", ts=ts))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["exotic_market_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "EXOTIC_MARKET_SKIPPED"
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "NO_DATA"
    assert all(row.get("coin") != "XYZ:TSLA" for row in payload["bot_simulation"]["events"])


def test_simulation_skips_old_rest_backfill_before_scoring(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    old_fill_ts = ts - 5 * 60 * 60 * 1000
    wallet = "0x" + "2" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        row = _open_delta(
            wallet,
            ts=old_fill_ts,
            source="hyperliquid_rest:userFillsByTime",
            raw={"coin": "ETH", "dir": "Open Long", "time": old_fill_ts, "hash": "old-rest-fill"},
        )
        row.detected_at_ms = ts
        session.add(row)
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["hard_stale_entry_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "STALE_BACKFILL"
    assert payload["bot_simulation"]["prefilter_skips"][0]["signal_age_ms"] >= 5 * 60 * 60 * 1000
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "SUPPLY"
    assert payload["scanner"]["entry_supply"]["prefilter_skips"] == 1
    assert all((row.get("signal_age_ms") or 0) <= 60_000 for row in payload["bot_simulation"]["events"])


def test_simulation_dedupes_same_fill_between_poll_rows(tmp_path: Path, monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par DEFAUT le bot refuse un edge non empirique.
    # Ce test exerce l'ANCIEN chemin (edge invente) -> mode A/B EXPLICITE.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "1")
    monkeypatch.setenv("HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS", "5")
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "3" * 40
    raw = {"coin": "ETH", "dir": "Open Long", "hash": "same-fill", "tid": 11, "oid": 22, "time": ts}
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(_open_delta(wallet, ts=ts, raw=raw))
        session.add(_open_delta(wallet, ts=ts + 1, raw=raw))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "OK"
    assert payload["scanner"]["entry_supply"]["accepted_entries"] == 1
    assert payload["bot_simulation"]["filter_diagnostics"]["duplicate_delta_skipped"] == 1


def test_simulation_skips_orphan_reduce_without_ledger_noise(tmp_path: Path):
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet = "0x" + "4" * 40
    with factory() as session:
        session.add(_leader(wallet, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side="LONG",
                new_side="LONG",
                previous_size=2.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=-1.0,
                delta_notional_usdc=3_000.0,
                action="REDUCE",
                exchange_ts=ts,
                detected_at_ms=ts,
                source="hyperliquid_ws:userFills",
                side="A",
                price=3_000.0,
                fill_size=1.0,
                delta_type="reduce_long",
                confidence="high",
                confidence_score=0.95,
                raw_json={"coin": "ETH", "dir": "Close Long", "hash": "orphan-reduce", "time": ts},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["orphan_exit_skipped"] == 1
    assert payload["bot_simulation"]["prefilter_skip_count"] == 1
    assert payload["bot_simulation"]["prefilter_skips"][0]["reason"] == "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"
    assert payload["scanner"]["entry_supply"]["bottleneck"] == "SUPPLY"
    assert "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" not in {
        str(row.get("reason") or "") for row in payload["bot_simulation"]["events"]
    }


def _semer_la_table_d_edge_mesuree(racine: Path, *, markout_bps: float = 60.0) -> None:
    """🔴 #598 -- CE TEST EXIGEAIT AUTREFOIS UN EDGE **INVENTE**.

    Jusqu'au 2026-07-13, `routes.py` fabriquait l'edge d'entree avec trois constantes magiques
    (`18.0 + confidence*34 + min(24, (consensus-1)*8)`). G2 l'a tue : l'edge vient DESORMAIS de
    la **table mesuree** (Q1), **sans aucun repli**. Pas de mesure => 0 bps => refus.

    Ce test rougissait donc pour la MEILLEURE des raisons : il attendait que le bot invente un
    chiffre. On ne l'a pas « repare » en affaiblissant le garde-fou -- on lui DONNE une vraie
    mesure, et on verifie qu'il ouvre alors la position.

    (L'autre moitie de la verite est verrouillee juste en dessous : SANS mesure, il doit REFUSER.)
    """
    from hl_observer.edge.edge_source import vider_le_cache
    from hl_observer.edge.measured_edge_table import Features, Observation, construire

    obs = [
        Observation(
            features=Features(strategie="COPY", coin="ETH", direction="LONG",
                              signal_age_ms=float(age), leader_score=95.0, consensus_wallets=2.0),
            markout_bps=markout_bps + (0.5 if i % 2 else -0.5),
            signal_ms=1_000.0,
        )
        for age in (1_000.0, 2_000.0)
        for i in range(40)
    ]
    table = construire(obs, horizon_ms=60_000, min_echantillons=30)
    p = racine / "data" / "reports" / "table_edge_mesuree.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(table.vers_json(), encoding="utf-8")
    vider_le_cache()


def test_SANS_mesure_le_bot_REFUSE_au_lieu_d_inventer_un_edge(tmp_path: Path, monkeypatch):
    """🔴 L'INVARIANT QUI COMPTE (#598, 2026-07-13).

    Table d'edge ABSENTE => l'edge vaut 0 bps => le bot doit refuser, bruyamment, avec un motif
    lisible. Deny-by-default : *l'absence de mesure n'autorise rien.*

    Sans ce test, quelqu'un pourrait « reparer » le test du dessous en remettant une formule --
    et le 5e edge fabrique renaitrait.
    """
    monkeypatch.setenv("HYPERSMART_ROOT", str(tmp_path))     # aucune table ici
    # #594 : conftest pose une TEST_FIXTURE sur la porte unique pour toute la suite. Ici on veut
    # justement l'ABSENCE de mesure -- on la retire donc explicitement.
    monkeypatch.delenv("HYPERSMART_EDGE_TABLE_PATH", raising=False)
    monkeypatch.setenv("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "30000")
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "2")
    from hl_observer.edge.edge_source import vider_le_cache
    vider_le_cache()

    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wa, wb = "0x" + "a" * 40, "0x" + "b" * 40
    with factory() as session:
        session.add(_leader(wa, rank=1, ts=ts))
        session.add(_leader(wb, rank=2, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(_open_delta(wa, ts=ts - 2_000, raw={"coin": "ETH", "dir": "Open Long",
                                                        "hash": "no-edge-a", "time": ts - 2_000}))
        session.add(_open_delta(wb, ts=ts - 1_000, raw={"coin": "ETH", "dir": "Open Long",
                                                        "hash": "no-edge-b", "time": ts - 1_000}))
        session.commit()

    payload = client.get("/api/simulation/overview?limit=40").json()
    bot = payload["bot_simulation"]

    assert not bot["open_positions"], "sans edge MESURE, aucune position ne doit s'ouvrir"
    motifs = "|".join(sorted(str(r.get("reason") or "") for r in bot["events"]))
    # Le motif exact a change avec #594 (la porte unique NOMME desormais la table absente, ce qui
    # est STRICTEMENT plus informatif que l'ancien « edge trop petit »). Ce qui compte -- et ce que
    # ce test verrouille -- c'est que le refus soit EXPLICITE et parle de l'EDGE.
    assert any(m in motifs for m in (
        "EDGE_TABLE_ABSENTE",                       # #594 : la porte dit QUOI manque
        "EDGE_NON_MESURE_POUR_CE_BUCKET",
        "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS",  # l'ancien motif, toujours acceptable
    )), ("le refus doit etre EXPLICITE et lisible, pas un silence. Motifs vus : %s" % motifs)


def test_accepted_fresh_opportunity_cluster_opens_virtual_position_with_v9_authoritative(tmp_path: Path,
    monkeypatch,):
    # 🔴 #598 (2026-07-13) : l'edge d'entree vient maintenant de la TABLE MESUREE (G2), sans repli.
    # Ce test lui donne donc une VRAIE mesure. Il ne peut plus passer sur un edge invente.
    monkeypatch.setenv("HYPERSMART_ROOT", str(tmp_path))
    _semer_la_table_d_edge_mesuree(tmp_path, markout_bps=60.0)
    monkeypatch.setenv("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "5")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "30000")
    monkeypatch.setenv("HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS", "2")
    monkeypatch.setenv("HYPERSMART_RUNTIME_DEPTH_FILL_GUARD", "0")
    monkeypatch.setenv("HYPERSMART_RUNTIME_MICROSTRUCTURE_GUARD", "0")
    client, factory, _state = _client(tmp_path)
    ts = now_ms()
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    with factory() as session:
        session.add(_leader(wallet_a, rank=1, ts=ts))
        session.add(_leader(wallet_b, rank=2, ts=ts))
        session.add(MarketSnapshot(source="allMids", exchange_ts=ts, raw_json={"ETH": "3000"}))
        session.add(
            _open_delta(
                wallet_a,
                ts=ts - 2_000,
                raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-a", "time": ts - 2_000},
                source="hyperliquid_ws:userFills",
            )
        )
        session.add(
            _open_delta(
                wallet_b,
                ts=ts - 1_000,
                raw={"coin": "ETH", "dir": "Open Long", "hash": "fresh-cluster-b", "time": ts - 1_000},
                source="hyperliquid_ws:userFills",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=40").json()

    accepted_fresh = [
        row for row in payload["fresh_opportunities"]
        if row.get("decision") == "ACCEPT_LOCAL_SIMULATION"
    ]
    assert accepted_fresh
    assert payload["counts"]["reproduced_entries"] >= 1
    assert payload["bot_simulation"]["open_positions"], payload["bot_simulation"]["events"]
    accepted_events = [
        row for row in payload["bot_simulation"]["events"]
        if row.get("status") == "LOCAL_REPLAY"
    ]
    assert accepted_events
    assert any(row.get("position_mode") == "CONSENSUS_CLUSTER" for row in accepted_events)
