from __future__ import annotations

from types import SimpleNamespace

import hl_observer.collection.run_collect_all as mod


class FakeSession:
    def __init__(self):
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        self.commits += 1


class FakeReport:
    def __init__(self, ok: bool, outputs):
        self.ok = ok
        self.outputs = outputs

    def summary(self):
        return " | ".join(self.outputs)


def _settings():
    return SimpleNamespace(
        database_url="sqlite:///fake.db",
        wallet_scanner=SimpleNamespace(scan_max_wallets_per_run=12, scan_batch_size=3),
    )


def _install_fakes(monkeypatch, *, report_ok=True):
    calls = []
    sessions = []
    monkeypatch.setattr(mod, "load_settings", _settings)
    monkeypatch.setattr(mod, "create_sqlite_engine", lambda url: calls.append(("engine", url)) or "engine")

    def factory(engine):
        assert engine == "engine"
        def make_session():
            session = FakeSession()
            sessions.append(session)
            return session
        return make_session

    monkeypatch.setattr(mod, "create_session_factory", factory)
    monkeypatch.setattr(
        mod,
        "MarketDiscoveryPlan",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    async def discover_markets(plan, settings):
        calls.append(("markets", plan.max_coins, plan.sources, plan.include_altcoins, plan.store, plan.dry_run))
        return SimpleNamespace(coins_discovered=77)

    monkeypatch.setattr(mod, "run_discover_markets", discover_markets)
    monkeypatch.setattr(
        mod,
        "build_wallet_discovery_plan",
        lambda settings, **kwargs: calls.append(("wallet_plan", kwargs)) or SimpleNamespace(kind="wallet-plan"),
    )
    monkeypatch.setattr(
        mod,
        "run_wallet_discovery",
        lambda plan, settings: calls.append(("wallets", plan.kind)) or SimpleNamespace(candidates_found=33),
    )
    monkeypatch.setattr(
        mod,
        "bootstrap_top_wallets",
        lambda settings, **kwargs: calls.append(("bootstrap", kwargs["target"], kwargs["source"], kwargs["store"], kwargs["dry_run"])),
    )
    monkeypatch.setattr(
        mod,
        "scan_wallet_queue",
        lambda session, **kwargs: calls.append(("scan", kwargs["max_wallets"], kwargs["batch_size"], kwargs["dry_run"])),
    )

    def run_steps(steps):
        outputs = []
        for name, fn in steps:
            outputs.append(f"{name}:{fn()}")
        return FakeReport(report_ok, outputs)

    monkeypatch.setattr(mod, "run_steps", run_steps)
    return calls, sessions


def test_collect_all_main_runs_every_read_only_step(monkeypatch, capsys) -> None:
    calls, sessions = _install_fakes(monkeypatch, report_ok=True)
    rc = mod.main(["--max-coins", "123", "--target", "456"])
    assert rc == 0
    assert ("markets", 123, ["meta", "all-mids"], True, True, False) in calls
    assert any(call[0] == "wallet_plan" for call in calls)
    assert ("wallets", "wallet-plan") in calls
    assert ("bootstrap", 456, "all", True, False) in calls
    assert ("scan", 12, 3, False) in calls
    assert len(sessions) == 2
    assert [session.commits for session in sessions] == [1, 1]
    out = capsys.readouterr().out
    assert "discover_markets:coins=77" in out
    assert "discover_wallets:candidates=33" in out
    assert "bootstrap_top_wallets:top_wallets target<= 456" in out
    assert "scan_wallet_queue:queue scored" in out


def test_collect_all_main_returns_red_when_step_report_is_not_ok(monkeypatch) -> None:
    _install_fakes(monkeypatch, report_ok=False)
    assert mod.main([]) == 1


def test_discover_markets_summary_falls_back_to_stored(monkeypatch, capsys) -> None:
    calls, sessions = _install_fakes(monkeypatch, report_ok=True)

    async def discover_markets(plan, settings):
        return SimpleNamespace(stored=9)

    monkeypatch.setattr(mod, "run_discover_markets", discover_markets)
    assert mod.main([]) == 0
    assert "discover_markets:coins=9" in capsys.readouterr().out
