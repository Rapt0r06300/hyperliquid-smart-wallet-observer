"""Contrat du logger ultra-détaillé: structuré, capté (anti-bloat), best-effort."""

from __future__ import annotations

from hl_observer.runtime import detailed_logger as dl


def test_trade_and_decision_logged_structured(tmp_path):
    dl.log_trade("CLOSE", "HYPE", "LONG", net_pnl_usdc=1.23, notional_usdt=42, fee_usdc=0.05,
                 reason="TAKE_PROFIT", runtime_data_dir=tmp_path)
    dl.log_decision("SOL", "SHORT", "PAPER_TRADE", edge_net_bps=38.2, strategy="FUNDING_ARB",
                    runtime_data_dir=tmp_path)
    t = dl.read("trade", runtime_data_dir=tmp_path)
    d = dl.read("decision", runtime_data_dir=tmp_path)
    assert t[-1]["coin"] == "HYPE" and t[-1]["net_pnl_usdc"] == 1.23 and t[-1]["cat"] == "TRADE"
    assert d[-1]["decision"] == "PAPER_TRADE" and d[-1]["edge_net_bps"] == 38.2


def test_refusal_is_replay_ready(tmp_path):
    dl.log_refusal("BTC", "EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS", edge_net_bps=6.0, side="LONG",
                   runtime_data_dir=tmp_path)
    r = dl.read("refusal", runtime_data_dir=tmp_path)
    assert r[-1]["reason"].startswith("EXPECTED_NET_EDGE") and r[-1]["coin"] == "BTC"


def test_error_captures_type_and_traceback(tmp_path):
    try:
        1 / 0
    except ZeroDivisionError as e:
        dl.log_error("poll_loop", e, poll=42, runtime_data_dir=tmp_path)
    errs = dl.read("error", runtime_data_dir=tmp_path)
    assert errs[-1]["error_type"] == "ZeroDivisionError" and "traceback" in errs[-1]
    assert errs[-1]["poll"] == 42 and errs[-1]["sev"] == "ERROR"


def test_capping_prevents_bloat(tmp_path, monkeypatch):
    # force un petit cap et écrit beaucoup -> le fichier reste borné
    monkeypatch.setattr(dl, "_MAX_BYTES", 2000)
    monkeypatch.setattr(dl, "_MAX_LINES", 20)
    for i in range(400):
        dl.log("SCAN", "poll %d" % i, i=i, runtime_data_dir=tmp_path)
    rows = dl.read("scan", max=1000, runtime_data_dir=tmp_path)
    assert len(rows) <= 25            # capé, ne grossit pas indéfiniment (anti-bloat)
    assert rows[-1]["i"] == 399       # garde bien les DERNIERS


def test_never_raises_on_bad_input(tmp_path):
    # objets non sérialisables -> convertis en str, jamais d'exception
    dl.log("SYSTEM", "obj", weird=object(), runtime_data_dir=tmp_path)
    dl.log_error("x", "not an exception", runtime_data_dir=tmp_path)
    assert dl.read("system", runtime_data_dir=tmp_path)[-1]["cat"] == "SYSTEM"


def test_summary_counts_all_categories(tmp_path):
    dl.log_trade("OPEN", "ETH", "LONG", runtime_data_dir=tmp_path)
    dl.log_error("w", ValueError("x"), runtime_data_dir=tmp_path)
    s = dl.summary(runtime_data_dir=tmp_path)
    assert s["trade"]["count"] >= 1 and s["error"]["count"] >= 1 and "last" in s["trade"]
