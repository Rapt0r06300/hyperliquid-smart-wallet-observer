from hl_observer.config.local_rule_store import LocalRuleStore


def test_local_rule_store_write_failure_is_fail_closed(tmp_path, monkeypatch):
    failures = []
    monkeypatch.setattr("hl_observer.config.local_rule_store._noter_echec", failures.append)

    def fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", fail_write)
    store = LocalRuleStore(str(tmp_path / "rules.json"))
    store.set("min_edge_bps", 12)

    assert store.get("min_edge_bps") == 12
    assert failures == ["hl_observer/config/local_rule_store.py:38"]
