from hl_observer.edge.edge_net_v12 import EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.scoring.wallet_score_v2 import WalletPerformanceSample, score_wallet_v2
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore


def test_v12_sqlite_store_migrations_are_idempotent(tmp_path):
    path = tmp_path / "v12.sqlite3"
    store = V12SQLiteStore(path)
    store.initialize()
    store.initialize()

    assert store.count("v12_wallet_scores") == 0
    assert store.latest("v12_signal_clusters") == []


def test_v12_sqlite_store_upserts_wallet_score_and_edge(tmp_path):
    path = tmp_path / "v12.sqlite3"
    store = V12SQLiteStore(path)
    store.initialize()
    wallet = "0x" + "a" * 40
    samples = [
        WalletPerformanceSample(wallet=wallet, coin="BTC", closed_pnl_usdc=10 + i, timestamp_ms=1_700_000_000_000 + i * 86_400_000)
        for i in range(14)
    ]
    score = score_wallet_v2(wallet, samples, now_ms=1_700_000_000_000 + 14 * 86_400_000)
    store.upsert_wallet_score(score, updated_at_ms=1_700_000_000_000)
    store.upsert_wallet_score(score, updated_at_ms=1_700_000_000_001)

    edge = estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=100,
            current_mid=100,
            leader_expected_edge_bps=80,
            spread_bps=2,
            slippage_bps=2,
            fee_bps=4,
            funding_estimate_bps=0,
        )
    )
    store.upsert_edge_estimate("edge:1", edge, created_at_ms=1_700_000_000_002)

    assert store.count("v12_wallet_scores") == 1
    assert store.count("v12_edge_estimates") == 1
    assert store.latest("v12_wallet_scores")[0]["wallet"] == wallet
    assert "payload_json" in store.latest("v12_edge_estimates")[0]


def test_v12_sqlite_store_rejects_unknown_table(tmp_path):
    store = V12SQLiteStore(tmp_path / "v12.sqlite3")
    store.initialize()
    try:
        store.count("paper_orders")
    except ValueError as exc:
        assert "unsupported table" in str(exc)
    else:
        raise AssertionError("unknown table should be rejected")
