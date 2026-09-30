"""V27 — cablage du firehose userFills multiplexe dans le runner persistant.
Prouve: OFF par defaut (aucun process), activable par env, plafond anti-ban dur.
Read-only / paper-only."""

from __future__ import annotations

from hl_observer.runtime.persistent_poll_runner import PersistentPollRunner, build_config


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_FILLS_MULTIPLEX", raising=False)
    cfg = build_config(["--root", "."])
    assert cfg.fills_multiplex is False
    runner = PersistentPollRunner(cfg)
    assert runner._spawn_fills_multiplex() is None       # OFF par defaut -> aucun sous-process


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("HYPERSMART_FILLS_MULTIPLEX", "1")
    monkeypatch.setenv("HYPERSMART_FILLS_MULTIPLEX_CONNECTIONS", "5")
    cfg = build_config(["--root", "."])
    assert cfg.fills_multiplex is True
    assert cfg.fills_multiplex_connections == 5


def test_connections_hard_capped(monkeypatch):
    monkeypatch.setenv("HYPERSMART_FILLS_MULTIPLEX", "yes")
    monkeypatch.setenv("HYPERSMART_FILLS_MULTIPLEX_CONNECTIONS", "999")
    cfg = build_config(["--root", "."])
    assert cfg.fills_multiplex_connections == 8          # plafond anti-ban dur (8*10 leaders)
