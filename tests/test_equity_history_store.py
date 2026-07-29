"""Contrat de l'historique d'equity persisté (survit à la fermeture du dashboard)."""

from __future__ import annotations

from hl_observer.runtime.equity_history_store import append_equity_point, read_equity_points


def test_append_and_read_roundtrip(tmp_path):
    for i in range(5):
        append_equity_point(timestamp_ms=1000 + i, equity_usdt=1000 + i * 0.5, pnl_usdc=i * 0.5, runtime_data_dir=tmp_path)
    pts = read_equity_points(runtime_data_dir=tmp_path)
    assert len(pts) == 5
    assert pts[0]["t"] == 1000 and pts[-1]["equity"] == 1002.0     # chronologique, valeurs justes


def test_read_caps_to_max(tmp_path):
    for i in range(50):
        append_equity_point(timestamp_ms=i, equity_usdt=1000 + i, runtime_data_dir=tmp_path)
    pts = read_equity_points(max=10, runtime_data_dir=tmp_path)
    assert len(pts) == 10 and pts[-1]["t"] == 49                    # derniers points


def test_missing_file_is_empty_honest(tmp_path):
    assert read_equity_points(runtime_data_dir=tmp_path) == []      # rien inventé


def test_append_never_raises(tmp_path):
    append_equity_point(timestamp_ms="bad", equity_usdt=None, runtime_data_dir=tmp_path)  # ne doit pas lever
    # valeurs invalides ignorées proprement, pas de crash
    assert isinstance(read_equity_points(runtime_data_dir=tmp_path), list)


def test_missing_baseline_preserves_unmeasurable_pnl(tmp_path):
    append_equity_point(
        timestamp_ms=1_000,
        equity_usdt=987.5,
        pnl_usdc=None,
        starting_equity_usdt=None,
        session_id="paper:no-baseline",
        runtime_data_dir=tmp_path,
    )

    point = read_equity_points(runtime_data_dir=tmp_path)[0]

    assert point["equity"] == 987.5
    assert point["pnl"] is None
    assert point["starting_equity_usdt"] is None
    assert point["accounting_status"] == "BASELINE_UNMEASURABLE"
