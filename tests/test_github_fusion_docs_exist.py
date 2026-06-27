"""Verify the GitHub-fusion documentation set exists and is non-trivial."""

from pathlib import Path

FUSION_DOCS = [
    "docs/research/HYPERSMART_GITHUB_FUSION_MASTER.md",
    "docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md",
    "docs/HYPERSMART_HYPERLIQUID_SCAN_STRATEGY_FUSION.md",
    "docs/HYPERSMART_COMMON_DATA_MODEL_FUSION.md",
    "docs/HYPERSMART_MARKET_SIGNAL_FEATURES_FUSION.md",
    "docs/HYPERSMART_WALLET_INTELLIGENCE_FUSION.md",
    "docs/HYPERSMART_RISK_ENGINE_FUSION.md",
    "docs/HYPERSMART_DASHBOARD_FUSION.md",
    "docs/HYPERSMART_BACKTEST_RUNTIME_PARITY_FUSION.md",
    "docs/HYPERSMART_AGENT_SAFE_READONLY_TOOLS_FUSION.md",
    "docs/HYPERSMART_NO_FAKE_DATA_NO_HYPE_NO_EXECUTION_POLICY.md",
    "docs/HYPERSMART_LICENSE_SAFETY_POLICY.md",
]


def test_all_fusion_docs_exist_and_nontrivial():
    missing = [d for d in FUSION_DOCS if not Path(d).is_file()]
    assert not missing, f"missing fusion docs: {missing}"
    for d in FUSION_DOCS:
        assert len(Path(d).read_text(encoding="utf-8").strip()) > 200, f"doc too small: {d}"
