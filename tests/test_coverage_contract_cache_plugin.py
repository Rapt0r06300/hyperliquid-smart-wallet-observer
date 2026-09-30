from __future__ import annotations

import signal
from types import SimpleNamespace

import pytest

from tests import coverage_contract_cache_plugin as plugin


def _frame(filename: str):
    return SimpleNamespace(f_code=SimpleNamespace(co_filename=filename))


def _fake_signal_runtime(monkeypatch, *, previous_remaining=0.0, previous_handler=signal.SIG_DFL):
    state: dict[str, object] = {"handler": None, "alarms": [], "delegated": 0}

    def fake_getsignal(_signum):
        return previous_handler

    def fake_getitimer(_which):
        return float(previous_remaining), 0.0

    def fake_signal(_signum, handler):
        state["handler"] = handler
        return previous_handler

    def fake_setitimer(_which, seconds, interval=0.0):
        state["alarms"].append((float(seconds), float(interval)))
        return 0.0, 0.0

    monkeypatch.setattr(plugin.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(plugin.signal, "getitimer", fake_getitimer)
    monkeypatch.setattr(plugin.signal, "signal", fake_signal)
    monkeypatch.setattr(plugin.signal, "setitimer", fake_setitimer)
    return state


def test_timeout_frame_accepts_repo_code_but_refuses_foreign_and_plugin_code() -> None:
    assert plugin._controlled_timeout_frame(
        _frame(plugin._REPO_ROOT + "/src/hl_observer/example.py")
    )
    assert plugin._controlled_timeout_frame(
        _frame(plugin._REPO_ROOT + "/tests/test_example.py")
    )
    assert not plugin._controlled_timeout_frame(_frame("/usr/lib/python3.11/weakref.py"))
    assert not plugin._controlled_timeout_frame(_frame("/venv/site-packages/sqlalchemy/event/registry.py"))
    assert not plugin._controlled_timeout_frame(_frame(plugin._PLUGIN_FILE))


def test_bounded_invoke_raises_immediately_in_controlled_repo_frame(monkeypatch) -> None:
    state = _fake_signal_runtime(monkeypatch)

    def target():
        handler = state["handler"]
        assert callable(handler)
        handler(signal.SIGALRM, _frame(plugin._REPO_ROOT + "/src/hl_observer/example.py"))

    wrapped = plugin._bounded_invoke(target, seconds=0.5)
    with pytest.raises(plugin._CoverageContractCallTimeout, match="exceeded 0.500s"):
        wrapped()

    assert state["alarms"][0] == (0.5, 0.0)
    assert state["alarms"][-1] == (0.0, 0.0)


def test_bounded_invoke_defers_foreign_callback_then_raises_on_return(monkeypatch) -> None:
    state = _fake_signal_runtime(monkeypatch)

    def target():
        handler = state["handler"]
        assert callable(handler)
        handler(signal.SIGALRM, _frame("/venv/site-packages/sqlalchemy/event/registry.py"))
        return "foreign-callback-finished"

    wrapped = plugin._bounded_invoke(target, seconds=0.5)
    with pytest.raises(plugin._CoverageContractCallTimeout, match="exceeded 0.500s"):
        wrapped()

    assert (plugin._UNSAFE_FRAME_RETRY_SECONDS, 0.0) in state["alarms"]
    assert state["alarms"][-1] == (0.0, 0.0)


def test_bounded_invoke_preserves_earlier_outer_timeout(monkeypatch) -> None:
    delegated: list[tuple[object, object]] = []

    def previous_handler(signum, frame):
        delegated.append((signum, frame))
        return None

    state = _fake_signal_runtime(
        monkeypatch,
        previous_remaining=0.1,
        previous_handler=previous_handler,
    )

    def target():
        handler = state["handler"]
        assert callable(handler)
        current = _frame(plugin._REPO_ROOT + "/src/hl_observer/example.py")
        handler(signal.SIGALRM, current)
        return "ok"

    wrapped = plugin._bounded_invoke(target, seconds=0.5)
    assert wrapped() == "ok"
    assert delegated
    assert state["alarms"][0] == (0.1, 0.0)
