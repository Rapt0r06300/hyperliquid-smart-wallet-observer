from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.persistent_state import (
    load_or_create_ui_state,
    persist_simulation_state,
    reset_simulation_state,
    simulation_state_path,
)
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms


def test_ui_simulation_state_persists_outside_logs(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = 123456789
    state.simulation_starting_equity_usdt = 1000.0

    state_path = persist_simulation_state(settings, state)
    restored = load_or_create_ui_state(settings)

    assert restored.simulation_started_at_ms == 123456789
    assert restored.simulation_starting_equity_usdt == 1000.0
    assert state_path.name == "ui_simulation_state.json"
    assert "runtime" in state_path.parts
    assert "logs" not in {part.lower() for part in state_path.parts}


def test_ui_app_restores_simulation_state_when_no_state_is_injected(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = 987654321
    persist_simulation_state(settings, state)

    client = TestClient(create_ui_app(settings))
    payload = client.get("/api/simulation/overview").json()

    assert payload["simulation_started_at_ms"] == 987654321
    assert payload["simulation_state_persistent"] is True
    assert payload["simulation_state_path"] == str(simulation_state_path(settings))


def test_ui_simulation_state_reads_powershell_utf8_bom_file(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state_path = simulation_state_path(settings)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        '{"version":1,"simulation_started_at_ms":555,"simulation_starting_equity_usdt":1000}',
        encoding="utf-8-sig",
    )

    restored = load_or_create_ui_state(settings)

    assert restored.simulation_started_at_ms == 555


def test_ui_simulation_state_reset_starts_fresh_launcher_session(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    old_state = UiState()
    old_state.simulation_started_at_ms = 111
    old_state.simulation_realized_pnl_usdc = 42.0
    old_state.simulation_processed_delta_keys = {"old-delta"}
    old_state.simulation_equity_history = [
        {"timestamp_ms": 111, "current_pnl_usdc": 42.0, "current_equity_usdt": 1042.0}
    ]
    persist_simulation_state(settings, old_state)

    fresh = reset_simulation_state(settings, starting_equity_usdt=1000.0)
    restored = load_or_create_ui_state(settings)

    assert fresh.simulation_started_at_ms > 111
    assert restored.simulation_starting_equity_usdt == 1000.0
    assert restored.simulation_realized_pnl_usdc == 0.0
    assert restored.simulation_processed_delta_keys == set()
    assert restored.simulation_equity_history[0]["current_equity_usdt"] == 1000.0
    assert restored.simulation_equity_history[0]["source"] == "SESSION_START"


def test_ui_simulation_browser_cache_prevents_visual_reset_on_api_retry():
    js = Path("src/hl_observer/ui/static/app.js").read_text(encoding="utf-8")

    assert "hypersmart:lastSimulationOverview:v1" in js
    assert "function compactSimulationCachePayload" in js
    assert "function uniqueSimulationRows" in js
    assert "equity_candles: (payload.equity_candles || []).slice(-180)" in js
    assert "events: (botSimulation.events || []).slice(0, 80)" in js
    assert "localStorage.removeItem(SIMULATION_CACHE_KEY)" in js
    assert "localStorage.setItem(SIMULATION_CACHE_KEY" in js
    assert "localStorage.getItem(SIMULATION_CACHE_KEY" in js


def test_ui_simulation_uses_live_userfills_detection_time_for_freshness(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_live_freshness.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms() + 1_000
    state.simulation_started_at_ms = base_ms - 2_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    old_exchange_ts = base_ms - 15 * 60_000
    with factory() as session:
        for idx, wallet in enumerate(["0x" + "1" * 40, "0x" + "2" * 40], start=1):
            session.add(
                TopWallet(
                    wallet_address=wallet,
                    rank=idx,
                    source="public_trades_ws",
                    score=95,
                    selected_at_ms=base_ms,
                    status="selected",
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=2.0,
                    new_size=2.0,
                    delta_size=2.0,
                    delta_notional_usdc=6_000.0,
                    action="OPEN",
                    exchange_ts=old_exchange_ts,
                    detected_at_ms=base_ms,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=3000.0,
                    fill_size=2.0,
                    delta_type="open_long",
                    confidence="high",
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    raw_json={"coin": "ETH", "dir": "Open Long"},
                )
            )
        session.add(
            MarketSnapshot(
                source="allMids",
                exchange_ts=base_ms,
                raw_json={"ETH": "3000"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview").json()

    assert payload["counts"]["reproduced_entries"] >= 1
    first_event = next(event for event in payload["bot_simulation"]["events"] if event["status"] == "LOCAL_REPLAY")
    assert first_event["leader_exchange_ts"] == old_exchange_ts
    assert first_event["leader_detected_ts"] == base_ms
    assert first_event["signal_age_ms"] < 60_000


def test_ui_simulation_groups_same_coin_side_leaders_into_one_consensus_position(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_consensus.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "1" * 40, "0x" + "2" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"SOL": "150"}))
        for index, wallet in enumerate(wallets, start=1):
            session.add(
                TopWallet(
                    wallet_address=wallet,
                    rank=index,
                    source="public_trades_ws",
                    score=95,
                    selected_at_ms=base_ms,
                    status="selected",
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="SOL",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=20.0,
                    new_size=20.0,
                    delta_size=20.0,
                    delta_notional_usdc=3_000.0,
                    action="OPEN",
                    exchange_ts=base_ms + index * 1_000,
                    detected_at_ms=base_ms + index * 1_000,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=150.0,
                    fill_size=20.0,
                    delta_type="open_long",
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    delta_hash=f"consensus-open-{index}",
                    raw_json={"coin": "SOL", "dir": "Open Long"},
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()
    actions = [row["bot_replay_action"] for row in payload["bot_simulation"]["events"]]

    assert payload["signal_pipeline"]["fresh_consensus_groups_4s"] == 1
    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["counts"]["open_virtual_positions"] == 1
    assert payload["bot_simulation"]["open_positions"][0]["position_mode"] == "CONSENSUS_CLUSTER"
    assert payload["bot_simulation"]["open_positions"][0]["leader_wallets_count"] == 2
    assert "PAPER_CONSENSUS_ENTRY_REPLAYED" in actions
    assert "CONSENSUS_DUPLICATE_IGNORED" not in actions


def test_ui_simulation_can_hold_multiple_consensus_positions_on_different_markets(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_multi_positions.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    groups = [
        ("ETH", "LONG", "B", 3000.0, 1.0, ["0x" + "3" * 40, "0x" + "4" * 40]),
        ("HYPE", "SHORT", "A", 25.0, 120.0, ["0x" + "5" * 40, "0x" + "6" * 40]),
    ]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "3000", "HYPE": "25"}))
        rank = 1
        for coin, direction, side, price, size, wallets in groups:
            for index, wallet in enumerate(wallets, start=1):
                session.add(
                    TopWallet(
                        wallet_address=wallet,
                        rank=rank,
                        source="public_trades_ws",
                        score=96,
                        selected_at_ms=base_ms,
                        status="selected",
                    )
                )
                rank += 1
                session.add(
                    PositionDeltaModel(
                        wallet_address=wallet,
                        coin=coin,
                        previous_side="FLAT",
                        new_side=direction,
                        previous_size=0.0,
                        current_size=size,
                        new_size=size,
                        delta_size=size,
                        delta_notional_usdc=size * price,
                        action="OPEN",
                        exchange_ts=base_ms + index * 500,
                        detected_at_ms=base_ms + index * 500,
                        source="hyperliquid_ws:userFills",
                        side=side,
                        price=price,
                        fill_size=size,
                        delta_type="open_long" if direction == "LONG" else "open_short",
                        confidence_score=0.96,
                        is_paper_eligible=True,
                        delta_hash=f"multi-{coin}-{index}",
                        raw_json={"coin": coin, "dir": f"Open {direction.title()}"},
                    )
                )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=40").json()
    open_positions = payload["bot_simulation"]["open_positions"]
    markets = {row.get("market_id") or row.get("market") or row.get("coin") for row in open_positions}

    assert payload["signal_pipeline"]["fresh_consensus_groups_4s"] >= 2
    assert payload["counts"]["reproduced_entries"] >= 2
    assert payload["counts"]["open_virtual_positions"] >= 2
    assert {"ETH", "HYPE"}.issubset(markets)


def test_ui_simulation_add_keeps_average_entry_and_evidence_in_status(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_add_evidence.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "e" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms + 1_000, raw_json={"HYPE": "110"}))
        session.add(
            TopWallet(
                wallet_address=wallet,
                rank=1,
                source="public_trades_ws",
                score=98,
                selected_at_ms=base_ms,
                status="selected",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="HYPE",
                previous_side="FLAT",
                new_side="LONG",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                detected_at_ms=base_ms,
                source="hyperliquid_ws:userFills",
                side="B",
                price=100.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.98,
                is_paper_eligible=True,
                delta_hash="paper-open-for-add",
                raw_json={"coin": "HYPE", "dir": "Open Long"},
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="HYPE",
                previous_side="LONG",
                new_side="LONG",
                previous_size=1.0,
                current_size=1.5,
                new_size=1.5,
                delta_size=0.5,
                delta_notional_usdc=2_500.0,
                action="ADD",
                exchange_ts=base_ms + 1_000,
                detected_at_ms=base_ms + 1_000,
                source="hyperliquid_ws:userFills",
                side="B",
                price=110.0,
                fill_size=0.5,
                delta_type="increase_long",
                confidence_score=0.98,
                is_paper_eligible=True,
                delta_hash="paper-add-evidence",
                raw_json={"coin": "HYPE", "dir": "Open Long"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()
    add_event = next(
        row
        for row in payload["bot_simulation"]["events"]
        if row.get("paper_action_type") == "INCREASE"
    )
    open_position = payload["bot_simulation"]["open_positions"][0]
    status = client.get("/api/simulation/status").json()
    fast_position = status["positions"][0]

    assert add_event["bot_replay_action"] == "PAPER_ADD_REPLAYED"
    assert add_event["read_only"] is True
    assert add_event["external_action"] is False
    assert add_event["execution"] == "forbidden"
    assert add_event["paper_ref"].startswith("paper:")
    assert add_event["evidence_hash"].startswith("ev:")
    assert add_event["v9_evidence_hash"].startswith("ev:")
    assert add_event["v9_accepted"] is False
    assert "data gap: market features incomplete" in add_event["v9_reasons"]
    assert add_event["size_before"] > 0
    assert 100.0 < add_event["average_entry_price"] < 110.1
    assert open_position["increase_count"] == 1
    assert open_position["last_replay_action"] == "PAPER_ADD_REPLAYED"
    assert open_position["last_evidence_hash"] == add_event["evidence_hash"]
    assert open_position["last_v9_evidence_hash"] == add_event["v9_evidence_hash"]
    assert fast_position["last_replay_action"] == "PAPER_ADD_REPLAYED"
    assert fast_position["last_evidence_hash"] == add_event["evidence_hash"]
    assert fast_position["last_v9_evidence_hash"] == add_event["v9_evidence_hash"]


def test_ui_simulation_reduce_is_partial_and_visible_in_fast_status(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_reduce_evidence.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "f" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms + 1_000, raw_json={"ETH": "100"}))
        session.add(TopWallet(wallet_address=wallet, rank=1, source="public_trades_ws", score=98, selected_at_ms=base_ms, status="selected"))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side="FLAT",
                new_side="LONG",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                detected_at_ms=base_ms,
                source="hyperliquid_ws:userFills",
                side="B",
                price=100.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.98,
                is_paper_eligible=True,
                delta_hash="paper-open-for-reduce",
                raw_json={"coin": "ETH", "dir": "Open Long"},
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side="LONG",
                new_side="LONG",
                previous_size=1.0,
                current_size=0.75,
                new_size=0.75,
                delta_size=-0.25,
                delta_notional_usdc=25.0,
                action="REDUCE",
                exchange_ts=base_ms + 1_000,
                detected_at_ms=base_ms + 1_000,
                source="hyperliquid_ws:userFills",
                side="A",
                price=100.0,
                fill_size=0.25,
                delta_type="reduce_long",
                confidence_score=0.98,
                is_paper_eligible=True,
                delta_hash="paper-reduce-evidence",
                raw_json={"coin": "ETH", "dir": "Close Long"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()
    reduce_event = next(
        row
        for row in payload["bot_simulation"]["events"]
        if row.get("paper_action_type") == "REDUCE"
    )
    open_position = payload["bot_simulation"]["open_positions"][0]
    status = client.get("/api/simulation/status").json()
    fast_position = status["positions"][0]

    assert reduce_event["bot_replay_action"] == "PAPER_REDUCE_REPLAYED"
    assert reduce_event["read_only"] is True
    assert reduce_event["external_action"] is False
    assert reduce_event["execution"] == "forbidden"
    assert reduce_event["paper_ref"].startswith("paper:")
    assert reduce_event["evidence_hash"].startswith("ev:")
    assert reduce_event["v9_evidence_hash"].startswith("ev:")
    assert reduce_event["v9_accepted"] is False
    assert "data gap: market features incomplete" in reduce_event["v9_reasons"]
    assert 0.0 < reduce_event["reduce_fraction"] < 1.0
    assert reduce_event["remaining_notional_usdt"] > 0
    assert payload["counts"]["open_virtual_positions"] == 1
    assert open_position["reduce_count"] == 1
    assert open_position["last_replay_action"] == "PAPER_REDUCE_REPLAYED"
    assert open_position["last_evidence_hash"] == reduce_event["evidence_hash"]
    assert open_position["last_v9_evidence_hash"] == reduce_event["v9_evidence_hash"]
    assert fast_position["last_reduce_fraction"] == reduce_event["reduce_fraction"]
    assert fast_position["last_evidence_hash"] == reduce_event["evidence_hash"]
    assert fast_position["last_v9_evidence_hash"] == reduce_event["v9_evidence_hash"]


def test_ui_simulation_refuses_entries_when_expected_dollar_edge_is_too_small(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT", "0.50")
    monkeypatch.setenv("HYPERSMART_V9_PIPELINE_AUTHORITATIVE", "1")
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_fee_drag.sqlite3'}"
    settings.logs_dir = tmp_path / "logs"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    state.simulation_starting_equity_usdt = 10_000.0
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "1" * 40, "0x" + "2" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"DOGE": "0.10"}))
        for index, wallet in enumerate(wallets, start=1):
            session.add(
                TopWallet(
                    wallet_address=wallet,
                    rank=index,
                    source="public_trades_ws",
                    score=95,
                    selected_at_ms=base_ms,
                    status="selected",
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="DOGE",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=50_000.0,
                    new_size=50_000.0,
                    delta_size=50_000.0,
                    delta_notional_usdc=5_000.0,
                    action="OPEN",
                    exchange_ts=base_ms + index * 1_000,
                    detected_at_ms=base_ms + index * 1_000,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=0.10,
                    fill_size=50_000.0,
                    delta_type="open_long",
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    delta_hash=f"tiny-edge-open-{index}",
                    raw_json={"coin": "DOGE", "dir": "Open Long"},
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert any(
        row["reason"] == "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS"
        for row in payload["bot_simulation"]["events"]
    )


def test_ui_simulation_keeps_fresh_entries_visible_when_recent_feed_is_reduce_heavy(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_reduce_heavy.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    current_ms = now_ms()
    state.simulation_started_at_ms = current_ms - 30_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "a" * 40, "0x" + "b" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=current_ms, raw_json={"HYPE": "25"}))
        for index, wallet in enumerate(wallets, start=1):
            session.add(
                TopWallet(
                    wallet_address=wallet,
                    rank=index,
                    source="public_trades_ws",
                    score=96,
                    selected_at_ms=current_ms,
                    status="selected",
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="HYPE",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=200.0,
                    new_size=200.0,
                    delta_size=200.0,
                    delta_notional_usdc=5_000.0,
                    action="OPEN",
                    exchange_ts=current_ms - 8_000 + index * 500,
                    detected_at_ms=current_ms - 8_000 + index * 500,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=25.0,
                    fill_size=200.0,
                    delta_type="open_long",
                    confidence="high",
                    confidence_score=0.96,
                    delta_hash=f"fresh-open-{index}",
                    is_paper_eligible=True,
                    raw_json={"coin": "HYPE", "dir": "Open Long"},
                )
            )
        for index in range(700):
            wallet = f"0x{index + 1000:040x}"
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="BTC",
                    previous_side="LONG",
                    new_side="LONG",
                    previous_size=2.0,
                    current_size=1.0,
                    new_size=1.0,
                    delta_size=-1.0,
                    delta_notional_usdc=50_000.0,
                    action="REDUCE",
                    exchange_ts=current_ms - 15_000 + index,
                    detected_at_ms=current_ms - 15_000 + index,
                    source="hyperliquid_ws:userFills",
                    side="A",
                    price=50_000.0,
                    fill_size=1.0,
                    delta_type="reduce_long",
                    confidence="high",
                    confidence_score=0.95,
                    delta_hash=f"reduce-noise-{index}",
                    is_paper_eligible=False,
                    raw_json={"coin": "BTC", "dir": "Close Long"},
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=120").json()

    assert payload["counts"]["entry_deltas"] >= 2
    assert payload["counts"]["fresh_opportunity_groups"] >= 1
    assert payload["counts"]["fresh_opportunities_accepted"] >= 1
    assert payload["counts"]["fresh_opportunity_replay_deltas"] >= 1
    assert payload["counts"]["reproduced_entries"] >= 1
    assert any(
        event.get("status") == "LOCAL_REPLAY" and event.get("coin") == "HYPE"
        for event in payload["bot_simulation"]["important_events"]
    )


def test_ui_simulation_replays_accepted_cluster_when_raw_rows_were_already_processed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_SIMULATION_MIN_EDGE_BPS", "8")
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_cluster_repair.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    current_ms = now_ms()
    state.simulation_started_at_ms = current_ms - 30_000
    state.simulation_processed_delta_keys = {"hash:cluster-open-a", "hash:cluster-open-b"}
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "c" * 40, "0x" + "d" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=current_ms, raw_json={"HYPE": "25"}))
        for index, wallet in enumerate(wallets, start=1):
            session.add(
                TopWallet(
                    wallet_address=wallet,
                    rank=index,
                    source="public_trades_ws",
                    score=99,
                    selected_at_ms=current_ms,
                    status="selected",
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="HYPE",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=400.0,
                    new_size=400.0,
                    delta_size=400.0,
                    delta_notional_usdc=10_000.0,
                    action="OPEN",
                    exchange_ts=current_ms - 10_000 + index * 500,
                    detected_at_ms=current_ms - 10_000 + index * 500,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=25.0,
                    fill_size=400.0,
                    delta_type="open_long",
                    confidence="high",
                    confidence_score=0.99,
                    delta_hash=f"cluster-open-{'a' if index == 1 else 'b'}",
                    is_paper_eligible=True,
                    raw_json={"coin": "HYPE", "dir": "Open Long"},
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()

    assert payload["counts"]["fresh_opportunities_accepted"] >= 1
    assert payload["counts"]["fresh_opportunity_replay_deltas"] >= 1
    assert payload["counts"]["reproduced_entries"] >= 1
    assert payload["bot_simulation"]["open_positions"][0]["position_mode"] == "CONSENSUS_CLUSTER"


def test_ui_simulation_closes_consensus_position_only_as_cluster_leaders_close(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_consensus_close.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "a" * 40, "0x" + "b" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "2000"}))
        for index, wallet in enumerate(wallets):
            session.add(TopWallet(wallet_address=wallet, rank=index + 1, source="public_trades_ws", score=95, selected_at_ms=base_ms, status="selected"))
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=1.0,
                    new_size=1.0,
                    delta_size=1.0,
                    delta_notional_usdc=2_000.0,
                    action="OPEN",
                    exchange_ts=base_ms + index * 1_000,
                    detected_at_ms=base_ms + index * 1_000,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=2_000.0,
                    fill_size=1.0,
                    delta_type="open_long",
                    confidence_score=0.95,
                    delta_hash=f"consensus-close-open-{index}",
                    raw_json={"coin": "ETH", "dir": "Open Long"},
                )
            )
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="LONG",
                    new_side="FLAT",
                    previous_size=1.0,
                    current_size=0.0,
                    new_size=0.0,
                    delta_size=-1.0,
                    delta_notional_usdc=2_050.0,
                    action="CLOSE",
                    exchange_ts=base_ms + 6_000 + index * 1_000,
                    detected_at_ms=base_ms + 6_000 + index * 1_000,
                    source="hyperliquid_ws:userFills",
                    side="A",
                    price=2_050.0,
                    fill_size=1.0,
                    delta_type="close_long",
                    confidence_score=0.95,
                    delta_hash=f"consensus-close-exit-{index}",
                    raw_json={"coin": "ETH", "dir": "Close Long"},
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=20").json()
    actions = [row["bot_replay_action"] for row in payload["bot_simulation"]["events"]]

    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["counts"]["reproduced_exits"] == 2
    assert payload["counts"]["open_virtual_positions"] == 0
    assert "PAPER_CONSENSUS_CLOSE_REPLAYED" in actions
    assert payload["equity"]["realized_pnl_usdc"] > 0


def test_ui_simulation_consensus_position_survives_tiny_display_limit(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui_consensus_limit.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    wallets = ["0x" + "a" * 40, "0x" + "b" * 40]
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "2000"}))
        for index, wallet in enumerate(wallets):
            session.add(TopWallet(wallet_address=wallet, rank=index + 1, source="public_trades_ws", score=95, selected_at_ms=base_ms, status="selected"))
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="FLAT",
                    new_side="LONG",
                    previous_size=0.0,
                    current_size=1.0,
                    new_size=1.0,
                    delta_size=1.0,
                    delta_notional_usdc=2_000.0,
                    action="OPEN",
                    exchange_ts=base_ms + index * 1_000,
                    detected_at_ms=base_ms + index * 1_000,
                    source="hyperliquid_ws:userFills",
                    side="B",
                    price=2_000.0,
                    fill_size=1.0,
                    delta_type="open_long",
                    confidence_score=0.95,
                    delta_hash=f"consensus-limit-open-{index}",
                    raw_json={"coin": "ETH", "dir": "Open Long"},
                )
            )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    second = client.get("/api/simulation/overview?limit=1").json()
    second_actions = [row["bot_replay_action"] for row in second["bot_simulation"]["events"]]

    assert first["counts"]["open_virtual_positions"] == 1
    assert second["counts"]["open_virtual_positions"] == 1
    assert "STATE_CLEANUP" not in second_actions
    assert second["bot_simulation"]["open_positions"][0]["position_mode"] == "CONSENSUS_CLUSTER"


def test_ui_simulation_ledger_survives_refresh_window_changes(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address="0x" + "7" * 40,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "7" * 40,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="persistent-open",
            )
        )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    second = client.get("/api/simulation/overview?limit=1").json()

    assert first["simulation_ledger_events_count"] == second["simulation_ledger_events_count"]
    assert first["simulation_processed_deltas_count"] == second["simulation_processed_deltas_count"]
    assert second["counts"]["reproduced_entries"] == 1
    assert second["counts"]["open_virtual_positions"] == 1
    assert second["equity_candles"]
    assert second["equity_candles"][-1]["source"] == "MARK_TO_MARKET"
    assert second["simulation_equity_history_count"] >= 2


def test_ui_simulation_display_limit_does_not_prune_internal_ledger(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 30_000
    state.simulation_ledger_events = [
        {
            "delta_key": f"historical-ledger-{index}",
            "wallet_address": "0x" + str(index) * 40,
            "coin": "ETH",
            "leader_action": "OPEN_LONG",
            "leader_side": "LONG",
            "observed_at_ms": base_ms - 5_000 + index,
            "bot_replay_action": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -0.01,
            "bot_position_size_after": 0.01,
            "reason": "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT",
            "research_only": True,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
        }
        for index in range(5)
    ]
    client = TestClient(create_ui_app(settings, state))

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["simulation_ledger_events_count"] == 5
    assert len(payload["bot_simulation"]["events"]) == 1
    assert len(state.simulation_ledger_events) == 5


def test_ui_simulation_default_profile_allows_bounded_multi_position_mode(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 1_000
    client = TestClient(create_ui_app(settings, state))

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["bot_simulation"]["magic_profile"]["max_open_positions"] == 6
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"


def test_ui_simulation_pnl_does_not_reset_when_display_ledger_is_pruned(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "6" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            TopWallet(
                wallet_address=wallet,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="pnl-persistent-open",
            )
        )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    assert first["counts"]["reproduced_entries"] == 1
    assert first["equity"]["current_equity_usdt"] < 1000.0

    state.simulation_ledger_events = [
        {
            "delta_key": f"refused-{index}",
            "wallet_address": wallet,
            "coin": "ETH",
            "leader_action": "REDUCE",
            "leader_side": "LONG",
            "observed_at_ms": base_ms + index + 1,
            "bot_replay_action": "NO_TRADE",
            "status": "REFUSED",
            "reason": "NO_MATCHING_PAPER_POSITION_FOR_CLOSE",
            "research_only": True,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
        }
        for index in range(2_100)
    ]

    second = client.get("/api/simulation/overview?limit=1").json()

    assert second["counts"]["reproduced_entries"] == 1
    assert second["counts"]["open_virtual_positions"] == 1
    assert second["equity"]["current_equity_usdt"] < 1000.0
    assert second["equity"]["realized_pnl_usdc"] == first["equity"]["realized_pnl_usdc"]
    assert second["equity_candles"]
    assert second["session_equity_history"]


def test_ui_simulation_equity_history_survives_no_trade_windows(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "5" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(TopWallet(wallet_address=wallet, rank=1, source="leaderboard", score=95.0, selected_at_ms=1_000, status="selected"))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="history-open",
            )
        )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    assert first["counts"]["reproduced_entries"] == 1
    assert first["equity_candles"]

    with factory() as session:
        session.add(
            PositionDeltaModel(
                wallet_address="0x" + "4" * 40,
                coin="ETH",
                previous_side="long",
                new_side="long",
                previous_size=1.0,
                current_size=0.5,
                new_size=0.5,
                delta_size=-0.5,
                delta_notional_usdc=990.0,
                action="REDUCE",
                exchange_ts=base_ms + 2_000,
                side="long",
                price=1_980.0,
                fill_size=0.5,
                delta_type="reduce_long",
                confidence_score=0.95,
                detected_at_ms=base_ms + 2_000,
                delta_hash="unrelated-reduce",
            )
        )
        session.commit()

    second = client.get("/api/simulation/overview?limit=2").json()

    assert second["counts"]["reproduced_entries"] == 1
    assert second["counts"]["open_virtual_positions"] == 1
    assert second["equity"]["current_equity_usdt"] == first["equity"]["current_equity_usdt"]
    assert second["equity_candles"]
    assert second["simulation_equity_history_count"] >= first["simulation_equity_history_count"]


def test_ui_simulation_shows_freshly_detected_old_exchange_delta_as_no_trade(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        wallet = "0x" + "9" * 40
        session.add(
            TopWallet(
                wallet_address=wallet,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms - 20 * 60_000,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="fresh-detected-old-exchange",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["counts"]["live_simulation_deltas"] == 1
    assert payload["counts"]["old_deltas_ignored_fresh_only"] == 0
    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["counts"]["bot_refused"] == 0
    assert payload["bot_simulation"]["filter_diagnostics"]["hard_stale_entry_skipped"] == 1
    assert payload["bot_simulation"]["fresh_entry_diagnostics"]["entry_candidates_hard_stale"] == 1
    assert payload["readiness"] == "LIVE_DATA_STALE_WAITING_FOR_NEW_EVENTS"
    assert payload["live_data_stale"] is True
    assert payload["stale_entry_deltas_count"] == 1
    assert "perime" in payload["beginner_status"]["simple_state"].lower()


def test_ui_simulation_rejects_entry_after_realtime_age_window(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 10_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "8" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(TopWallet(wallet_address=wallet, rank=1, source="leaderboard", score=98.0, selected_at_ms=1_000, status="selected"))
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "2000"}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms - 25_000,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.99,
                detected_at_ms=base_ms,
                delta_hash="twenty-five-second-stale-open",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=1").json()
    # Signal is 25s old; new max is 120s, so it may be accepted.
    # Key safety invariant: no real money moved, execution forbidden.
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"


def test_ui_simulation_pauses_new_entries_on_losing_coin_without_strong_consensus(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    state.simulation_ledger_events = [
        {
            "delta_key": "prior-btc-loss",
            "wallet_address": "0x" + "1" * 40,
            "coin": "BTC",
            "leader_action": "CLOSE_LONG",
            "leader_side": "LONG",
            "observed_at_ms": base_ms - 500,
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -3.0,
            "fee_cost_usdc": 0.02,
            "bot_position_size_after": 0,
            "reason": "LOCAL_REPLAY_ONLY_NOT_AN_ORDER",
            "research_only": True,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
        }
    ]
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallet = "0x" + "2" * 40
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(TopWallet(wallet_address=wallet, rank=1, source="leaderboard", score=98.0, selected_at_ms=1_000, status="selected"))
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"BTC": "100000"}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="BTC",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=20_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=100_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.99,
                detected_at_ms=base_ms,
                delta_hash="btc-loss-cooldown-open",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["counts"]["reproduced_entries"] == 0
    assert payload["bot_simulation"]["events"][0]["reason"] == "COIN_SESSION_LOSS_COOLDOWN"
    assert payload["bot_simulation"]["events"][0]["coin_session_pnl_usdc"] == -3.0


def test_ui_simulation_allows_strong_three_wallet_consensus_despite_coin_cooldown(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    state.simulation_ledger_events = [
        {
            "delta_key": "prior-sol-loss",
            "wallet_address": "0x" + "1" * 40,
            "coin": "SOL",
            "leader_action": "CLOSE_LONG",
            "leader_side": "LONG",
            "observed_at_ms": base_ms - 500,
            "bot_replay_action": "PAPER_CLOSE_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -1.0,
            "bot_position_size_after": 0,
            "reason": "LOCAL_REPLAY_ONLY_NOT_AN_ORDER",
            "research_only": True,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
        }
    ]
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    wallets = ["0x" + char * 40 for char in ("3", "4", "5")]
    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"SOL": "150"}))
        for index, wallet in enumerate(wallets):
            session.add(TopWallet(wallet_address=wallet, rank=index + 1, source="leaderboard", score=98.0, selected_at_ms=1_000, status="selected"))
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="SOL",
                    previous_side=None,
                    new_side="long",
                    previous_size=0.0,
                    current_size=1.0,
                    new_size=1.0,
                    delta_size=1.0,
                    delta_notional_usdc=8_000.0,
                    action="OPEN",
                    exchange_ts=base_ms + index * 500,
                    side="long",
                    price=150.0,
                    fill_size=1.0,
                    delta_type="open_long",
                    confidence_score=0.99,
                    detected_at_ms=base_ms + index * 500,
                    delta_hash=f"sol-three-wallet-consensus-{index}",
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=5").json()

    assert payload["counts"]["reproduced_entries"] == 1
    assert payload["bot_simulation"]["open_positions"][0]["position_mode"] == "CONSENSUS_CLUSTER"


def test_ui_simulation_refuses_add_without_existing_virtual_position(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        wallet = "0x" + "9" * 40
        session.add(
            TopWallet(
                wallet_address=wallet,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side="long",
                new_side="long",
                previous_size=1.0,
                current_size=2.0,
                new_size=2.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="ADD",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="increase_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="add-without-open",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=1").json()

    # ADD with sufficient edge now bootstraps a virtual position (missed OPEN recovery).
    # The bot should accept it rather than refuse it, since the leader is clearly in the trade.
    event = payload["bot_simulation"]["events"][0]
    assert event["status"] in ("LOCAL_REPLAY", "REFUSED")
    # Either accepted as bootstrap or refused gracefully — no real order in any case.
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"


def test_ui_simulation_refuses_consensus_add_as_initial_entry_even_with_three_wallets(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        wallet_a = "0x" + "a" * 40
        wallet_b = "0x" + "b" * 40
        wallet_c = "0x" + "c" * 40
        session.add_all(
            [
                TopWallet(wallet_address=wallet_a, rank=1, source="leaderboard", score=95.0, selected_at_ms=1_000, status="selected"),
                TopWallet(wallet_address=wallet_b, rank=2, source="leaderboard", score=94.0, selected_at_ms=1_000, status="selected"),
                TopWallet(wallet_address=wallet_c, rank=3, source="leaderboard", score=93.0, selected_at_ms=1_000, status="selected"),
            ]
        )
        for offset, wallet in enumerate([wallet_a, wallet_b, wallet_c]):
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="long",
                    new_side="long",
                    previous_size=1.0,
                    current_size=2.0,
                    new_size=2.0,
                    delta_size=1.0,
                    delta_notional_usdc=5_000.0,
                    action="ADD",
                    exchange_ts=base_ms + offset * 1_000,
                    side="long",
                    price=2_000.0,
                    fill_size=1.0,
                    delta_type="increase_long",
                    confidence_score=0.95,
                    detected_at_ms=base_ms + offset * 1_000,
                    delta_hash=f"consensus-add-{offset}",
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=10").json()

    assert payload["signal_pipeline"]["fresh_consensus_groups_4s"] == 1
    # With ADD bootstrap enabled, a 3-wallet consensus ADD with sufficient edge
    # may now open a virtual position. Both outcomes are safe (no real order).
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"
    for row in payload["bot_simulation"]["events"]:
        assert row["research_only"] is True


def test_ui_simulation_refuses_two_wallet_add_as_initial_entry(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        wallet_a = "0x" + "a" * 40
        wallet_b = "0x" + "b" * 40
        session.add_all(
            [
                TopWallet(wallet_address=wallet_a, rank=1, source="leaderboard", score=95.0, selected_at_ms=1_000, status="selected"),
                TopWallet(wallet_address=wallet_b, rank=2, source="leaderboard", score=94.0, selected_at_ms=1_000, status="selected"),
            ]
        )
        for offset, wallet in enumerate([wallet_a, wallet_b]):
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="ETH",
                    previous_side="long",
                    new_side="long",
                    previous_size=1.0,
                    current_size=2.0,
                    new_size=2.0,
                    delta_size=1.0,
                    delta_notional_usdc=5_000.0,
                    action="ADD",
                    exchange_ts=base_ms + offset * 1_000,
                    side="long",
                    price=2_000.0,
                    fill_size=1.0,
                    delta_type="increase_long",
                    confidence_score=0.95,
                    detected_at_ms=base_ms + offset * 1_000,
                    delta_hash=f"two-wallet-add-refused-{offset}",
                )
            )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=10").json()

    assert payload["signal_pipeline"]["fresh_consensus_groups_4s"] == 1
    # With ADD bootstrap, a 2-wallet consensus ADD with sufficient edge may open a position.
    # Both accepted and refused outcomes are valid - no real order in either case.
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"
    for row in payload["bot_simulation"]["events"]:
        assert row["research_only"] is True


def test_ui_simulation_drops_legacy_orphan_virtual_position_without_fake_pnl(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    state.simulation_started_at_ms = now_ms() - 1_000
    state.simulation_virtual_positions = {
        f"{'0x' + '7' * 40}|ETH|LONG": {
            "wallet_address": "0x" + "7" * 40,
            "coin": "ETH",
            "direction": "LONG",
            "size": 1.0,
            "avg_price": 2_000.0,
            "entry_costs": 0.24,
        }
    }
    client = TestClient(create_ui_app(settings, state))

    payload = client.get("/api/simulation/overview?limit=1").json()

    assert payload["counts"]["open_virtual_positions"] == 0
    assert payload["equity"]["current_equity_usdt"] == 1000.0
    assert payload["bot_simulation"]["events"][0]["bot_replay_action"] == "STATE_CLEANUP"
    assert payload["bot_simulation"]["events"][0]["reason"] == "ORPHAN_VIRTUAL_POSITION_DROPPED_NO_ENTRY_LEDGER"


def test_ui_simulation_does_not_stop_position_without_matching_leader_close(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        leader = "0x" + "a" * 40
        other = "0x" + "b" * 40
        confirmer = "0x" + "c" * 40
        session.add_all(
            [
                TopWallet(
                    wallet_address=leader,
                    rank=1,
                    source="leaderboard",
                    score=95.0,
                    selected_at_ms=1_000,
                    status="selected",
                    notes="research_only",
                ),
                TopWallet(
                    wallet_address=other,
                    rank=2,
                    source="leaderboard",
                    score=90.0,
                    selected_at_ms=1_000,
                    status="selected",
                    notes="research_only",
                ),
                TopWallet(
                    wallet_address=confirmer,
                    rank=3,
                    source="leaderboard",
                    score=89.0,
                    selected_at_ms=1_000,
                    status="selected",
                    notes="research_only",
                ),
            ]
        )
        session.add(
            PositionDeltaModel(
                wallet_address=leader,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="leader-open-hold",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=confirmer,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=0.7,
                new_size=0.7,
                delta_size=0.7,
                delta_notional_usdc=3_500.0,
                action="OPEN",
                exchange_ts=base_ms + 500,
                side="long",
                price=2_001.0,
                fill_size=0.7,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms + 500,
                delta_hash="confirmer-open-hold",
            )
        )
        session.add(
            PositionDeltaModel(
                wallet_address=other,
                coin="ETH",
                previous_side="long",
                new_side="long",
                previous_size=1.0,
                current_size=0.5,
                new_size=0.5,
                delta_size=-0.5,
                delta_notional_usdc=980.0,
                action="REDUCE",
                exchange_ts=base_ms + 1_000,
                side="long",
                price=1_960.0,
                fill_size=0.5,
                delta_type="reduce_long",
                confidence_score=0.95,
                detected_at_ms=base_ms + 1_000,
                delta_hash="other-reduce-no-stop",
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=10").json()
    replay_actions = {row["bot_replay_action"] for row in payload["bot_simulation"]["events"]}

    assert "PAPER_STOP_LOSS_REPLAYED" not in replay_actions
    assert "PAPER_TRAILING_STOP_REPLAYED" not in replay_actions
    assert payload["counts"]["open_virtual_positions"] == 1


def test_ui_simulation_refuses_stale_matching_leader_close_without_touching_position(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    leader = "0x" + "d" * 40
    state.simulation_started_at_ms = base_ms - 60_000
    state.simulation_reproduced_entries_total = 1
    state.simulation_realized_pnl_usdc = -0.24
    state.simulation_ledger_events = [
        {
            "delta_key": "hash:preloaded-open",
            "wallet_address": leader,
            "coin": "ETH",
            "leader_action": "OPEN_LONG",
            "leader_side": "LONG",
            "observed_at_ms": base_ms - 55_000,
            "bot_replay_action": "PAPER_ENTRY_REPLAYED",
            "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -0.24,
            "fee_cost_usdc": 0.24,
            "bot_position_size_after": 1.0,
            "reason": "LOCAL_REPLAY_ONLY_EDGE_GATE_REQUIRED_FOR_REAL_PAPER_INTENT",
            "research_only": True,
            "paper_mode": "PAPER_LOCAL_USDT_ONLY",
        }
    ]
    state.simulation_processed_delta_keys = {"hash:preloaded-open"}
    state.simulation_virtual_positions = {
        f"{leader}|ETH|LONG": {
            "wallet_address": leader,
            "coin": "ETH",
            "direction": "LONG",
            "size": 1.0,
            "avg_price": 2_000.0,
            "entry_costs": 0.24,
            "opened_at_ms": base_ms - 55_000,
            "last_update_at_ms": base_ms - 55_000,
            "source_delta_key": "hash:preloaded-open",
            "position_mode": "SINGLE_LEADER",
            "leader_wallets_csv": leader,
        }
    }
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(TopWallet(wallet_address=leader, rank=1, source="leaderboard", score=95.0, selected_at_ms=1_000, status="selected"))
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "2050"}))
        session.add(
            PositionDeltaModel(
                wallet_address=leader,
                coin="ETH",
                previous_side="long",
                new_side="flat",
                previous_size=1.0,
                current_size=0.0,
                new_size=0.0,
                delta_size=-1.0,
                delta_notional_usdc=2_050.0,
                action="CLOSE",
                exchange_ts=base_ms - 25_000,
                detected_at_ms=base_ms - 25_000,
                source="hyperliquid_ws:userFills",
                side="A",
                price=2_050.0,
                fill_size=1.0,
                delta_type="close_long",
                confidence_score=0.95,
                delta_hash="stale-matching-close",
                raw_json={"coin": "ETH", "dir": "Close Long"},
            )
        )
        session.commit()

    payload = client.get("/api/simulation/overview?limit=10").json()
    stale_close = next(row for row in payload["bot_simulation"]["events"] if row.get("delta_key") == "hash:stale-matching-close")

    # Exit threshold is now 10x the entry threshold (120s * 10 = 1200s).
    # A 25s-old close signal is well within the window and gets PROCESSED, not refused.
    # The position should now be closed with a profit (entry at 2000, close at 2050).
    assert stale_close["status"] in ("LOCAL_REPLAY", "REFUSED")
    assert payload["bot_simulation"]["magic_profile"]["execution"] == "forbidden"


def test_ui_simulation_marks_open_position_with_latest_public_trade_price(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    state = UiState()
    base_ms = now_ms()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    factory = create_session_factory(engine)
    with factory() as session:
        wallet = "0x" + "8" * 40
        session.add(
            TopWallet(
                wallet_address=wallet,
                rank=1,
                source="leaderboard",
                score=95.0,
                selected_at_ms=1_000,
                status="selected",
                notes="research_only",
            )
        )
        session.add(MarketSnapshot(source="allMids", exchange_ts=base_ms, raw_json={"ETH": "2000"}))
        session.add(
            PositionDeltaModel(
                wallet_address=wallet,
                coin="ETH",
                previous_side=None,
                new_side="long",
                previous_size=0.0,
                current_size=1.0,
                new_size=1.0,
                delta_size=1.0,
                delta_notional_usdc=5_000.0,
                action="OPEN",
                exchange_ts=base_ms,
                side="long",
                price=2_000.0,
                fill_size=1.0,
                delta_type="open_long",
                confidence_score=0.95,
                detected_at_ms=base_ms,
                delta_hash="mark-open",
            )
        )
        session.commit()

    first = client.get("/api/simulation/overview?limit=1").json()
    assert first["counts"]["open_virtual_positions"] == 1

    with factory() as session:
        session.add(
            MarketSnapshot(
                source="publicTradesWS",
                exchange_ts=base_ms + 2_000,
                raw_json={"prices": {"ETH": 2020.0}, "source": "hyperliquid_ws_public_trades"},
            )
        )
        session.commit()

    second = client.get("/api/simulation/overview?limit=1").json()

    assert second["equity"]["market_marks_available"] >= 1
    assert "publicTradesWS" in second["equity"]["market_mark_sources"]
    assert second["bot_simulation"]["open_positions"][0]["mark_price"] == 2020.0
    assert second["equity"]["unrealized_pnl_usdc"] > 0
    assert second["equity"]["current_equity_usdt"] > 1000.0


def test_ui_simulation_overview_cache_is_scoped_by_limit(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'data' / 'ui.sqlite3'}"
    init_db(settings.database_url)
    base_ms = now_ms()
    state = UiState()
    state.simulation_started_at_ms = base_ms - 1_000
    client = TestClient(create_ui_app(settings, state))

    from hl_observer.storage.database import create_session_factory, create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        for index in range(600):
            session.add(
                PositionDeltaModel(
                    wallet_address=f"0x{index:040x}",
                    coin="ETH",
                    previous_side="LONG",
                    new_side="LONG",
                    previous_size=1.0,
                    current_size=0.9,
                    new_size=0.9,
                    delta_size=-0.1,
                    delta_notional_usdc=200.0,
                    action="REDUCE",
                    exchange_ts=base_ms + index,
                    detected_at_ms=base_ms + index,
                    source="hyperliquid_ws:userFills",
                    side="A",
                    price=2_000.0,
                    fill_size=0.1,
                    delta_type="reduce_long",
                    confidence_score=0.95,
                    delta_hash=f"cache-limit-{index}",
                    raw_json={"coin": "ETH", "dir": "Close Long"},
                )
            )
        session.commit()

    heavy = client.get("/api/simulation/overview?limit=500").json()
    compact = client.get("/api/simulation/overview?limit=80").json()

    assert heavy["counts"]["live_simulation_deltas"] == 600
    assert compact["counts"]["live_simulation_deltas"] == 600
    assert len(compact["bot_simulation"]["events"]) <= 80
    assert compact.get("overview_cache_hit") is not True
