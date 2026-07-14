import json
from pathlib import Path

from hl_observer.strategies import PaperStrategyRegistry
from hl_observer.strategies.external_github_bridge import (
    build_external_github_bridge_payload,
    discover_external_repo_capabilities,
    external_strategy_definitions,
    register_external_github_profiles,
    requested_external_repos,
)
from hl_observer.strategies.strategy_catalog import strategy_catalog


FAILED_IDS = {
    "06_composio_polymarket_kalshi_arbitrage_bot",
    "18_neron888_polymarket_copy_trading_bot",
    "19_terauss_polymarket_copy_trading_bot",
}


def _write_manifest(project_root: Path) -> None:
    repo_root = project_root / "runtime" / "research" / "github_repos_v24"
    repo_root.mkdir(parents=True)
    rows = []
    for index, spec in enumerate(requested_external_repos(), start=1):
        target = repo_root / spec.local_id
        failed = spec.local_id in FAILED_IDS
        if not failed:
            target.mkdir()
        rows.append(
            {
                "id": spec.local_id,
                "url": spec.url,
                "target": str(target),
                "status": "FAILED" if failed else "ALREADY_PRESENT",
                "message": "Repository not found" if failed else "",
                "branch": "main" if not failed else None,
                "commit": f"abc{index:03d}" if not failed else None,
                "file_count": 10 if not failed else 0,
                "size_bytes": 1000 if not failed else 0,
            }
        )
    (repo_root / "EXTERNAL_REPOS_MANIFEST.json").write_text(json.dumps(rows), encoding="utf-8")


def test_external_bridge_discovers_installed_and_unavailable_repos(tmp_path):
    _write_manifest(tmp_path)

    caps = discover_external_repo_capabilities(tmp_path)

    assert len(caps) == len(requested_external_repos())
    assert sum(cap.installed for cap in caps) == len(requested_external_repos()) - len(FAILED_IDS)
    assert {cap.local_id for cap in caps if not cap.installed} == FAILED_IDS
    assert caps[0].local_id == "17_rezzecup_whale_wallet_mirror_copy_trader"
    assert all(cap.paper_only is True for cap in caps)
    assert all(cap.direct_execution is False for cap in caps)


def test_external_bridge_registers_only_installed_paper_profiles(tmp_path):
    _write_manifest(tmp_path)
    registry = PaperStrategyRegistry()

    count = register_external_github_profiles(registry, project_root=tmp_path)
    definitions = external_strategy_definitions(tmp_path)

    assert count == len(requested_external_repos()) - len(FAILED_IDS)
    assert all(definition.read_only is True for definition in definitions)
    assert all(definition.params["paper_only"] == "True" for definition in definitions)
    assert all(definition.params["external_action"] == "False" for definition in definitions)
    assert registry.is_registered("ext_rezzecup_whale_mirror_primary")
    assert registry.is_registered("ext_jack_hl_arbitrage_spread")
    assert registry.is_registered("ext_hummingbot_market_making_framework")
    assert not registry.is_registered("ext_terauss_hot_path_pending")


def test_strategy_catalog_prioritizes_external_before_internal():
    catalog = strategy_catalog()

    assert catalog[0] == "ext_rezzecup_whale_mirror_primary"
    assert "wallet_mirror_copy_follow" in catalog
    assert catalog.index("ext_rezzecup_whale_mirror_primary") < catalog.index("wallet_mirror_copy_follow")


def test_external_bridge_status_payload_is_paper_only(tmp_path):
    _write_manifest(tmp_path)

    payload = build_external_github_bridge_payload(tmp_path)

    # DOCTRINE SHADOW-ONLY (pivot ff7aeec, re-imposee a l'audit du 2026-07-11) : ce champ etait
    # "True" en dur -- une affirmation FAUSSE envoyee au statut, au dashboard et a l'audit.
    # Aucun repo externe ne bypasse le RiskEngine, le ledger, ni l'interne. Observation, pas priorite.
    assert payload["priority_over_internal"] is False
    assert payload["direct_external_execution"] is False
    assert payload["paper_only"] is True
    assert payload["read_only"] is True
    assert payload["installed_count"] == len(requested_external_repos()) - len(FAILED_IDS)
    assert payload["unavailable_count"] == len(FAILED_IDS)
    assert "ext_rezzecup_whale_mirror_primary" in payload["priority_strategy_catalog"]
    assert "ext_jack_hl_arbitrage_spread" in payload["priority_strategy_catalog"]
    assert "ext_hummingbot_market_making_framework" in payload["priority_strategy_catalog"]
    assert "ext_composio_cross_market_arb_pending" in payload["disabled_strategy_catalog"]
    assert "ext_terauss_hot_path_pending" in payload["disabled_strategy_catalog"]


def test_simulation_ui_renders_external_github_bridge_status():
    html = Path("src/hl_observer/ui/static/simulation_v2.html").read_text(encoding="utf-8")

    assert "external_github_bridge" in html
    assert "Moteurs GitHub" in html
    assert "GitHub branche" in html
    assert "Opportunites distillees" in html
    assert "priority_strategy_catalog" in html
