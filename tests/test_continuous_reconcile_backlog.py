"""Fail-closed inventory and Git error classification for continuous Release waves."""
import pytest
from tools.continuous_reconcile_backlog import pending, PACK


def test_pending_respects_release_aliases_status_and_quarantine() -> None:
    index = {
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "run_manifest_release_tags_by_release": {"data-v2-physical": "data-v2-alias"},
        "shards": [
            {"release_tag": "data-v2-physical"},
            {"release_tag": "copy-vault-v2-done"},
        ],
    }
    rows = (
        "data-v2-next\ttrue\n"
        "data-v2-alias\ttrue\n"
        "copy-vault-v2-done\ttrue\n"
        "archive-v2-hold\ttrue\n"
        "data-v2-missing\tfalse\n"
        "data-v2-next\ttrue\n"
    )
    assert pending(rows, index, {"archive-v2-hold"}) == ["data-v2-next"]


def test_malformed_inventory_rejected() -> None:
    with pytest.raises(ValueError):
        pending("missing-tab", {"shards": []}, set())
    with pytest.raises(ValueError):
        pending("../attack\ttrue", {"shards": []}, set())


def test_git_pack_failure_not_confused_with_concurrent_main_update() -> None:
    assert PACK.search("remote unpack failed: index-pack failed")
    assert PACK.search("tree too large")
    assert not PACK.search("! [rejected] HEAD -> main (fetch first)")
