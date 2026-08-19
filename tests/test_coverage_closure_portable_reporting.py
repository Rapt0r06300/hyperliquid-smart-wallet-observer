from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

import hl_observer.ops.portable_audit_guard as audit_guard
from hl_observer.core.logging_config import JsonLineFormatter, configure_structured_logging
from hl_observer.research.research_toolkit import summarize_paper_outcomes
from hl_observer.runtime.research_path import summarize_no_trade_reasons
from hl_observer.wallets.top_wallet_export import export_top_wallets


def test_research_toolkit_empty_and_aggregated_outcomes() -> None:
    empty = summarize_paper_outcomes([])
    assert empty["rows"] == 0
    assert empty["trades_with_pnl"] == 0
    assert empty["winrate"] is None
    assert empty["research_only"] is True

    result = summarize_paper_outcomes(
        [
            {"pnl_usdc": 2.0, "coin": "btc", "leader_wallet": "0xA", "reason_codes": ["R1"]},
            {"pnl": -1.0, "coin": "ETH", "wallet": "0xB", "reason_codes": ["R1", "R2"]},
            {"coin": "BTC", "reason_codes": None},
        ]
    )
    assert result["rows"] == 3
    assert result["trades_with_pnl"] == 2
    assert result["net_pnl_usdc"] == 1.0
    assert result["winrate"] == 0.5
    assert result["pnl_by_coin"] == {"ETH": -1.0, "BTC": 2.0}
    assert result["reason_counts"] == {"R1": 2, "R2": 1}
    assert result["pnl_by_wallet"]["0xa"] == 2.0
    assert result["pnl_by_wallet"]["0xb"] == -1.0
    assert result["pnl_by_wallet"]["unknown"] == 0.0


def test_research_path_normalizes_counts_orders_and_severity() -> None:
    findings = summarize_no_trade_reasons([" stale ", "STALE", "cost", "STALE", "", "  ", "risk"])
    assert [row.code for row in findings] == ["STALE", "COST", "RISK"]
    assert findings[0].severity == "HIGH"
    assert findings[0].detail == "3 occurrence(s) in research path"
    assert findings[1].severity == "MEDIUM"
    assert summarize_no_trade_reasons([]) == ()


def test_json_logging_formatter_plain_json_context_and_exception() -> None:
    formatter = JsonLineFormatter()
    record = logging.LogRecord("unit", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.component = "paper"
    record.event = "trade"
    record.wallet = "0xA"
    record.coin = "BTC"
    record.decision_id = "d1"
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "unit"
    assert payload["message"] == "hello world"
    assert payload["component"] == "paper"
    assert payload["event"] == "trade"
    assert payload["wallet"] == "0xA"
    assert payload["coin"] == "BTC"
    assert payload["decision_id"] == "d1"
    assert "ts" in payload

    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()
    record = logging.LogRecord("unit", logging.ERROR, __file__, 1, "failed", (), exc_info)
    payload = json.loads(formatter.format(record))
    assert "ValueError: boom" in payload["exc_info"]


def test_configure_structured_logging_both_modes_restores_root() -> None:
    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    try:
        configure_structured_logging("DEBUG", json_lines=True)
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonLineFormatter)

        configure_structured_logging("NOT_A_LEVEL", json_lines=False)
        assert root.level == logging.INFO
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, logging.Formatter)
        assert not isinstance(root.handlers[0].formatter, JsonLineFormatter)
    finally:
        root.handlers[:] = old_handlers
        root.setLevel(old_level)


def test_portable_guard_loopback_write_detection_and_inside(tmp_path) -> None:
    root = tmp_path.resolve()
    assert audit_guard._loopback_bind((object(), ("127.0.0.1", 0)))
    assert audit_guard._loopback_bind((object(), ("::1", 0)))
    assert audit_guard._loopback_bind((object(), ("localhost", 0)))
    assert not audit_guard._loopback_bind((object(), ("0.0.0.0", 0)))
    assert not audit_guard._loopback_bind((object(), "bad"))

    assert audit_guard._inside(root / "a.txt", root)
    assert audit_guard._inside("relative.txt", Path.cwd().resolve())
    assert audit_guard._inside(None, root)
    assert audit_guard._inside(5, root)
    assert not audit_guard._inside(root.parent / "escape.txt", root)

    assert audit_guard._open_is_write(("x", "w", 0))
    assert audit_guard._open_is_write(("x", "a", 0))
    assert audit_guard._open_is_write(("x", "r+", 0))
    assert not audit_guard._open_is_write(("x", "r", 0))
    assert audit_guard._open_is_write(("x", "r", getattr(os, "O_WRONLY", 1)))


def test_portable_guard_record_and_install_validation(tmp_path, monkeypatch) -> None:
    log = tmp_path / "audit.jsonl"
    audit_guard._record(log, "event", ("secret", 123))
    payload = json.loads(log.read_text(encoding="utf-8").strip())
    assert payload["event"] == "event"
    assert payload["pid"] == os.getpid()
    assert payload["args"] == ["'secret'", "123"]

    monkeypatch.setattr(audit_guard, "_INSTALLED", False)
    with pytest.raises(ValueError, match="must live inside extraction"):
        audit_guard.install(tmp_path / "root", tmp_path / "outside.log")


def test_portable_guard_hook_denies_network_and_external_writes_without_global_hook(tmp_path, monkeypatch) -> None:
    root = tmp_path / "release"
    root.mkdir()
    log = root / "audit.jsonl"
    captured = {}
    monkeypatch.setattr(audit_guard, "_INSTALLED", False)
    monkeypatch.setattr(audit_guard.sys, "addaudithook", lambda hook: captured.setdefault("hook", hook))
    audit_guard.install(root, log)
    assert audit_guard._INSTALLED is True
    hook = captured["hook"]

    hook("socket.bind", (object(), ("127.0.0.1", 0)))
    with pytest.raises(PermissionError, match="denies network"):
        hook("socket.bind", (object(), ("0.0.0.0", 0)))
    with pytest.raises(PermissionError, match="denies network"):
        hook("socket.connect", (object(), ("example.com", 443)))

    inside = root / "inside.txt"
    hook("open", (str(inside), "w", 0))
    outside = tmp_path / "outside.txt"
    with pytest.raises(PermissionError, match="denies external write"):
        hook("open", (str(outside), "w", 0))
    with pytest.raises(PermissionError, match="denies external write"):
        hook("os.rename", (str(inside), str(outside)))
    hook("open", (str(outside), "r", 0))
    assert log.is_file()
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert any(row["event"] == "socket.bind" for row in lines)
    assert any(row["event"] == "socket.connect" for row in lines)
    assert any(row["event"] == "open" for row in lines)
    assert any(row["event"] == "os.rename" for row in lines)

    # Installing twice is intentionally a no-op.
    captured.clear()
    audit_guard.install(root, log)
    assert captured == {}


def test_portable_guard_environment_missing_and_present(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HYPERSMART_PORTABLE_AUDIT_ROOT", raising=False)
    monkeypatch.delenv("HYPERSMART_PORTABLE_AUDIT_LOG", raising=False)
    assert audit_guard.install_from_environment() is False

    called = {}
    monkeypatch.setenv("HYPERSMART_PORTABLE_AUDIT_ROOT", str(tmp_path))
    monkeypatch.setenv("HYPERSMART_PORTABLE_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(audit_guard, "install", lambda root, log: called.update(root=root, log=log))
    assert audit_guard.install_from_environment() is True
    assert called["root"] == str(tmp_path)
    assert called["log"] == str(tmp_path / "audit.jsonl")


class _FakeRow:
    def __init__(self, address: str, rank: int, score: float, status: str = "active") -> None:
        self.wallet_address = address
        self.rank = rank
        self.source = "unit"
        self.score = score
        self.status = status


class _FakeQuery:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.order_expression = None

    def order_by(self, expression):
        self.order_expression = expression
        return self

    def all(self):
        return self.rows


class _FakeDbSession:
    def __init__(self, rows) -> None:
        self.query_obj = _FakeQuery(rows)
        self.added = []

    def query(self, model):
        return self.query_obj

    def add(self, value):
        self.added.append(value)


def test_top_wallet_export_json_csv_and_db_audit_rows(tmp_path) -> None:
    session = _FakeDbSession([_FakeRow("0xA", 1, 9.5), _FakeRow("0xB", 2, 8.0, "watch")])
    paths = export_top_wallets(session, export_dir=tmp_path / "exports")
    assert set(paths) == {"json", "csv"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload == [
        {"rank": 1, "score": 9.5, "source": "unit", "status": "active", "wallet_address": "0xA"},
        {"rank": 2, "score": 8.0, "source": "unit", "status": "watch", "wallet_address": "0xB"},
    ]
    csv_text = paths["csv"].read_text(encoding="utf-8")
    assert "wallet_address,rank,source,score,status" in csv_text
    assert "0xA,1,unit,9.5,active" in csv_text
    assert len(session.added) == 2
    assert {row.format for row in session.added} == {"json", "csv"}
    assert all(row.rows_exported == 2 for row in session.added)
