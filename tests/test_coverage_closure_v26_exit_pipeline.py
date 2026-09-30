from __future__ import annotations

from types import SimpleNamespace

from hl_observer.paper_trading import v26_exit_pipeline as pipeline
from hl_observer.paper_trading import auto_unstuck
from hl_observer.risk import graded_halt, kelly_leader_book, protections_v26
from hl_observer.runtime import replay_recorder
from hl_observer.signals import market_quality_score


def test_v26_exit_pipeline_records_marks_ingests_closes_and_runs_actions(monkeypatch, tmp_path) -> None:
    failures = []
    monkeypatch.setattr(pipeline, "_noter_echec", failures.append)
    monkeypatch.setenv("HYPERSMART_V26_RECORD_CANDIDATES", "true")
    monkeypatch.setenv("HYPERSMART_V26_RECORD_PATH", str(tmp_path / "replay"))
    appended = []
    monkeypatch.setattr(
        replay_recorder,
        "append_replay_lines",
        lambda base, name, rows, max_bytes, max_lines: appended.append((base, name, rows, max_bytes, max_lines)),
    )

    protection_book = SimpleNamespace(update_from_ledger_events=lambda events: len(events))
    kelly_book = SimpleNamespace(update_from_ledger_events=lambda events: len(events) + 10)
    monkeypatch.setattr(protections_v26, "DEFAULT_PROTECTIONS_BOOK", protection_book)
    monkeypatch.setattr(kelly_leader_book, "DEFAULT_KELLY_LEADER_BOOK", kelly_book)

    def close_record(event):
        if event.get("paper_action_type") != "CLOSE":
            return None
        return SimpleNamespace(coin=event["coin"], net_pnl_usd=float(event["pnl"]))

    monkeypatch.setattr(protections_v26, "close_record_from_ledger_event", close_record)
    observed = []
    monkeypatch.setattr(
        market_quality_score,
        "DEFAULT_MARKET_QUALITY_BOOK",
        SimpleNamespace(observe=lambda coin, market_pnl_usd, env: observed.append((coin, market_pnl_usd, env))),
    )

    halt_book = SimpleNamespace(
        update=lambda events, now_ms, env: "RED",
        effects=lambda env: SimpleNamespace(force_exit_all=True),
        mark_forced_exit_done=lambda: observed.append(("halt_done", 0, None)),
    )
    monkeypatch.setattr(graded_halt, "DEFAULT_GRADED_HALT", halt_book)
    monkeypatch.setattr(graded_halt, "flag_on", lambda env: True)
    monkeypatch.setattr(
        graded_halt,
        "force_exit_all_positions",
        lambda positions, ledger_events, mid_prices, **kwargs: ["forced-close"],
    )
    monkeypatch.setattr(
        auto_unstuck,
        "apply_auto_unstuck",
        lambda positions, ledger_events, mid_prices, **kwargs: ["unstuck"],
    )

    events = [
        {"old": True},
        {"paper_action_type": "CLOSE", "coin": "BTC", "pnl": 2.0},
        "not-a-dict",
        {"paper_action_type": "CLOSE", "coin": "BTC", "pnl": -0.5},
        {"paper_action_type": "OPEN", "coin": "ETH", "pnl": 9.0},
    ]
    env = {"unit": "1"}
    summary = pipeline.run_v26_exit_pipeline(
        {"BTC": {"size": 1}},
        events,
        {"btc": 100.0, "ETH": "bad", "SOL": 20},
        now_ms=2_000,
        cost_bps=8.0,
        ledger_len_before=1,
        env=env,
        paper_mode="PAPER_TEST",
    )

    assert summary["pipeline"] == "V26"
    assert summary["protections_ingested"] == 3
    assert summary["kelly_ingested"] == 13
    assert summary["graded_halt_state"] == "RED"
    assert summary["actions"] == ["forced-close", "unstuck"]
    assert appended and appended[0][1] == "marks.jsonl"
    assert appended[0][2] == [
        {"ts": 2.0, "coin": "BTC", "mid": 100.0},
        {"ts": 2.0, "coin": "SOL", "mid": 20.0},
    ]
    assert ("BTC", 1.5, env) in observed
    assert failures == []


def test_v26_exit_pipeline_halt_off_empty_events_and_no_positions(monkeypatch) -> None:
    monkeypatch.delenv("HYPERSMART_V26_RECORD_CANDIDATES", raising=False)
    monkeypatch.setattr(graded_halt, "flag_on", lambda env: False)
    calls = []
    monkeypatch.setattr(auto_unstuck, "apply_auto_unstuck", lambda *args, **kwargs: calls.append(kwargs) or [])
    summary = pipeline.run_v26_exit_pipeline({}, [], None, now_ms=0, ledger_len_before=-5)
    assert summary == {"pipeline": "V26", "actions": []}
    assert len(calls) == 1


def test_v26_exit_pipeline_halt_on_without_force_exit(monkeypatch) -> None:
    monkeypatch.setattr(graded_halt, "flag_on", lambda env: True)
    monkeypatch.setattr(
        graded_halt,
        "DEFAULT_GRADED_HALT",
        SimpleNamespace(
            update=lambda events, now_ms, env: "YELLOW",
            effects=lambda env: SimpleNamespace(force_exit_all=False),
        ),
    )
    forced = []
    monkeypatch.setattr(graded_halt, "force_exit_all_positions", lambda *args, **kwargs: forced.append(True) or [])
    monkeypatch.setattr(auto_unstuck, "apply_auto_unstuck", lambda *args, **kwargs: [])
    summary = pipeline.run_v26_exit_pipeline({"BTC": {}}, [], {}, now_ms=1)
    assert summary["graded_halt_state"] == "YELLOW"
    assert forced == []


def test_v26_exit_pipeline_all_fail_safe_handlers(monkeypatch, tmp_path) -> None:
    failures = []
    monkeypatch.setattr(pipeline, "_noter_echec", failures.append)

    monkeypatch.setenv("HYPERSMART_V26_RECORD_CANDIDATES", "1")
    monkeypatch.setenv("HYPERSMART_V26_RECORD_PATH", str(tmp_path / "replay"))
    monkeypatch.setattr(
        replay_recorder,
        "append_replay_lines",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("recorder boom")),
    )

    monkeypatch.setattr(
        protections_v26,
        "DEFAULT_PROTECTIONS_BOOK",
        SimpleNamespace(update_from_ledger_events=lambda events: (_ for _ in ()).throw(RuntimeError("ingest boom"))),
    )

    monkeypatch.setattr(graded_halt, "flag_on", lambda env: (_ for _ in ()).throw(RuntimeError("halt boom")))
    monkeypatch.setattr(
        auto_unstuck,
        "apply_auto_unstuck",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unstuck boom")),
    )

    summary = pipeline.run_v26_exit_pipeline(
        {"BTC": {}},
        [{"paper_action_type": "CLOSE", "coin": "BTC"}],
        {"BTC": 1.0},
        now_ms=1,
    )
    assert summary["actions"] == []
    assert any(value.endswith(":57") for value in failures)
    assert any(value.endswith(":83") for value in failures)
    assert any(value.endswith(":102") for value in failures)
    assert any(value.endswith(":114") for value in failures)


def test_v26_exit_pipeline_market_quality_nested_failure_is_isolated(monkeypatch) -> None:
    failures = []
    monkeypatch.setattr(pipeline, "_noter_echec", failures.append)
    monkeypatch.delenv("HYPERSMART_V26_RECORD_CANDIDATES", raising=False)
    monkeypatch.setattr(
        protections_v26,
        "DEFAULT_PROTECTIONS_BOOK",
        SimpleNamespace(update_from_ledger_events=lambda events: 1),
    )
    monkeypatch.setattr(
        kelly_leader_book,
        "DEFAULT_KELLY_LEADER_BOOK",
        SimpleNamespace(update_from_ledger_events=lambda events: 1),
    )
    monkeypatch.setattr(
        protections_v26,
        "close_record_from_ledger_event",
        lambda event: (_ for _ in ()).throw(RuntimeError("quality boom")),
    )
    monkeypatch.setattr(graded_halt, "flag_on", lambda env: False)
    monkeypatch.setattr(auto_unstuck, "apply_auto_unstuck", lambda *args, **kwargs: [])

    summary = pipeline.run_v26_exit_pipeline(
        {},
        [{"paper_action_type": "CLOSE", "coin": "BTC"}],
        {},
        now_ms=1,
    )
    assert summary["protections_ingested"] == 1
    assert summary["kelly_ingested"] == 1
    assert any(value.endswith(":81") for value in failures)
